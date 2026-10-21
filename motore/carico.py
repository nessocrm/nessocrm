"""Regole del carico, senza Espo e senza rete.

Il giro le applica. I test le verificano da sole.
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import re
import secrets
from datetime import datetime, timedelta

OWNERS = ("sorgente", "espo")
CLOSE_CANDIDATES = ("status", "stage", "cStato", "stato")
PAGE_SIZE = 200


def owner_of(rule: dict) -> str:
    value = rule.get("owner") or "sorgente"
    if value not in OWNERS:
        raise RuntimeError("il padrone del campo è la sorgente oppure Espo")
    return value


def plan_fields(fields: list[dict], current: dict | None, creating: bool) -> tuple[dict, list[dict]]:
    """Decide che cosa scrivere e che cosa finisce in coda.

    fields: to, owner, present, value. current sono i valori già in Espo.
    In creazione non c'è un ritocco umano: si scrive anche un campo tenuto da Espo.
    In aggiornamento un campo tenuto da Espo, se il valore è diverso, non si tocca.
    """
    current = current or {}
    write: dict = {}
    watch: list[dict] = []
    for field in fields:
        name = field["to"]
        owner = owner_of(field)
        present = bool(field.get("present"))
        value = "" if field.get("value") is None else str(field.get("value"))
        if owner == "espo" and not creating:
            if not present or value == "":
                continue
            already = "" if current.get(name) is None else str(current.get(name))
            if already and already != value:
                watch.append({"field": name, "today": already, "incoming": value})
                continue
        if owner == "sorgente":
            if not present:
                continue
            write[name] = value
            continue
        if present and value != "":
            write[name] = value
    return write, watch


def dangerous_diffs(watch: list[dict]) -> list[dict]:
    return [
        {"field": item["field"], "today": item["today"], "incoming": item["incoming"]}
        for item in watch
    ]


def classify_row(existing: bool, write: dict, previous: dict | None, watch: list[dict]) -> str:
    if watch and not write:
        return "in coda"
    if not existing:
        return "creato"
    if previous is not None and write == previous:
        return "invariato"
    return "aggiornato"


def parse_date(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise RuntimeError("data vuota")
    candidates = (
        (text, "%d/%m/%Y"),
        (text[:10], "%Y-%m-%d"),
        (text, "%d-%m-%Y"),
    )
    for chunk, fmt in candidates:
        try:
            return datetime.strptime(chunk, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise RuntimeError(f"data non riconosciuta: {text}")


def normalize_fiscal(value: str) -> tuple[str, str]:
    raw = str(value or "").strip().upper()
    raw = raw.replace(" ", "").replace(".", "").replace("-", "")
    if raw.startswith("IT") and raw[2:].isdigit():
        raw = raw[2:]
    if re.fullmatch(r"\d{11}", raw):
        return "piva", raw
    if re.fullmatch(r"[A-Z0-9]{16}", raw):
        return "cf", raw
    raise RuntimeError("partita IVA o codice fiscale non valido")


def fiscal_blocks_create(found_id: str | None, current_id: str | None) -> bool:
    return bool(found_id) and found_id != (current_id or "")


def enum_value(value: str, options: list[str]) -> str:
    text = str(value or "").strip()
    if text in options:
        return text
    raise RuntimeError(f"valore non previsto: {text}")


def check_quality(value: str, kind: str | None, options: list[str] | None, field: str) -> str:
    if kind == "date":
        try:
            return parse_date(value)
        except RuntimeError as error:
            raise RuntimeError(f"campo {field}: {error}") from error
    if kind == "fiscale":
        try:
            _kind, normal = normalize_fiscal(value)
        except RuntimeError as error:
            raise RuntimeError(f"campo {field}: {error}") from error
        return normal
    if kind == "enum":
        try:
            return enum_value(value, options or [])
        except RuntimeError as error:
            raise RuntimeError(f"campo {field}: {error}") from error
    return value


def is_fiscal_field(name: str, label: str = "") -> bool:
    text = f"{name} {label}".lower().replace(" ", "").replace("_", "")
    return any(token in text for token in ("partitaiva", "partita", "piva", "vat", "codicefiscale", "fiscalcode"))


def required_columns(external_id: str, rules: list[dict], extras: list[str] | None = None) -> list[str]:
    columns = []
    for name in [external_id, *(extras or [])]:
        text = str(name or "").strip()
        if text and text not in columns:
            columns.append(text)
    for rule in rules:
        source = str(rule.get("from") or "")
        if rule.get("required") and source and not source.startswith("_"):
            if source not in columns:
                columns.append(source)
    return columns


def missing_headers(headers: list[str], required: list[str]) -> list[str]:
    have = {str(name).strip() for name in headers if str(name).strip()}
    return [name for name in required if name not in have]


def collect_pages(fetch, page_size: int = PAGE_SIZE) -> list:
    offset = 0
    rows: list = []
    while True:
        page = list(fetch(page_size, offset))
        rows.extend(page)
        if len(page) < page_size:
            return rows
        offset += page_size


def fixed_due(schedule_at: str, last_run: str | None, now: datetime) -> bool:
    hour, minute = _clock(schedule_at)
    slot = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now < slot:
        return False
    if not last_run:
        return True
    previous = datetime.strptime(last_run, "%Y-%m-%d %H:%M:%S")
    return previous < slot


def _clock(value: str) -> tuple[int, int]:
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{2}:\d{2}", text):
        raise RuntimeError("l'orario è nel formato 02:10")
    hour, minute = (int(part) for part in text.split(":"))
    if hour > 23 or minute > 59:
        raise RuntimeError("l'orario è nel formato 02:10")
    return hour, minute


def read_deadline(hours: int, now: datetime) -> str:
    span = hours if hours and hours > 0 else 48
    return (now + timedelta(hours=span)).strftime("%Y-%m-%d %H:%M:%S")


def reading(read_only: bool, writes_enabled: bool) -> tuple[bool, str]:
    if not writes_enabled:
        return True, "le scritture verso Espo sono ferme"
    if read_only:
        return True, "modalità lettura"
    return False, ""


def restorable(previous: str, written: str, current: str | None) -> bool:
    if current is None:
        return False
    return str(current) == str(written)


def disappeared(known: set[str], seen: set[str]) -> list[str]:
    return sorted(known - seen)


def close_decision(
    missing: list[str],
    confirmed: bool,
    has_status: bool,
    cursor_active: bool,
) -> dict:
    if cursor_active:
        return {"action": "salta", "reason": "con la colonna di variazione non si sa chi è sparito", "keys": []}
    if not missing:
        return {"action": "niente", "reason": "", "keys": []}
    if not has_status:
        return {"action": "salta", "reason": "la scheda non ha uno stato di chiusura", "keys": missing}
    if not confirmed:
        return {"action": "conferma", "reason": "la prima chiusura va confermata", "keys": missing}
    return {"action": "chiudi", "reason": "", "keys": missing}


def close_field_of(names: list[str], options: dict[str, list[str]] | None = None) -> tuple[str, str] | None:
    options = options or {}
    for name in CLOSE_CANDIDATES:
        if name not in names:
            continue
        choices = options.get(name) or []
        if choices and "Closed" not in choices and "Chiuso" not in choices:
            continue
        value = "Chiuso" if "Chiuso" in choices else "Closed"
        return name, value
    return None


def column_samples(rows: list[dict], source: str, interpret=None, limit: int = 3) -> dict:
    values = []
    interpreted = []
    for row in rows:
        if len(values) >= limit:
            break
        raw = "" if row.get(source) is None else str(row.get(source))
        values.append(raw)
        if interpret is None:
            interpreted.append(raw)
        else:
            try:
                interpreted.append(interpret(raw))
            except Exception as error:
                interpreted.append(str(error))
    return {"from": source, "values": values, "interpreted": interpreted}


def success_stamp(last_success: str | None, last_run: str | None, last_status: str | None, counts: dict | None) -> str | None:
    if last_success:
        return last_success
    _source, aligned = alignment_counts(counts)
    if last_status == "ok" and last_run and aligned:
        return last_run
    return None


def alignment_counts(counts: dict | None) -> tuple[int, int]:
    if not counts:
        return 0, 0
    aligned = int(counts.get("created") or 0) + int(counts.get("updated") or 0) + int(counts.get("unchanged") or 0)
    source = aligned + int(counts.get("failed") or 0) + int(counts.get("queued") or 0)
    return source, aligned


def morning_alignment(
    source_count: int,
    aligned_count: int,
    last_success: str | None,
    last_status: str | None,
    now: datetime,
) -> dict:
    if not last_success:
        return {
            "percent": None,
            "tone": "mai",
            "today": False,
            "successAt": None,
            "text": "Nessun giro di anagrafiche è riuscito.",
            "textKey": "Nessun giro di anagrafiche è riuscito.",
            "textParams": {},
        }
    today = now.strftime("%Y-%m-%d")
    success_today = last_success[:10] == today and last_status == "ok"
    percent = int(round(aligned_count * 100 / source_count)) if source_count > 0 else None
    hour = last_success[11:16]
    if success_today:
        if percent is None:
            key = "Giro riuscito alle {hour}. Non c'è ancora un confronto."
            text = f"Giro riuscito alle {hour}. Non c'è ancora un confronto."
        else:
            key = "{percent}% di anagrafiche allineate. Ultimo giro riuscito alle {hour}."
            text = f"{percent}% di anagrafiche allineate. Ultimo giro riuscito alle {hour}."
        return {
            "percent": percent,
            "tone": "ok",
            "today": True,
            "successAt": last_success,
            "text": text,
            "textKey": key,
            "textParams": {"percent": percent if percent is not None else "", "hour": hour},
        }
    if last_status not in (None, "ok"):
        text = f"Il giro di oggi non è riuscito. L'ultimo successo resta il {last_success}."
        tone = "rosso"
        key = "Il giro di oggi non è riuscito. L'ultimo successo resta il {quando}."
    else:
        text = f"Oggi non c'è ancora un giro riuscito. L'ultimo successo è il {last_success}."
        tone = "attesa"
        key = "Oggi non c'è ancora un giro riuscito. L'ultimo successo è il {quando}."
    return {
        "percent": None,
        "tone": tone,
        "today": False,
        "successAt": last_success,
        "text": text,
        "textKey": key,
        "textParams": {"quando": last_success},
    }


def parse_amount(value) -> float:
    text = str(value or "").strip().replace(" ", "").replace("€", "")
    if not text:
        return 0.0
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return round(float(text), 2)
    except ValueError:
        return 0.0


def quadratura(
    source_keys: set[str],
    espo_keys: set[str],
    source_amount: float | None,
    espo_amount: float | None,
) -> dict:
    only_source = source_keys - espo_keys
    only_espo = espo_keys - source_keys
    gap = None
    if source_amount is not None and espo_amount is not None:
        gap = round(source_amount - espo_amount, 2)
    ok = not only_source and not only_espo and gap in (None, 0, 0.0)
    parts = [f"{len(source_keys)} in sorgente, {len(espo_keys)} in Espo"]
    if only_source:
        parts.append(f"{len(only_source)} solo in sorgente")
    if only_espo:
        parts.append(f"{len(only_espo)} solo in Espo")
    if gap not in (None, 0, 0.0):
        parts.append(f"scarto importi {gap}")
    text = ("Quadratura: " if ok else "Quadratura rossa: ") + ", ".join(parts) + "."
    return {
        "sourceCount": len(source_keys),
        "espoCount": len(espo_keys),
        "onlySource": len(only_source),
        "onlyEspo": len(only_espo),
        "sourceAmount": source_amount,
        "espoAmount": espo_amount,
        "amountGap": gap,
        "ok": ok,
        "text": text,
    }


def file_wait(now: datetime, expect_at: str, last_success: str | None, has_file: bool) -> str:
    hour, minute = _clock(expect_at)
    slot = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now < slot:
        return "presto"
    if last_success and last_success[:10] == now.strftime("%Y-%m-%d"):
        return "ok"
    if has_file:
        return "in_attesa"
    return "mancante"


def badge_gestionale(when: datetime, lingua: str = "it") -> str:
    import frasi
    return frasi.traduci(
        "aggiornato dal gestionale il {data} alle {ora}",
        lingua,
        data=when.strftime("%d/%m/%Y"),
        ora=when.strftime("%H:%M"),
    )


def badge_persona(name: str, when: datetime, lingua: str = "it") -> str:
    import frasi
    return frasi.traduci(
        "ultimo ritocco di {nome} il {data} alle {ora}",
        lingua,
        nome=name,
        data=when.strftime("%d/%m/%Y"),
        ora=when.strftime("%H:%M"),
    )


def badge_decision(
    stored_at: str | None,
    modified_at: str | None,
    modified_by: str | None,
    engine_names: set[str],
) -> str:
    author = str(modified_by or "").strip()
    stamp = str(modified_at or "").strip()
    if not author or not stamp:
        return "niente"
    known = {item.lower() for item in engine_names}
    if author.lower() in known:
        return "niente"
    if stored_at and stamp <= stored_at:
        return "niente"
    return "persona"


def summary_line(counts: dict, prefix: str) -> str:
    detail = (
        f"{prefix}, {counts.get('created', 0)} create, {counts.get('updated', 0)} aggiornate, "
        f"{counts.get('closed', 0)} chiuse, {counts.get('unchanged', 0)} invariate, "
        f"{counts.get('failed', 0)} scartate"
    )
    if counts.get("held"):
        detail += ", senza scrivere"
    if counts.get("first"):
        detail += ". " + str(counts["first"])
    return detail


def compile_visibility(rule: dict) -> list[dict]:
    team_from = str(rule.get("teamFrom") or "").strip()
    team_const = str(rule.get("team") or "").strip()
    assign_from = str(rule.get("assignFrom") or "").strip()
    miss = rule.get("onMiss") or "skip"
    if miss not in ("fail", "skip", "create"):
        raise RuntimeError("se il team non c'è si scarta la riga, si lascia vuoto o si crea il team")
    if miss == "create" and assign_from:
        raise RuntimeError("un utente non si crea da un'anagrafica")
    compiled = []
    if team_const and not team_from:
        compiled.append({
            "from": "_visibility_team",
            "to": "teamsIds",
            "transform": "lookups",
            "lookupEntity": "Team",
            "lookupBy": "name",
            "onMiss": miss,
            "constValue": team_const,
            "owner": "sorgente",
            "role": "visibility",
        })
    elif team_from:
        compiled.append({
            "from": team_from,
            "to": "teamsIds",
            "transform": "lookups",
            "lookupEntity": "Team",
            "lookupBy": "name",
            "onMiss": miss,
            "owner": "sorgente",
            "role": "visibility",
        })
    if assign_from:
        compiled.append({
            "from": assign_from,
            "to": "assignedUserId",
            "transform": "lookup",
            "lookupEntity": "User",
            "lookupBy": "userName",
            "onMiss": "skip" if miss == "create" else miss,
            "owner": "sorgente",
            "role": "visibility",
            "neverCreate": True,
        })
    if not compiled:
        raise RuntimeError("indica il team o la persona")
    return compiled


def _fold(name: str) -> str:
    text = str(name or "").strip().lower()
    for src, dst in (("à", "a"), ("è", "e"), ("é", "e"), ("ì", "i"), ("ò", "o"), ("ù", "u")):
        text = text.replace(src, dst)
    text = text.replace(".", " ").replace("_", " ").replace("-", " ")
    return " ".join(text.split())


_PROPOSTE = {
    "it": (
        (("ragione sociale", "denominazione", "nome azienda", "nome cliente"), "name", ""),
        (("partita iva", "p iva", "piva", "partitaiva"), "fiscale", "fiscale"),
        (("codice fiscale",), "fiscale", "fiscale"),
        (("email", "e mail", "mail", "posta elettronica"), "emailAddress", ""),
        (("telefono", "tel", "cellulare"), "phoneNumber", ""),
        (("citta", "comune", "localita"), "billingAddressCity", ""),
        (("codice", "codice cliente", "id cliente", "codice esterno"), "identity", ""),
    ),
    "en": (
        (("company name", "business name", "account name", "customer name"), "name", ""),
        (("vat", "vat number", "tax id", "vat no"), "fiscale", "fiscale"),
        (("email", "e mail", "mail"), "emailAddress", ""),
        (("phone", "telephone", "mobile"), "phoneNumber", ""),
        (("city", "town"), "billingAddressCity", ""),
        (("code", "customer code", "external id", "account code"), "identity", ""),
    ),
}


def _named(fields: list[dict] | None) -> dict[str, str]:
    found = {}
    for field in fields or []:
        name = str(field.get("name") or "")
        if name:
            found[name] = str(field.get("label") or "")
    return found


def _fiscal_target(fields: list[dict] | None) -> str:
    for field in fields or []:
        name = str(field.get("name") or "")
        if name and is_fiscal_field(name, str(field.get("label") or "")):
            return name
    return ""


def _target(token: str, fields: list[dict] | None) -> str:
    if token == "identity":
        return ""
    if token == "fiscale":
        return _fiscal_target(fields)
    if token in _named(fields):
        return token
    return ""


def propose_column(name: str, lingua: str = "it", fields: list[dict] | None = None) -> dict:
    folded = _fold(name)
    table = _PROPOSTE.get(lingua if lingua in _PROPOSTE else "it", _PROPOSTE["it"])
    for aliases, token, kind in table:
        if folded in aliases:
            return {
                "from": name,
                "to": _target(token, fields),
                "kind": kind,
                "role": "identity" if token == "identity" else "field",
                "known": True,
            }
    return {"from": name, "to": "", "kind": "", "role": "field", "known": False}


def _cell_reading(value: str) -> str:
    try:
        return parse_date(value)
    except RuntimeError:
        return value


def propose(
    columns: list[str],
    lingua: str = "it",
    fields: list[dict] | None = None,
    samples: list[dict] | None = None,
) -> list[dict]:
    rows = []
    for name in columns:
        row = propose_column(str(name), lingua, fields)
        raw = ""
        for sample in samples or []:
            if not isinstance(sample, dict):
                continue
            value = str(sample.get(name) or "").strip()
            if value:
                raw = value
                break
        row["sample"] = raw
        row["reading"] = _cell_reading(raw) if raw else ""
        rows.append(row)
    return rows


def _present(fields: list[dict] | None, name: str) -> str:
    return name if name in _named(fields) else ""


def _field_row(source: str, target: str, kind: str = "") -> dict:
    return {"from": source, "to": target, "role": "field", "kind": kind}


def recipe_anagrafiche(fields: list[dict] | None = None) -> dict:
    fiscal = _fiscal_target(fields)
    return {
        "id": "anagrafiche",
        "entity": "Account",
        "externalIdField": "codice",
        "rows": [
            _field_row("ragione sociale", _present(fields, "name")),
            _field_row("partita iva", fiscal, "fiscale"),
            _field_row("email", _present(fields, "emailAddress")),
            _field_row("telefono", _present(fields, "phoneNumber")),
            _field_row("città", _present(fields, "billingAddressCity")),
        ],
        "noteKey": "Non è un connettore certificato con un gestionale. È un abbinamento pronto da rivedere.",
    }


def recipe_contatti(fields: list[dict] | None = None) -> dict:
    return {
        "id": "contatti",
        "entity": "Contact",
        "externalIdField": "codice",
        "rows": [
            _field_row("nome", _present(fields, "firstName")),
            _field_row("cognome", _present(fields, "lastName")),
            _field_row("email", _present(fields, "emailAddress")),
            _field_row("telefono", _present(fields, "phoneNumber")),
            {
                "from": "azienda",
                "to": "Account",
                "role": "link",
                "kind": "",
                "lookupEntity": "Account",
                "lookupBy": "name",
                "onMiss": "fail",
            },
        ],
        "noteKey": "Il contatto si lega all'azienda per nome. Se il file ha il codice cliente, cambia il campo di ricerca. Non è un connettore certificato.",
    }


def recipe_sedi(fields: list[dict] | None = None) -> dict:
    return {
        "id": "sedi",
        "entity": "Account",
        "externalIdField": "codice",
        "rows": [
            _field_row("indirizzo", _present(fields, "shippingAddressStreet")),
            _field_row("cap", _present(fields, "shippingAddressPostalCode")),
            _field_row("città", _present(fields, "shippingAddressCity")),
            _field_row("provincia", _present(fields, "shippingAddressState")),
            _field_row("nazione", _present(fields, "shippingAddressCountry")),
        ],
        "noteKey": "Una sede per azienda, sull'indirizzo di spedizione. Non è un'anagrafica di più sedi, e non è un connettore certificato.",
    }


def recipe_listino(fields: list[dict] | None = None) -> dict:
    price = _present(fields, "unitPrice") or _present(fields, "listPrice")
    currency = _present(fields, "unitPriceCurrency") or _present(fields, "listPriceCurrency")
    return {
        "id": "listino",
        "entity": "Product",
        "externalIdField": "codice",
        "rows": [
            _field_row("descrizione", _present(fields, "name")),
            _field_row("codice", _present(fields, "partNumber")),
            _field_row("prezzo", price),
            _field_row("valuta", currency),
        ],
        "noteKey": "Il listino scrive il Product di Espo, se la scheda c'è già. Non crea una scheda. Non è un connettore certificato.",
    }


def listino_payload(row: dict) -> dict:
    """La riga del listino diventa campi di Product. Non nomina una scheda nuova."""
    return {
        "entity": "Product",
        "name": str(row.get("descrizione") or row.get("name") or "").strip(),
        "partNumber": str(row.get("codice") or "").strip(),
        "unitPrice": row.get("prezzo"),
        "unitPriceCurrency": str(row.get("valuta") or "").strip(),
    }


def _bounded(text: str, token: str) -> bool:
    start = 0
    while True:
        at = text.find(token, start)
        if at < 0:
            return False
        before = text[at - 1] if at else ""
        after_at = at + len(token)
        after = text[after_at] if after_at < len(text) else ""
        if not before.isalnum() and not after.isalnum():
            return True
        start = at + 1


def match_pdf(filename: str, keys: list[str] | None) -> str:
    """La chiave deve stare nel nome come parola intera. Fra due chiavi vince la più lunga."""
    name = str(filename or "").replace("\\", "/").split("/")[-1]
    best = ""
    for key in keys or []:
        token = str(key or "").strip()
        if len(token) < 3 or len(token) <= len(best):
            continue
        if _bounded(name, token):
            best = token
    return best


def stage_proposal(current: str, proposed: str) -> str:
    """Restituisce il valore da proporre. Se è già quello, non c'è nulla da confermare."""
    incoming = str(proposed or "").strip()
    if not incoming or str(current or "").strip() == incoming:
        return ""
    return incoming


def privacy_export(rows: list[dict] | None, contact: str, company: str) -> list[dict]:
    """Ciò che Nesso ha scritto su quel contatto e su quell'azienda. Non toglie righe."""
    wanted = {str(contact or "").strip(), str(company or "").strip()}
    wanted.discard("")
    if not wanted:
        return []
    exported = []
    for row in rows or []:
        field = str(row.get("field") or "")
        if "password" in field.lower():
            continue
        ident = {str(row.get("external_key") or ""), str(row.get("espo_id") or "")}
        if not (wanted & ident):
            continue
        exported.append({
            "at": row.get("at") or "",
            "entity": row.get("entity") or "",
            "key": row.get("external_key") or "",
            "field": field,
            "value": "" if row.get("value") is None else str(row.get("value")),
        })
    return exported


def is_field_rule(rule: dict) -> bool:
    transform = str(rule.get("transform") or "copy")
    if transform in ("lookup", "lookups", "file"):
        return False
    if rule.get("parentType") or rule.get("role") in ("link", "links", "parent", "visibility"):
        return False
    if str(rule.get("to") or "") == "parentId":
        return False
    return True


_SHEET = {
    "it": ("Integrazione", "Colonna", "Campo", "Trasformazione", "Padrone", "Obbligatorio"),
    "en": ("Integration", "Column", "Field", "Transform", "Owner", "Required"),
}
_SHEET_KEY = ("pipeline", "from", "to", "transform", "owner", "required")
_TRANSFORMS = ("copy", "split_first", "split_last", "map", "const")


def sheet_csv(pipelines: list[dict], lingua: str = "it") -> str:
    chosen = "en" if lingua == "en" else "it"
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow(_SHEET[chosen])
    yes = "yes" if chosen == "en" else "si"
    no = "no"
    for item in pipelines or []:
        if item.get("direction") not in (None, "in"):
            continue
        for rule in item.get("mapping") or []:
            if not is_field_rule(rule):
                continue
            writer.writerow([
                item.get("id") or "",
                rule.get("from") or "",
                rule.get("to") or "",
                rule.get("transform") or "copy",
                rule.get("owner") or "sorgente",
                yes if rule.get("required") else no,
            ])
    return "\ufeff" + buffer.getvalue()


def _sheet_index(header: list[str]) -> dict[str, int]:
    cells = [cell.strip() for cell in header]
    for labels in _SHEET.values():
        if cells[: len(labels)] == list(labels):
            return {key: index for index, key in enumerate(_SHEET_KEY)}
    raise RuntimeError("il foglio non è un abbinamento")


def _owner_token(value: str) -> str:
    token = str(value or "").strip().lower()
    if token in ("", "sorgente", "source"):
        return "sorgente"
    if token == "espo":
        return "espo"
    raise RuntimeError("il padrone del campo è la sorgente oppure Espo")


def parse_sheet(text: str) -> list[dict]:
    raw = str(text or "").lstrip("\ufeff").strip()
    if not raw:
        raise RuntimeError("il foglio è vuoto")
    rows = list(csv.reader(io.StringIO(raw), delimiter=";"))
    if not rows:
        raise RuntimeError("il foglio è vuoto")
    index = _sheet_index(rows[0])
    parsed = []
    for cells in rows[1:]:
        if not any(str(cell).strip() for cell in cells):
            continue

        def cell(name: str) -> str:
            position = index[name]
            return cells[position].strip() if position < len(cells) else ""

        flag = cell("required").lower()
        parsed.append({
            "pipeline": cell("pipeline"),
            "from": cell("from"),
            "to": cell("to"),
            "transform": cell("transform") or "copy",
            "owner": cell("owner"),
            "required": flag in ("si", "sì", "yes", "true", "1"),
        })
    if not parsed:
        raise RuntimeError("il foglio non ha righe")
    return parsed


def apply_sheet(mapping: list[dict], rows: list[dict]) -> list[dict]:
    kept = [dict(rule) for rule in mapping or [] if not is_field_rule(rule)]
    previous = {str(rule.get("from")): rule for rule in mapping or [] if is_field_rule(rule)}
    fields = []
    seen: set[str] = set()
    for row in rows:
        source = str(row.get("from") or "").strip()
        target = str(row.get("to") or "").strip()
        if not source or not target:
            continue
        if source in seen:
            raise RuntimeError(f"colonna ripetuta {source}")
        seen.add(source)
        transform = str(row.get("transform") or "copy").strip() or "copy"
        if not (transform in _TRANSFORMS or transform.startswith("const:")):
            raise RuntimeError("trasformazione non riconosciuta")
        base = previous.get(source) or {}
        if transform == "const":
            old = str(base.get("transform") or "")
            transform = old if old.startswith("const:") else "const:"
        item = {
            "from": source,
            "to": target,
            "transform": transform,
            "owner": _owner_token(str(row.get("owner") or "")),
        }
        if transform == "map" and isinstance(base.get("valueMap"), dict):
            item["valueMap"] = base["valueMap"]
        if row.get("required"):
            item["required"] = True
        fields.append(item)
    result = kept + fields
    if not result:
        raise RuntimeError("il foglio non ha abbinamenti")
    return result


def consegna(
    public_base: str,
    espo_public: str,
    writes_enabled: bool,
    pipelines: list[dict] | None,
    connections: list[dict] | None,
    windows: list[dict] | None,
) -> dict:
    links = {
        item.get("id"): {"name": item.get("name") or "", "kind": item.get("kind") or ""}
        for item in connections or []
    }
    integrations = []
    for item in pipelines or []:
        owners = []
        for rule in item.get("mapping") or []:
            if not is_field_rule(rule):
                continue
            owners.append({
                "from": rule.get("from") or "",
                "to": rule.get("to") or "",
                "owner": rule.get("owner") or "sorgente",
            })
        link = links.get(item.get("connection_id")) or {}
        integrations.append({
            "name": item.get("name") or item.get("id") or "",
            "entity": item.get("espo_entity") or "",
            "direction": item.get("direction") or "in",
            "enabled": item.get("enabled") not in (0, False, "0"),
            "scheduleAt": item.get("schedule_at") or "",
            "scheduleMinutes": int(item.get("schedule_minutes") or 0),
            "connection": link.get("name") or "",
            "readOnly": bool(item.get("read_only")),
            "owners": owners,
        })
    silence = []
    for window in windows or []:
        silence.append({
            "start": window.get("start_on") or window.get("start") or "",
            "end": window.get("end_on") or window.get("end") or "",
            "reason": window.get("reason") or "",
            "pipelineId": window.get("pipeline_id") or "",
        })
    return {
        "nesso": str(public_base or ""),
        "espo": str(espo_public or ""),
        "writesEnabled": bool(writes_enabled),
        "integrations": integrations,
        "silence": silence,
    }


def parse_day(value: str) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise RuntimeError("il giorno è nel formato 2026-10-19")
    datetime.strptime(text, "%Y-%m-%d")
    return text


def silence_decision(day: str, windows: list[dict] | None, held: bool) -> dict:
    """Senza finestre e senza un file fermo, l'azione è scrivere."""
    today = str(day or "")[:10]
    for window in windows or []:
        start = str(window.get("start") or "")
        end = str(window.get("end") or "")
        if start and end and start <= today <= end:
            return {"action": "attesa", "reason": str(window.get("reason") or "")}
    if held:
        return {"action": "fermo", "reason": "la finestra è finita e il file è in attesa"}
    return {"action": "scrivi", "reason": ""}


def step_may_enable(in_plan: bool, position: int, previous_confirmed: bool) -> tuple[bool, str]:
    if not in_plan or int(position or 1) <= 1:
        return True, ""
    if previous_confirmed:
        return True, ""
    return False, "il gradino precedente non è stato confermato"


def compose_identity(payload: dict, columns: list[str]) -> str:
    """Una colonna restituisce la cella, senza separatore. Due o più si uniscono con |."""
    names = [str(name).strip() for name in columns if str(name).strip()]
    if len(names) <= 1:
        name = names[0] if names else ""
        return str(payload.get(name) or "").strip()
    parts = []
    for name in names:
        value = str(payload.get(name) or "").strip()
        if not value:
            raise RuntimeError(f"manca il campo {name}")
        if "|" in value:
            raise RuntimeError(f"campo {name}: il valore non può contenere |")
        parts.append(value)
    return "|".join(parts)


def password_record(password: str, salt: bytes | None = None) -> str:
    raw = salt if salt is not None else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), raw, 120_000)
    return raw.hex() + "$" + digest.hex()


def password_matches(password: str, record: str) -> bool:
    salt_hex, _, digest_hex = str(record or "").partition("$")
    if not salt_hex or not digest_hex:
        return False
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return hmac.compare_digest(digest.hex(), digest_hex)


def gesture_can(gesture: str, method: str, path: str) -> bool:
    """Chi cambia fa tutto. Chi lancia esegue e legge, e non modifica un abbinamento."""
    if gesture == "cambia":
        return True
    if gesture != "lancia":
        return False
    verb = method.upper()
    if verb in ("GET", "HEAD"):
        return True
    if verb != "POST":
        return False
    parts = [part for part in path.split("/") if part]
    if parts in (["api", "uscita"], ["api", "privacy"]):
        return True
    if len(parts) == 3 and parts[:2] == ["api", "watch"]:
        return True
    if len(parts) == 4 and parts[:2] == ["api", "pipelines"] and parts[3] in ("run", "dry", "chiusure"):
        return True
    if len(parts) == 4 and parts[:2] == ["api", "proposte"] and parts[3] in ("conferma", "lascia"):
        return True
    if (
        len(parts) == 5
        and parts[:2] == ["api", "pipelines"]
        and parts[3] == "silenzio"
        and parts[4] in ("conferma", "scarta")
    ):
        return True
    return False


def role_scope(pipelines: list[dict]) -> list[str]:
    """Schede che l'utente di servizio può leggere e scrivere: solo le integrazioni accese."""
    found: list[str] = []

    def add(name: str) -> None:
        if name and name not in found:
            found.append(name)

    for item in pipelines:
        enabled = item.get("enabled", 1)
        if enabled in (0, False, "0"):
            continue
        add(str(item.get("espo_entity") or item.get("entity") or ""))
        if item.get("kind") == "pdf":
            add("Document")
            add("Attachment")
        for rule in item.get("mapping") or []:
            if not isinstance(rule, dict):
                continue
            add(str(rule.get("lookupEntity") or ""))
            add(str(rule.get("parentType") or ""))
            if rule.get("role") == "visibility":
                add("Team")
                add("User")
    return found


def role_data(entities: list[str]) -> dict:
    table = {}
    for name in entities:
        if name == "User":
            table[name] = {"create": "no", "read": "all", "edit": "no", "delete": "no", "stream": "no"}
        else:
            table[name] = {"create": "yes", "read": "all", "edit": "all", "delete": "no", "stream": "no"}
    return table


def notice_needed(open_kinds: set[str], kind: str) -> bool:
    return kind not in open_kinds


def silence_elapsed(last_success: str | None, minutes: int, now: datetime) -> bool:
    if minutes <= 0 or not last_success:
        return False
    then = _parse_stamp(last_success)
    if then is None:
        return False
    return (now - then).total_seconds() >= minutes * 60


def _parse_stamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def next_run(schedule_at: str | None, schedule_minutes: int, last_run: str | None, now: datetime) -> dict:
    if schedule_at:
        hour, minute = _clock(schedule_at)
        slot = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        previous = _parse_stamp(last_run)
        if previous and previous >= slot:
            slot += timedelta(days=1)
        if slot <= now:
            return {"text": "al prossimo controllo", "textKey": "al prossimo controllo", "textParams": {}}
        when = slot.strftime("%Y-%m-%d %H:%M")
        return {"text": f"il {when}", "textKey": "il {quando}", "textParams": {"quando": when}}
    minutes = int(schedule_minutes or 0)
    if minutes <= 0:
        return {"text": "Solo a comando", "textKey": "Solo a comando", "textParams": {}}
    previous = _parse_stamp(last_run)
    if previous is None:
        return {"text": "al prossimo controllo", "textKey": "al prossimo controllo", "textParams": {}}
    slot = previous + timedelta(minutes=minutes)
    if slot <= now:
        return {"text": "al prossimo controllo", "textKey": "al prossimo controllo", "textParams": {}}
    when = slot.strftime("%Y-%m-%d %H:%M")
    return {"text": f"il {when}", "textKey": "il {quando}", "textParams": {"quando": when}}


def _success_when(stamp: str, now: datetime) -> tuple[str, str, dict]:
    then = _parse_stamp(stamp)
    if then is None:
        return "", "", {}
    hour = then.strftime("%H:%M")
    if then.date() == now.date():
        return f"oggi alle {hour}", "oggi alle {ora}", {"ora": hour}
    if then.date() == (now - timedelta(days=1)).date():
        return f"ieri alle {hour}", "ieri alle {ora}", {"ora": hour}
    shown = then.strftime("%Y-%m-%d %H:%M")
    return f"il {shown}", "il {istante}", {"istante": shown}


def _quiet_parts(last_success: str, now: datetime) -> tuple[str, str]:
    then = _parse_stamp(last_success)
    if then is None:
        return "", ""
    seconds = max(0, int((now - then).total_seconds()))
    hours = seconds // 3600
    if hours >= 48:
        return str(hours // 24), "giorni"
    if hours >= 1:
        return str(hours), "ore"
    return str(seconds // 60), "minuti"


def run_pace(
    now: datetime,
    schedule_at: str | None,
    schedule_minutes: int,
    last_run: str | None,
    last_success: str | None,
    last_error_at: str | None,
    last_error_detail: str | None,
) -> dict:
    coming = next_run(schedule_at, schedule_minutes, last_run, now)
    if last_success and _parse_stamp(last_success):
        when_text, when_key, when_params = _success_when(last_success, now)
        amount, unit = _quiet_parts(last_success, now)
        sentence = f"Ultimo successo {when_text}, tace da {amount} {unit}."
        quiet = {
            "text": sentence,
            "textKey": "Ultimo successo {quando}, tace da {n} {unita}.",
            "textParams": {"quandoKey": when_key, "n": amount, "unita": unit, **when_params},
        }
    else:
        sentence = "Non c'è ancora un successo."
        quiet = {"text": sentence, "textKey": "Non c'è ancora un successo.", "textParams": {}}
    if last_error_at:
        shown = str(last_error_at)[:16]
        detail = str(last_error_detail or "").strip()
        if detail:
            error = {
                "text": f"il {shown}: {detail}",
                "textKey": "il {quando}: {dettaglio}",
                "textParams": {"quando": shown, "dettaglio": detail},
            }
        else:
            error = {"text": f"il {shown}", "textKey": "il {quando}", "textParams": {"quando": shown}}
    else:
        error = {"text": "nessuno", "textKey": "nessuno", "textParams": {}}
    return {"next": coming, "quiet": quiet, "error": error, "sentence": sentence}


def skip_without_date(modified_at: str, espo_id: str, stamp: str, last_id: str) -> bool:
    if modified_at or stamp or not last_id or not espo_id:
        return False
    return espo_id <= last_id


def remote_file_names(names: list[str]) -> list[str]:
    found = []
    for name in names:
        raw = str(name or "").replace("\\", "/").strip("/")
        lowered = raw.lower()
        if lowered.startswith("elaborati/") or "/elaborati/" in f"/{lowered}":
            continue
        clean = raw.split("/")[-1]
        if not clean or clean.startswith("."):
            continue
        if clean.lower().endswith((".csv", ".xlsx")):
            found.append(clean)
    return sorted(set(found), key=str.lower)


def rows_from_bytes(name: str, data: bytes) -> tuple[list[str], list[dict]]:
    if str(name).lower().endswith(".xlsx"):
        return rows_from_xlsx(data)
    text = data.decode("utf-8-sig")
    sample = text.splitlines()[:1]
    delimiter = ";" if (sample and sample[0].count(";") > sample[0].count(",")) else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = [item.strip() for item in (reader.fieldnames or []) if item and str(item).strip()]
    rows = [{key: value for key, value in row.items() if key} for row in reader]
    return headers, rows


def rows_from_xlsx(data: bytes) -> tuple[list[str], list[dict]]:
    import zipfile
    from xml.etree import ElementTree as ET

    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(data)) as book:
        names = set(book.namelist())
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(book.read("xl/sharedStrings.xml"))
            for node in root.findall("m:si", ns):
                shared.append("".join(item.text or "" for item in node.findall(".//m:t", ns)))
        sheet_name = "xl/worksheets/sheet1.xml"
        if sheet_name not in names:
            sheets = sorted(name for name in names if name.startswith("xl/worksheets/sheet"))
            if not sheets:
                return [], []
            sheet_name = sheets[0]
        root = ET.fromstring(book.read(sheet_name))
    grid: list[dict[str, str]] = []
    for row in root.findall("m:sheetData/m:row", ns):
        cells: dict[str, str] = {}
        for cell in row.findall("m:c", ns):
            ref = cell.get("r") or ""
            column = "".join(char for char in ref if char.isalpha())
            if not column:
                continue
            kind = cell.get("t")
            value = cell.find("m:v", ns)
            inline = cell.find("m:is", ns)
            if kind == "s" and value is not None and value.text and value.text.isdigit():
                index = int(value.text)
                text = shared[index] if index < len(shared) else ""
            elif kind == "inlineStr" and inline is not None:
                text = "".join(item.text or "" for item in inline.findall(".//m:t", ns))
            elif value is not None and value.text is not None:
                text = value.text
            else:
                text = ""
            cells[column] = text
        grid.append(cells)
    if not grid:
        return [], []
    letters: list[str] = []
    for cells in grid:
        for column in cells:
            if column not in letters:
                letters.append(column)
    letters.sort(key=lambda name: (len(name), name))
    paired = [(column, grid[0].get(column, "").strip()) for column in letters]
    paired = [(column, header) for column, header in paired if header]
    rows = [{header: cells.get(column, "") for column, header in paired} for cells in grid[1:]]
    return [header for _column, header in paired], rows


def csv_bytes(rows: list[dict]) -> bytes:
    headers: list[str] = []
    for row in rows:
        for key in row:
            if key not in headers:
                headers.append(str(key))
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: "" if row.get(key) is None else row.get(key) for key in headers})
    return buffer.getvalue().encode("utf-8")


def quote_ident(name: str, engine: str) -> str:
    if engine in ("postgres", "oracle"):
        return f'"{name}"'
    if engine == "mssql":
        return f"[{name}]"
    return f"`{name}`"


def page_sql(source: str, engine: str, where: str, order: str, limit: int, offset: int) -> str:
    if engine == "oracle":
        return (
            f"SELECT * FROM ({source}) sorgente {where} {order} "
            f"OFFSET {int(offset)} ROWS FETCH NEXT {int(limit)} ROWS ONLY"
        )
    if engine == "mssql":
        order_by = order or "ORDER BY (SELECT NULL)"
        return (
            f"SELECT * FROM ({source}) AS sorgente {where} {order_by} "
            f"OFFSET {int(offset)} ROWS FETCH NEXT {int(limit)} ROWS ONLY"
        )
    return (
        f"SELECT * FROM ({source}) AS sorgente {where} {order} "
        f"LIMIT {int(limit)} OFFSET {int(offset)}"
    )


ENGINES = ("mysql", "postgres", "mssql", "oracle")


def engine_port(engine: str) -> int:
    return {"postgres": 5432, "mssql": 1433, "oracle": 1521}.get(engine, 3306)


def sign_body(secret: str, body: bytes) -> str:
    return hmac.new(str(secret).encode(), body, hashlib.sha256).hexdigest()


def signature_matches(secret: str, body: bytes, presented: str) -> bool:
    if not secret:
        return True
    shown = str(presented or "").strip()
    if shown.lower().startswith("sha256="):
        shown = shown.split("=", 1)[1].strip()
    expected = sign_body(secret, body)
    if len(shown) != len(expected):
        return False
    return hmac.compare_digest(expected, shown)


def oauth_expired(obtained_at: str | None, expires_in: int, now: datetime, skew: int = 30) -> bool:
    then = _parse_stamp(obtained_at)
    if then is None or int(expires_in or 0) <= 0:
        return True
    return (now - then).total_seconds() >= int(expires_in) - skew


def identity_preview(rows: list[dict], columns: list[str], limit: int = 3) -> list[str]:
    shown = []
    for row in rows:
        if len(shown) >= limit:
            break
        if not isinstance(row, dict):
            continue
        try:
            value = compose_identity(row, columns)
        except RuntimeError:
            continue
        if value:
            shown.append(value)
    return shown


def step_may_confirm(in_plan: bool, previewed: bool) -> tuple[bool, str]:
    if not in_plan:
        return False, "questa integrazione non è in un piano"
    if not previewed:
        return False, "prima va vista l'anteprima"
    return True, ""
