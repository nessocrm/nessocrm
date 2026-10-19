"""Regole del carico, senza Espo e senza rete.

Il giro le applica. I test le verificano da sole.
"""

from __future__ import annotations

import re
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


def required_columns(external_id: str, rules: list[dict]) -> list[str]:
    columns = []
    if external_id:
        columns.append(external_id)
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
        }
    today = now.strftime("%Y-%m-%d")
    success_today = last_success[:10] == today and last_status == "ok"
    percent = int(round(aligned_count * 100 / source_count)) if source_count > 0 else None
    hour = last_success[11:16]
    if success_today:
        if percent is None:
            text = f"Giro riuscito alle {hour}. Non c'è ancora un confronto."
        else:
            text = f"{percent}% di anagrafiche allineate. Ultimo giro riuscito alle {hour}."
        return {"percent": percent, "tone": "ok", "today": True, "successAt": last_success, "text": text}
    if last_status not in (None, "ok"):
        text = f"Il giro di oggi non è riuscito. L'ultimo successo resta il {last_success}."
        tone = "rosso"
    else:
        text = f"Oggi non c'è ancora un giro riuscito. L'ultimo successo è il {last_success}."
        tone = "attesa"
    return {"percent": None, "tone": tone, "today": False, "successAt": last_success, "text": text}


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


def badge_gestionale(when: datetime) -> str:
    return f"aggiornato dal gestionale il {when.strftime('%d/%m/%Y')} alle {when.strftime('%H:%M')}"


def badge_persona(name: str, when: datetime) -> str:
    return f"ultimo ritocco di {name} il {when.strftime('%d/%m/%Y')} alle {when.strftime('%H:%M')}"


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
