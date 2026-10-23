"""Motore di integrazione locale. Parla con Espo solo via API."""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import carico
import frasi

DB_PATH = Path(os.environ.get("DB_PATH", "/data/motore.sqlite"))
ESPO_BASE = os.environ.get("ESPO_BASE_URL", "http://espocrm").rstrip("/")
ESPO_PUBLIC = os.environ.get("ESPO_PUBLIC_URL", "http://localhost:8088").rstrip("/")
ESPO_USER = os.environ.get("ESPO_USER", "admin")
ESPO_PASSWORD = os.environ.get("ESPO_PASSWORD", "locale-admin")
PORT = int(os.environ.get("LISTEN_PORT", "8091"))
PUBLIC_BASE = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8091").rstrip("/")
SCAMBIO = Path(os.environ.get("SCAMBIO_DIR", "/scambio"))
RUN_LOCKS: dict[str, threading.RLock] = {}
RUN_LOCKS_GUARD = threading.Lock()

STATE = {
    "espo": "in attesa",
    "fields": "non creati",
    "detail": "",
}

# Sulle schede standard Espo antepone "c": externalKey diventa cExternalKey.
# Sulle schede create da questa app il nome resta externalKey.
FIELDS = [
    ("Lead", "externalKey", "Chiave esterna", 180),
    ("Account", "externalKey", "Chiave esterna", 180),
]


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS pipeline (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                direction TEXT NOT NULL,
                espo_entity TEXT NOT NULL,
                external_id_field TEXT NOT NULL,
                key_template TEXT NOT NULL,
                mapping_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS queue_item (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pipeline_id TEXT NOT NULL,
                external_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                mapped_json TEXT NOT NULL,
                hash TEXT NOT NULL,
                status TEXT NOT NULL,
                espo_id TEXT,
                detail TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE (pipeline_id, external_id)
            );
            CREATE TABLE IF NOT EXISTS sink_item (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pipeline_id TEXT NOT NULL,
                espo_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cursor_state (
                pipeline_id TEXT PRIMARY KEY,
                cursor_value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS connection (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                config_json TEXT NOT NULL,
                token TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS delivery (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pipeline_id TEXT,
                connection_id TEXT,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL,
                detail TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS scarto (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pipeline_id TEXT NOT NULL,
                external_id TEXT,
                payload_json TEXT NOT NULL,
                detail TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS run_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pipeline_id TEXT NOT NULL,
                status TEXT NOT NULL,
                detail TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chiave (
                entity TEXT NOT NULL,
                external_key TEXT NOT NULL,
                espo_id TEXT NOT NULL,
                PRIMARY KEY (entity, external_key)
            );
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(pipeline)")}
        additions = {
            "key_field": "TEXT NOT NULL DEFAULT 'cExternalKey'",
            "connection_id": "TEXT",
            "schedule_minutes": "INTEGER NOT NULL DEFAULT 0",
            "last_run": "TEXT",
            "last_status": "TEXT",
            "last_detail": "TEXT",
            "depends_on": "TEXT",
            "cursor_column": "TEXT",
            "enabled": "INTEGER NOT NULL DEFAULT 1",
            "on_duplicate": "TEXT NOT NULL DEFAULT 'fail'",
            "schedule_at": "TEXT",
            "read_only": "INTEGER NOT NULL DEFAULT 0",
            "read_until": "TEXT",
            "close_confirmed": "INTEGER NOT NULL DEFAULT 0",
            "close_field": "TEXT",
            "close_value": "TEXT",
            "last_counts": "TEXT",
            "last_success": "TEXT",
            "expect_at": "TEXT",
            "file_alert": "INTEGER NOT NULL DEFAULT 0",
            "balance_json": "TEXT",
            "silence_held": "INTEGER NOT NULL DEFAULT 0",
            "key_columns": "TEXT",
            "propose_from": "TEXT",
            "propose_entity": "TEXT",
            "propose_field": "TEXT",
            "propose_value": "TEXT",
            "alert_minutes": "INTEGER",
            "depends_json": "TEXT",
            "write_back": "INTEGER NOT NULL DEFAULT 0",
            "write_fields": "TEXT",
            "activity_json": "TEXT",
            "portal_json": "TEXT",
        }
        for name, ddl in additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE pipeline ADD COLUMN {name} {ddl}")
        scarto_columns = {row["name"] for row in conn.execute("PRAGMA table_info(scarto)")}
        if "resolved" not in scarto_columns:
            conn.execute("ALTER TABLE scarto ADD COLUMN resolved INTEGER NOT NULL DEFAULT 0")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS setting (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS watch_item (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pipeline_id TEXT NOT NULL,
                external_id TEXT,
                field_name TEXT NOT NULL,
                current_value TEXT,
                incoming_value TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS field_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pipeline_id TEXT NOT NULL,
                run_at TEXT NOT NULL,
                espo_id TEXT NOT NULL,
                field_name TEXT NOT NULL,
                previous_value TEXT,
                written_value TEXT
            );
            CREATE TABLE IF NOT EXISTS badge_state (
                espo_id TEXT PRIMARY KEY,
                modified_at TEXT,
                author TEXT,
                label TEXT
            );
            CREATE TABLE IF NOT EXISTS silence_window (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pipeline_id TEXT,
                start_on TEXT NOT NULL,
                end_on TEXT NOT NULL,
                reason TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS silence_payload (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pipeline_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS mapping_version (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pipeline_id TEXT NOT NULL,
                mapping_json TEXT NOT NULL,
                author TEXT,
                saved_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sheet_field (
                entity TEXT NOT NULL,
                name TEXT NOT NULL,
                label TEXT NOT NULL,
                PRIMARY KEY (entity, name)
            );
            CREATE TABLE IF NOT EXISTS mail_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                next_at TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS retry_item (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pipeline_id TEXT NOT NULL,
                external_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                next_at TEXT NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS plan_step (
                pipeline_id TEXT PRIMARY KEY,
                plan_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                confirmed INTEGER NOT NULL DEFAULT 0,
                previewed INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS presenza (
                pipeline_id TEXT NOT NULL,
                external_key TEXT NOT NULL,
                espo_id TEXT NOT NULL,
                PRIMARY KEY (pipeline_id, external_key)
            );
            CREATE TABLE IF NOT EXISTS pending_close (
                pipeline_id TEXT NOT NULL,
                external_key TEXT NOT NULL,
                PRIMARY KEY (pipeline_id, external_key)
            );
            CREATE TABLE IF NOT EXISTS actor (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                gesture TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS session (
                token TEXT PRIMARY KEY,
                actor_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notice (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pipeline_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                detail TEXT NOT NULL,
                created_at TEXT NOT NULL,
                open INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS stage_proposal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pipeline_id TEXT NOT NULL,
                offer_key TEXT NOT NULL,
                entity TEXT NOT NULL,
                espo_id TEXT,
                field_name TEXT NOT NULL,
                proposed TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (pipeline_id, offer_key)
            );
            """
        )
        conn.execute("INSERT OR IGNORE INTO setting (key, value) VALUES ('writes', '1')")


def espo_call(
    method: str,
    path: str,
    body: dict | None = None,
    query: dict | None = None,
    *,
    user: str,
    password: str,
):
    url = ESPO_BASE + path
    if query:
        url += "?" + urllib.parse.urlencode(query, doseq=True)
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Espo-Authorization", token)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode()
            if not raw:
                return response.status, None
            return response.status, json.loads(raw)
    except urllib.error.HTTPError as error:
        raw = error.read().decode()
        try:
            parsed = json.loads(raw) if raw else {"message": error.reason}
        except json.JSONDecodeError:
            parsed = {"message": raw or error.reason}
        return error.code, parsed


def _admin_path(path: str) -> bool:
    markers = ("/Metadata", "/Admin/", "/I18n/", "/EntityManager/", "/layout/", "/api/v1/App/", "/api/v1/User", "/api/v1/Role")
    return any(marker in path for marker in markers)


def _record_entity(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 3 and parts[0] == "api" and parts[1] == "v1":
        return parts[2]
    return ""


def espo_admin(method: str, path: str, body: dict | None = None, query: dict | None = None):
    return espo_call(method, path, body, query, user=ESPO_USER, password=ESPO_PASSWORD)


def data_credentials() -> tuple[str, str]:
    user = setting_value("espo_service_user", "")
    secret = setting_value("espo_service_secret", "")
    if user and secret:
        return user, secret
    return ESPO_USER, ESPO_PASSWORD


def assert_in_role(entity: str) -> None:
    raw = setting_value("espo_role_entities", "")
    if not raw or not entity:
        return
    try:
        granted = json.loads(raw)
    except json.JSONDecodeError:
        return
    if isinstance(granted, list) and entity not in granted:
        raise RuntimeError(f"la scheda {entity} non è nel ruolo di Nesso")


def espo_request(method: str, path: str, body: dict | None = None, query: dict | None = None):
    if _admin_path(path):
        return espo_admin(method, path, body, query)
    entity = _record_entity(path)
    if entity:
        assert_in_role(entity)
    user, password = data_credentials()
    return espo_call(method, path, body, query, user=user, password=password)


def resolve_import_file(name: str) -> Path:
    raw = str(name or "").strip().replace("\\", "/")
    rel = Path(raw)
    if not raw or rel.is_absolute() or any(part == ".." for part in rel.parts):
        raise RuntimeError("file non consentito")
    roots = [Path(os.environ.get("DEMO_DIR", "/demo")), SCAMBIO]
    for root in roots:
        base = root.resolve()
        candidate = (base / rel).resolve()
        if candidate.is_file() and (candidate == base or base in candidate.parents):
            return candidate
    raise RuntimeError(f"file non trovato: {name}")


def upload_attachment(path: Path) -> str:
    mime = "application/pdf" if path.suffix.lower() == ".pdf" else "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode()
    status, result = espo_request(
        "POST",
        "/api/v1/Attachment",
        {
            "name": path.name,
            "type": mime,
            "role": "Attachment",
            "parentType": "Document",
            "field": "file",
            "file": f"data:{mime};base64,{encoded}",
        },
    )
    if status not in (200, 201) or not isinstance(result, dict) or not result.get("id"):
        raise RuntimeError(f"caricamento file HTTP {status}: {result}")
    return result["id"]


def espo_up() -> bool:
    try:
        with urllib.request.urlopen(ESPO_BASE + "/", timeout=5) as response:
            return response.status < 500
    except Exception:
        return False


def pascal_name(label: str) -> str:
    parts = re.findall(r"[A-Za-z0-9]+", label)
    if not parts:
        raise RuntimeError("il nome deve contenere lettere")
    name = "".join(part[:1].upper() + part[1:] for part in parts)
    if len(name) < 3:
        raise RuntimeError("il nome è troppo corto")
    return name[:60]


def camel_name(label: str) -> str:
    parts = re.findall(r"[A-Za-z0-9]+", label)
    if not parts:
        raise RuntimeError("il nome del campo deve contenere lettere")
    name = parts[0].lower() + "".join(part[:1].upper() + part[1:] for part in parts[1:])
    return name[:40]


def scope_is_custom(entity: str) -> bool:
    code, scope = espo_request("GET", "/api/v1/Metadata", query={"key": f"scopes.{entity}"})
    if code != 200 or not isinstance(scope, dict):
        return False
    return scope.get("module") == "Custom" or bool(scope.get("isCustom"))


def publish_field_name(entity: str, requested: str) -> str:
    if scope_is_custom(entity):
        return requested
    if len(requested) > 1 and requested[0] == "c" and requested[1].isupper():
        return requested
    return "c" + requested[0].upper() + requested[1:]


def bare_entity(name: str) -> str:
    if len(name) > 2 and name[0] == "C" and name[1].isupper():
        return name[1:]
    return name


def ensure_field(entity: str, name: str, label: str, length: int, kind: str = "varchar", options: list | None = None) -> str:
    chosen = kind if kind in FIELD_TYPES else "varchar"
    payload: dict = {"name": name, "type": chosen, "label": label}
    if chosen == "varchar":
        payload["maxLength"] = length
    if chosen == "enum":
        clean = [str(item).strip() for item in (options or []) if str(item).strip()]
        if not clean:
            raise RuntimeError("un elenco ha almeno un valore")
        payload["options"] = clean[:50]
    status, result = espo_request(
        "POST",
        f"/api/v1/Admin/fieldManager/{entity}",
        payload,
    )
    actual = publish_field_name(entity, name)
    if status in (200, 201):
        return actual
    message = ""
    if isinstance(result, dict):
        message = str(result.get("message") or result.get("messageTranslation") or result)
    if status == 409 or "already exists" in message.lower() or "exists" in message.lower():
        return actual
    raise RuntimeError(f"{entity}.{name}: HTTP {status} {message}")


FIELD_TYPES = {
    "varchar", "text", "int", "float", "date", "datetime",
    "bool", "enum", "currency", "email", "phone", "url",
}


def create_sheet(body: dict) -> dict:
    singular = str(body.get("singular") or "").strip()
    plural = str(body.get("plural") or "").strip()
    name = create_espo_entity(singular, plural)
    CATALOG["at"] = 0
    return {"name": name, "label": singular}


def add_sheet_field(entity: str, body: dict) -> dict:
    label = str(body.get("label") or "").strip()
    kind = str(body.get("type") or "").strip()
    if not label:
        raise RuntimeError("indica l'etichetta del campo")
    if kind not in FIELD_TYPES:
        raise RuntimeError("tipo di campo non riconosciuto")
    if not scope_customizable(entity):
        raise RuntimeError("questa scheda non accetta campi nuovi")
    requested = camel_name(label)
    payload: dict = {"name": requested, "type": kind, "label": label}
    if kind == "varchar":
        payload["maxLength"] = 180
    if kind == "enum":
        raw = body.get("options")
        if isinstance(raw, str):
            options = [line.strip() for line in raw.splitlines() if line.strip()]
        elif isinstance(raw, list):
            options = [str(item).strip() for item in raw if str(item).strip()]
        else:
            options = []
        if not options:
            raise RuntimeError("un elenco ha almeno un valore")
        payload["options"] = options[:50]
    if body.get("required") in (True, 1, "1", "true", "si", "sì"):
        payload["required"] = True
    status, result = espo_request("POST", f"/api/v1/Admin/fieldManager/{entity}", payload)
    actual = publish_field_name(entity, requested)
    if status not in (200, 201):
        message = ""
        if isinstance(result, dict):
            message = str(result.get("message") or result.get("messageTranslation") or result)
        if status == 409 or "already exists" in message.lower():
            raise RuntimeError("questo campo c'è già")
        raise RuntimeError(f"{entity}.{requested}: HTTP {status} {message}")
    places = None
    if isinstance(body.get("listPosition"), int):
        places = {"list": body["listPosition"]}
    if body.get("kanban") in (True, 1, "1"):
        places = places or {}
        places["kanban"] = True
    show_on_layout(entity, [actual], places)
    with connect() as conn:
        conn.execute(
            "INSERT INTO sheet_field (entity, name, label) VALUES (?, ?, ?) ON CONFLICT(entity, name) DO UPDATE SET label = excluded.label",
            (entity, actual, label),
        )
    CATALOG["at"] = 0
    return {"name": actual, "label": label, "type": kind}


CUSTOMIZABLE: dict[str, bool] = {}


def scope_customizable(entity: str) -> bool:
    if entity in CUSTOMIZABLE:
        return CUSTOMIZABLE[entity]
    code, result = espo_request(
        "GET", "/api/v1/Metadata", query={"key": f"scopes.{entity}.customizable"}
    )
    ok = code == 200 and result is True
    CUSTOMIZABLE[entity] = ok
    return ok


def links_of(entity: str) -> dict:
    code, result = espo_request("GET", "/api/v1/Metadata", query={"key": f"entityDefs.{entity}.links"})
    if code != 200 or not isinstance(result, dict):
        return {}
    return result


def create_espo_entity(singular: str, plural: str) -> str:
    status, result = espo_request(
        "POST",
        "/api/v1/EntityManager/action/createEntity",
        {
            "name": pascal_name(singular),
            "type": "Base",
            "labelSingular": singular.strip(),
            "labelPlural": plural.strip(),
            "stream": False,
        },
    )
    if status not in (200, 201) or not isinstance(result, dict) or not result.get("name"):
        raise RuntimeError(f"creazione scheda HTTP {status}: {result}")
    name = result["name"]
    ensure_field(name, "externalKey", "Chiave esterna", 180)
    CATALOG["at"] = 0
    return name


def create_lookup(entity: str, foreign: str, label: str, back_label: str | None = None, wanted: str | None = None) -> str:
    existing = links_of(entity)
    matches = [
        link_name
        for link_name, link in existing.items()
        if isinstance(link, dict) and link.get("type") == "belongsTo" and link.get("entity") == foreign
    ]
    chosen = carico.link_choice(matches, wanted or "")
    if chosen and chosen in matches:
        return chosen
    if not wanted and len(matches) == 1:
        return matches[0]
    source = bare_entity(foreign)
    source = source[0].lower() + source[1:]
    foreign_name = bare_entity(entity)
    if not foreign_name.endswith("s"):
        foreign_name += "s"
    foreign_name = foreign_name[0].lower() + foreign_name[1:]
    candidate = chosen or source
    taken = set(existing)
    suffix = 2
    while candidate in taken:
        candidate = f"{source}{suffix}"
        suffix += 1
    status, result = espo_request(
        "POST",
        "/api/v1/EntityManager/action/createLink",
        {
            "entity": entity,
            "link": candidate,
            "entityForeign": foreign,
            "linkForeign": foreign_name,
            "label": label,
            "labelForeign": back_label or bare_entity(entity),
            "linkType": "manyToOne",
        },
    )
    if status not in (200, 201):
        raise RuntimeError(f"collegamento verso {foreign} HTTP {status}: {result}")
    refreshed = links_of(entity)
    for link_name, link in refreshed.items():
        if link_name in existing:
            continue
        if isinstance(link, dict) and link.get("type") == "belongsTo" and link.get("entity") == foreign:
            return link_name
    if candidate in refreshed:
        return candidate
    raise RuntimeError(f"collegamento verso {foreign} non comparso nel metadata")


def show_on_layout(entity: str, names: list[str], places: dict | None = None) -> None:
    wanted = [name for name in names if name and name != "name"]
    if not wanted:
        return
    code, current = espo_request("GET", f"/api/v1/{entity}/layout/detail")
    panels = current if code == 200 and isinstance(current, list) else []
    if not panels or not isinstance(panels[0], dict) or "rows" not in panels[0]:
        panels = [{"label": "Overview", "rows": [[{"name": "name", "fullWidth": True}]]}]
    present = {
        cell.get("name")
        for panel in panels if isinstance(panel, dict)
        for row in panel.get("rows") or [] if isinstance(row, list)
        for cell in row if isinstance(cell, dict)
    }
    extra = [name for name in wanted if name not in present]
    if not extra:
        return
    rows = panels[0]["rows"]
    pair: list[dict] = []
    for name in extra:
        pair.append({"name": name})
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    status, result = espo_request("PUT", f"/api/v1/{entity}/layout/detail", panels)
    if status not in (200, 201):
        raise RuntimeError(f"layout scheda HTTP {status}: {result}")
    code, columns = espo_request("GET", f"/api/v1/{entity}/layout/list")
    cols = columns if code == 200 and isinstance(columns, list) else [{"name": "name", "link": True}]
    listed = {col.get("name") for col in cols if isinstance(col, dict)}
    changed = False
    for name in extra:
        if name not in listed:
            if places and isinstance(places.get("list"), int):
                names_only = [col.get("name") for col in cols if isinstance(col, dict)]
                ordered = carico.place_names(names_only, name, places["list"])
                rebuilt = []
                by_name = {col.get("name"): col for col in cols if isinstance(col, dict)}
                for item in ordered:
                    rebuilt.append(by_name.get(item) or {"name": item})
                cols = rebuilt
            else:
                cols.append({"name": name})
            changed = True
    if changed:
        espo_request("PUT", f"/api/v1/{entity}/layout/list", cols)
    if places and places.get("kanban"):
        code, board = espo_request("GET", f"/api/v1/{entity}/layout/kanban")
        columns = board if code == 200 and isinstance(board, list) else []
        present = {col.get("name") for col in columns if isinstance(col, dict)}
        for name in extra:
            if name not in present:
                columns.append({"name": name})
        espo_request("PUT", f"/api/v1/{entity}/layout/kanban", columns)


def prepare_espo() -> None:
    STATE["espo"] = "attendo Espo"
    for _ in range(90):
        if espo_up():
            code, _ = espo_request("GET", "/api/v1/App/user")
            if code == 200:
                break
        time.sleep(2)
    else:
        STATE["espo"] = "non raggiungibile"
        return
    STATE["espo"] = "raggiungibile"
    try:
        espo_request("DELETE", "/api/v1/Admin/fieldManager/Lead/cCExternalKey")
        notes = []
        for entity, name, label, length in FIELDS:
            notes.append(f"{entity}.{ensure_field(entity, name, label, length)}")
        STATE["fields"] = "pronti"
        STATE["detail"] = ", ".join(notes)
    except Exception as error:
        STATE["fields"] = "errore"
        STATE["detail"] = str(error)
        print("[motore] preparazione", error)
        return
    try:
        ensure_service_user()
    except Exception as error:
        print("[motore] utente Espo", error)
    try:
        from demo_meridia import seed_demo
        seed_demo(connect, save_connection, save_pipeline, run_pipeline, ingest, SCAMBIO, espo_request)
    except Exception as error:
        print("[motore] demo", error)


IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def safe_ident(name: str) -> str:
    if not IDENT.match(name or ""):
        raise RuntimeError("nome colonna non valido")
    return name


def split_cursor(value: str) -> tuple[str, str]:
    if "\t" in (value or ""):
        stamp, last_id = value.split("\t", 1)
        return stamp, last_id
    return value or "", ""


def join_cursor(stamp: str, last_id: str) -> str:
    if last_id:
        return f"{stamp}\t{last_id}"
    return stamp


def normalize_phone(value: str) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.startswith("+"):
        digits = re.sub(r"\D", "", raw)
        return f"+{digits}" if digits else None
    if raw.startswith("00"):
        digits = re.sub(r"\D", "", raw[2:])
        return f"+{digits}" if digits else None
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    if digits.startswith("39") and len(digits) >= 11:
        return f"+{digits}"
    if digits.startswith("0"):
        return "+39" + digits[1:]
    if len(digits) >= 9:
        return "+39" + digits
    return f"+{digits}"


def apply_transform(rule: dict, payload: dict) -> str | None:
    transform = rule.get("transform") or "copy"
    if transform == "copy":
        value = payload.get(rule["from"])
        if value is None:
            return None
        return str(value)
    if transform.startswith("const:"):
        return transform.split(":", 1)[1]
    if transform == "split_first":
        text = str(payload.get(rule["from"]) or "").strip()
        return text.split(" ", 1)[0] if text else None
    if transform == "split_last":
        text = str(payload.get(rule["from"]) or "").strip()
        parts = text.split(" ", 1)
        return parts[1] if len(parts) > 1 else None
    if transform == "map":
        value = payload.get(rule["from"])
        if value is None or str(value).strip() == "":
            return None
        table = rule.get("valueMap") or {}
        text = str(value).strip()
        if text in table:
            return str(table[text])
        if "*" in table:
            return str(table["*"])
        return text
    raise RuntimeError(f"transform sconosciuto: {transform}")


def create_foreign(entity: str, key_field: str, key: str) -> str:
    body = {key_field: key}
    if key_field != "name":
        body["name"] = key[:255]
    code, result = espo_request("POST", f"/api/v1/{entity}", body)
    if code == 409:
        found = find_by_key(entity, key_field, key)
        if found:
            return found
    if code not in (200, 201) or not isinstance(result, dict) or "id" not in result:
        raise RuntimeError(f"creazione {entity} HTTP {code}: {result}")
    remember_key(entity, key, result["id"])
    return result["id"]


def resolve_lookup(rule: dict, value: str, dry: bool) -> str | None:
    found = find_by_key(rule["lookupEntity"], rule["lookupBy"], value)
    if found:
        return found
    policy = rule.get("onMiss") or "fail"
    if policy == "skip":
        return None
    if policy == "create":
        if rule.get("neverCreate"):
            return None
        if dry:
            return f"nuovo:{value}"
        return create_foreign(rule["lookupEntity"], rule["lookupBy"], value)
    raise RuntimeError(
        f"nessun {rule['lookupEntity']} con {rule['lookupBy']} uguale a {value}"
    )


def map_payload(mapping: list[dict], payload: dict, key: str | None, key_field: str, dry: bool = False) -> dict:
    mapped: dict = {}
    for rule in mapping:
        if str(rule.get("to") or "").endswith("NessoBadge"):
            continue
        if rule.get("transform") == "lookup":
            value = payload.get(rule["from"])
            if value is None or str(value).strip() == "":
                continue
            found = resolve_lookup(rule, str(value).strip(), dry)
            if not found:
                continue
            mapped[rule["to"]] = found
            if rule.get("parentType"):
                mapped["parentType"] = rule["parentType"]
            continue
        if rule.get("transform") == "lookups":
            raw = str(rule.get("constValue") or payload.get(rule["from"]) or "")
            parts = [part.strip() for part in re.split(r"[;,]", raw) if part.strip()]
            if not parts:
                continue
            ids = []
            for part in parts:
                found = resolve_lookup(rule, part, dry)
                if found:
                    ids.append(found)
            if ids:
                mapped[rule["to"]] = ids
            continue
        if rule.get("transform") == "file":
            raw = str(payload.get(rule["from"]) or "").strip()
            if not raw:
                continue
            if dry:
                mapped[rule["to"]] = raw
            else:
                mapped[rule["to"]] = upload_attachment(resolve_import_file(raw))
            continue
        value = apply_transform(rule, payload)
        if value is None or value == "":
            continue
        if rule.get("zone"):
            value = carico.wall_clock(value)
        if rule.get("kind") in ("date", "fiscale", "enum"):
            value = carico.check_quality(value, rule.get("kind"), rule.get("options"), rule.get("to") or "")
        if rule.get("kind") == "bool":
            mapped[rule["to"]] = str(value).strip().lower() in {"1", "true", "si", "sì", "yes"}
        elif rule.get("kind") == "phone":
            phone = normalize_phone(value)
            if phone:
                mapped[rule["to"]] = phone
        else:
            mapped[rule["to"]] = value
        if rule.get("currencyDefault") and rule.get("currencyField") and not mapped.get(rule["currencyField"]):
            if not str(payload.get(rule["currencyField"]) or "").strip():
                mapped[rule["currencyField"]] = str(rule["currencyDefault"])
    if key and key_field:
        mapped[key_field] = key
    return mapped


def render_key(template: str, payload: dict) -> str:
    key = template
    for name, value in payload.items():
        key = key.replace("{" + name + "}", str(value))
    if "{" in key or not key:
        raise RuntimeError("chiave esterna incompleta")
    return key


def find_local(entity: str, key: str) -> str | None:
    if not entity or not key:
        return None
    with connect() as conn:
        row = conn.execute(
            "SELECT espo_id FROM chiave WHERE entity = ? AND external_key = ?",
            (entity, key),
        ).fetchone()
    return row["espo_id"] if row else None


def remember_key(entity: str, key: str, espo_id: str) -> None:
    if not entity or not key or not espo_id:
        return
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO chiave (entity, external_key, espo_id) VALUES (?, ?, ?)
            ON CONFLICT(entity, external_key) DO UPDATE SET espo_id = excluded.espo_id
            """,
            (entity, key, espo_id),
        )


def find_by_key(entity: str, key_field: str, key: str):
    local = find_local(entity, key)
    if local:
        return local
    if not key_field:
        return None
    if key_field in ("cExternalKey", "externalKey") and not scope_customizable(entity):
        return None
    code, result = espo_request(
        "GET",
        f"/api/v1/{entity}",
        query={
            "select": f"id,{key_field}",
            "maxSize": "1",
            "where[0][type]": "equals",
            "where[0][attribute]": key_field,
            "where[0][value]": key,
        },
    )
    if code != 200 or not isinstance(result, dict):
        raise RuntimeError(f"ricerca {entity} HTTP {code}: {result}")
    rows = result.get("list") or []
    return rows[0]["id"] if rows else None


def upsert(
    entity: str,
    mapped: dict,
    existing_id: str | None,
    key_field: str,
    on_duplicate: str = "fail",
    identity: str | None = None,
) -> tuple[str, str]:
    token = identity or (mapped.get(key_field) if key_field else None)
    if existing_id:
        code, result = espo_request("PUT", f"/api/v1/{entity}/{existing_id}", mapped)
        action = "aggiornato"
    else:
        found = find_local(entity, token) if token else None
        if not found and key_field and token:
            found = find_by_key(entity, key_field, token)
        if found:
            code, result = espo_request("PUT", f"/api/v1/{entity}/{found}", mapped)
            action = "aggiornato"
            existing_id = found
        else:
            code, result = espo_request("POST", f"/api/v1/{entity}", mapped)
            action = "creato"
    if code == 409 and isinstance(result, list) and result and isinstance(result[0], dict):
        existing = result[0]
        same_key = existing.get(key_field) == mapped.get(key_field) and existing.get("id")
        if existing.get("id") and (same_key or on_duplicate == "adopt"):
            code, result = espo_request("PUT", f"/api/v1/{entity}/{existing['id']}", mapped)
            action = "aggiornato"
        else:
            label = existing.get("name") or existing.get("id")
            raise RuntimeError(f"Espo ha già un record simile ({label}) con un'altra chiave")
    if code not in (200, 201) or not isinstance(result, dict) or "id" not in result:
        named = carico.describe_espo_error(result)
        if named:
            raise RuntimeError(f"{named}. scrittura {entity} HTTP {code}")
        if result in (None, "", [], {}):
            raise RuntimeError(f"scrittura {entity} HTTP {code}: risposta vuota")
        raise RuntimeError(f"scrittura {entity} HTTP {code}: {result}")
    if token:
        remember_key(entity, token, result["id"])
    return result["id"], action


def setting_value(key: str, default: str = "") -> str:
    with connect() as conn:
        row = conn.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO setting (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def writes_held(row: sqlite3.Row) -> tuple[bool, str]:
    read_only = bool(row["read_only"]) if "read_only" in row.keys() else False
    enabled = setting_value("writes", "1") != "0"
    return carico.reading(read_only, enabled)


def record_fields(entity: str, espo_id: str | None, names: list[str]) -> dict:
    if not espo_id or not names:
        return {}
    select = ",".join(["id", *names])
    code, result = espo_request("GET", f"/api/v1/{entity}/{espo_id}", query={"select": select})
    if code != 200 or not isinstance(result, dict):
        return {}
    return {name: result.get(name) for name in names}


def find_fiscal(entity: str, field: str, value: str) -> str | None:
    code, result = espo_request(
        "GET",
        f"/api/v1/{entity}",
        query={
            "select": f"id,{field}",
            "maxSize": "1",
            "where[0][type]": "equals",
            "where[0][attribute]": field,
            "where[0][value]": value,
        },
    )
    if code != 200 or not isinstance(result, dict):
        raise RuntimeError(f"ricerca fiscale HTTP {code}")
    rows = result.get("list") or []
    return rows[0]["id"] if rows else None


def remember_watch(pipeline_id: str, external_id: str, watch: list[dict]) -> None:
    if not watch:
        return
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with connect() as conn:
        for item in watch:
            conn.execute(
                """
                INSERT INTO watch_item
                (pipeline_id, external_id, field_name, current_value, incoming_value, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (pipeline_id, external_id, item["field"], item["today"], item["incoming"], now),
            )


def remember_history(pipeline_id: str, run_at: str, espo_id: str, previous: dict, written: dict) -> None:
    with connect() as conn:
        for name, value in written.items():
            if name.endswith("Ids") or name.endswith("Id"):
                continue
            before = "" if previous.get(name) is None else str(previous.get(name))
            if before == str(value):
                continue
            conn.execute(
                """
                INSERT INTO field_history
                (pipeline_id, run_at, espo_id, field_name, previous_value, written_value)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (pipeline_id, run_at, espo_id, name, before, str(value)),
            )


def remember_badge(espo_id: str, modified_at: str, author: str, label: str) -> None:
    if not espo_id:
        return
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO badge_state (espo_id, modified_at, author, label) VALUES (?, ?, ?, ?)
            ON CONFLICT(espo_id) DO UPDATE SET
                modified_at = excluded.modified_at,
                author = excluded.author,
                label = excluded.label
            """,
            (espo_id, modified_at, author, label),
        )


def remember_presence(pipeline_id: str, key: str, espo_id: str) -> None:
    if not key or not espo_id:
        return
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO presenza (pipeline_id, external_key, espo_id) VALUES (?, ?, ?)
            ON CONFLICT(pipeline_id, external_key) DO UPDATE SET espo_id = excluded.espo_id
            """,
            (pipeline_id, key, espo_id),
        )


def governed_mapped(mapping: list[dict], payload: dict, mapped: dict, current: dict, creating: bool) -> tuple[dict, list[dict]]:
    fields = []
    for rule in mapping:
        if rule.get("transform") in ("lookup", "lookups", "file"):
            continue
        source = str(rule.get("from") or "")
        present = source in payload or str(rule.get("transform") or "").startswith("const:")
        fields.append({
            "to": rule["to"],
            "owner": carico.owner_of(rule),
            "present": present,
            "value": mapped.get(rule["to"], ""),
        })
    write, watch = carico.plan_fields(fields, current, creating)
    for rule in mapping:
        if rule.get("transform") in ("lookup", "lookups", "file") and rule["to"] in mapped:
            write[rule["to"]] = mapped[rule["to"]]
    return write, watch


def key_column_list(row) -> list[str]:
    raw = row["key_columns"] if "key_columns" in row.keys() else None
    columns = []
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = []
        if isinstance(parsed, list):
            for item in parsed:
                name = str(item or "").strip()
                if name and name not in columns:
                    columns.append(name)
    if len(columns) >= 2:
        return columns
    primary = str(row["external_id_field"] or "").strip()
    return [primary] if primary else []


def external_of(row, payload: dict) -> str:
    columns = key_column_list(row)
    if len(columns) >= 2:
        return carico.compose_identity(payload, columns)
    return str(payload.get(row["external_id_field"]) or "").strip()


def ingest(pipeline_id: str, payload: dict, hold: bool = False) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM pipeline WHERE id = ?", (pipeline_id,)).fetchone()
        if row is None:
            raise KeyError(pipeline_id)
        if row["direction"] != "in":
            raise RuntimeError("la pipeline non è in ingresso")
        external_id = external_of(row, payload)
        if not external_id:
            raise RuntimeError(f"manca il campo {row['external_id_field']}")
        key = render_key(row["key_template"], payload)
        mapping = json.loads(row["mapping_json"])
        missing_required = carico.empty_required(mapping, payload)
        if missing_required:
            raise RuntimeError(f"campo {missing_required}: obbligatorio")
        key_field = row["key_field"] or "cExternalKey"
        on_duplicate = row["on_duplicate"] if "on_duplicate" in row.keys() and row["on_duplicate"] else "fail"
        mapped = map_payload(mapping, payload, key, key_field, dry=hold)
        existing_id = None
        with connect() as conn:
            previous = conn.execute(
                "SELECT * FROM queue_item WHERE pipeline_id = ? AND external_id = ?",
                (pipeline_id, external_id),
            ).fetchone()
        if previous and previous["espo_id"]:
            existing_id = previous["espo_id"]
        names = [rule["to"] for rule in mapping if rule.get("owner") == "espo"]
        current = record_fields(row["espo_entity"], existing_id, names) if existing_id else {}
        write, watch = governed_mapped(mapping, payload, mapped, current, existing_id is None)
        if key and key_field:
            write[key_field] = key
        if scope_is_custom(row["espo_entity"]) and not write.get("name"):
            write["name"] = external_id
        for rule in mapping:
            if rule.get("kind") == "fiscale" and write.get(rule["to"]):
                found = find_fiscal(row["espo_entity"], rule["to"], write[rule["to"]])
                if carico.fiscal_blocks_create(found, existing_id):
                    raise RuntimeError(f"campo {rule['to']}: partita IVA o codice fiscale già presente")
        digest = hashlib.sha256(json.dumps(write, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        would = carico.classify_row(existing_id is not None, {k: v for k, v in write.items() if k != key_field}, None, watch)
        if previous and previous["hash"] == digest and previous["status"] == "synced" and not watch:
            would = "invariato"
        if would == "invariato" and not hold and not writes_held(row)[0]:
            try:
                note_stage(row, payload)
            except Exception:
                pass
        diffs = carico.dangerous_diffs(watch)
        if hold or writes_held(row)[0]:
            return {
                "status": "lettura",
                "would": would,
                "espoId": existing_id,
                "externalKey": key,
                "entity": row["espo_entity"],
                "diffs": diffs,
            }
        if would == "invariato":
            remember_presence(pipeline_id, key, existing_id or previous["espo_id"])
            return {
                "status": "invariato",
                "espoId": previous["espo_id"],
                "externalKey": key,
                "entity": row["espo_entity"],
                "diffs": diffs,
            }
        if would == "in coda" and existing_id:
            remember_watch(pipeline_id, external_id, watch)
            remember_presence(pipeline_id, key, existing_id)
            return {
                "status": "in coda",
                "espoId": existing_id,
                "externalKey": key,
                "entity": row["espo_entity"],
                "diffs": diffs,
            }
        when = datetime.strptime(now, "%Y-%m-%d %H:%M:%S")
        outgoing = dict(write)
        badge_field = publish_field_name(row["espo_entity"], "nessoBadge")
        try:
            if scope_customizable(row["espo_entity"]):
                ensure_field(row["espo_entity"], "nessoBadge", "Origine Nesso", 180)
                show_on_layout(row["espo_entity"], [badge_field])
        except Exception:
            pass
        outgoing[badge_field] = carico.badge_gestionale(when, frasi.lingua_corrente())
        espo_id, action = upsert(
            row["espo_entity"],
            outgoing,
            existing_id,
            key_field,
            on_duplicate,
            key,
        )
        remember_badge(espo_id, now, "gestionale", outgoing[badge_field])
        remember_history(pipeline_id, now, espo_id, current, write)
        remember_watch(pipeline_id, external_id, watch)
        remember_presence(pipeline_id, key, espo_id)
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO queue_item
                (pipeline_id, external_id, payload_json, mapped_json, hash, status, espo_id, detail, updated_at)
                VALUES (?, ?, ?, ?, ?, 'synced', ?, ?, ?)
                ON CONFLICT(pipeline_id, external_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    mapped_json = excluded.mapped_json,
                    hash = excluded.hash,
                    status = 'synced',
                    espo_id = excluded.espo_id,
                    detail = excluded.detail,
                    updated_at = excluded.updated_at
                """,
                (pipeline_id, external_id, json.dumps(payload, ensure_ascii=False), json.dumps(write, ensure_ascii=False), digest, espo_id, action, now),
            )
        try:
            note_stage(row, payload)
        except Exception:
            pass
        try:
            note_origin(row["espo_entity"], row["name"], espo_id, key, now)
        except Exception:
            pass
        try:
            open_activity(row, espo_id, action == "creato")
        except Exception:
            pass
        return {"status": action, "espoId": espo_id, "externalKey": key, "entity": row["espo_entity"], "diffs": diffs}


def note_origin(entity: str, name: str, espo_id: str, key: str, when: str) -> None:
    espo_request(
        "POST",
        "/api/v1/Note",
        {
            "type": "Post",
            "post": carico.note_line(name, key, when),
            "parentType": entity,
            "parentId": espo_id,
        },
    )


def open_activity(row: sqlite3.Row, espo_id: str, creating: bool) -> None:
    raw = row["activity_json"] if "activity_json" in row.keys() else None
    if not raw:
        return
    spec = json.loads(raw)
    if not isinstance(spec, dict) or not carico.activity_opens(creating, bool(spec.get("repeat"))):
        return
    kind = str(spec.get("type") or "Task")
    if kind not in ("Task", "Call", "Meeting"):
        return
    body = {
        "name": str(spec.get("name") or row["name"]),
        "parentType": row["espo_entity"],
        "parentId": espo_id,
    }
    if spec.get("date"):
        body["dateStart"] = str(spec["date"])
    if spec.get("assignee"):
        body["assignedUserId"] = str(spec["assignee"])
    espo_request("POST", f"/api/v1/{kind}", body)


def espo_page(entity: str, select: str, where: list[tuple[str, str, str]], order_by: str) -> list:
    query = {"select": select, "maxSize": "50", "orderBy": order_by, "order": "asc"}
    for index, (kind, attribute, value) in enumerate(where):
        query[f"where[{index}][type]"] = kind
        query[f"where[{index}][attribute]"] = attribute
        query[f"where[{index}][value]"] = value
    code, result = espo_request("GET", f"/api/v1/{entity}", query=query)
    if code != 200 or not isinstance(result, dict):
        raise RuntimeError(f"lettura Espo HTTP {code}: {result}")
    return result.get("list") or []


def secret_key() -> str:
    return os.environ.get("NESSO_SECRET_KEY", "")


def stored_config(raw: str | None) -> dict:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return carico.open_config(parsed, secret_key())


def pipeline_lock(pipeline_id: str) -> threading.RLock:
    with RUN_LOCKS_GUARD:
        lock = RUN_LOCKS.get(pipeline_id)
        if lock is None:
            lock = threading.RLock()
            RUN_LOCKS[pipeline_id] = lock
        return lock


def save_cursor(pipeline_id: str, stamp: str, last_id: str) -> None:
    if not stamp and not last_id:
        return
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO cursor_state (pipeline_id, cursor_value) VALUES (?, ?)
            ON CONFLICT(pipeline_id) DO UPDATE SET cursor_value = excluded.cursor_value
            """,
            (pipeline_id, join_cursor(stamp, last_id)),
        )


def load_cursor(pipeline_id: str) -> str:
    with connect() as conn:
        cursor = conn.execute(
            "SELECT cursor_value FROM cursor_state WHERE pipeline_id = ?",
            (pipeline_id,),
        ).fetchone()
    return cursor["cursor_value"] if cursor else "1970-01-01 00:00:00"


def collect_changes(entity: str, select: str, cursor_value: str, limit: int) -> list:
    stamp, last_id = split_cursor(cursor_value or "1970-01-01 00:00:00")
    origin_stamp, origin_id = stamp, last_id
    records = []
    seen = set()

    def add(items: list) -> bool:
        for item in items:
            espo_id = item.get("id")
            if not espo_id or espo_id in seen:
                continue
            if carico.skip_without_date(item.get("modifiedAt") or "", espo_id, origin_stamp, origin_id):
                continue
            seen.add(espo_id)
            records.append(item)
            if len(records) >= limit:
                return True
        return False

    if stamp and stamp > "1970-01-01 00:00:00":
        page_id = last_id
        while len(records) < limit:
            rows = espo_page(entity, select, [
                ("equals", "modifiedAt", stamp),
                ("greaterThan", "id", page_id or ""),
            ], "id")
            if not rows:
                break
            if add(rows):
                return records
            page_id = rows[-1].get("id") or page_id
            if len(rows) < 50:
                break
    guard = 0
    while len(records) < limit and guard < 40:
        guard += 1
        page = espo_page(entity, select, [("after", "modifiedAt", stamp)], "modifiedAt")
        if not page:
            break
        boundary = page[-1].get("modifiedAt") or ""
        earlier = [item for item in page if (item.get("modifiedAt") or "") < boundary]
        if earlier and add(earlier):
            return records
        if not boundary:
            add(page)
            break
        page_id = ""
        while len(records) < limit:
            rows = espo_page(entity, select, [
                ("equals", "modifiedAt", boundary),
                ("greaterThan", "id", page_id or ""),
            ], "id")
            if not rows:
                break
            if add(rows):
                return records
            page_id = rows[-1].get("id") or page_id
            if len(rows) < 50:
                break
        stamp = boundary
        if len(page) < 50:
            break
    records.sort(key=lambda item: (item.get("modifiedAt") or "", item.get("id") or ""))
    return records


def portal_rule(row: sqlite3.Row) -> dict | None:
    raw = row["portal_json"] if "portal_json" in row.keys() else ""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict) and parsed.get("enabled"):
        return parsed
    return None


def outbound_rows(pipeline_id: str, limit: int = 1000) -> list[dict]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM pipeline WHERE id = ?", (pipeline_id,)).fetchone()
    if row is None:
        raise KeyError(pipeline_id)
    if row["direction"] != "out":
        raise RuntimeError("la pipeline non è in uscita")
    mapping = json.loads(row["mapping_json"])
    portal = portal_rule(row)
    fields = {rule["from"] for rule in mapping} | {"id", "modifiedAt"}
    if portal:
        fields.add("teamsNames")
    select = ",".join(sorted(fields))
    items = collect_changes(row["espo_entity"], select, load_cursor(pipeline_id), limit)
    items.sort(key=lambda item: (item.get("modifiedAt") or "", item.get("id") or ""))
    records = []
    for item in items:
        outgoing = {}
        missing_key = ""
        for rule in mapping:
            value = item.get(rule["from"])
            if rule.get("as") == "chiave":
                external = external_key_for(str(rule.get("lookupEntity") or ""), str(value or ""))
                if not external:
                    missing_key = str(rule.get("to") or rule.get("from") or "collegamento")
                    break
                outgoing[rule["to"]] = external
            elif value is not None:
                outgoing[rule["to"]] = value
        if portal and not missing_key:
            teams = item.get("teamsNames") or []
            if isinstance(teams, str):
                teams = [teams]
            visible = carico.portal_visible(
                {**portal, "entity": row["espo_entity"]},
                {"entity": row["espo_entity"], "teams": teams},
            )
            if not visible:
                continue
        records.append({
            "espoId": item.get("id"),
            "modifiedAt": item.get("modifiedAt") or "",
            "payload": outgoing,
            "missingKey": missing_key,
        })
    return records


def external_key_for(entity: str, espo_id: str) -> str:
    if not entity or not espo_id:
        return ""
    with connect() as conn:
        row = conn.execute(
            "SELECT external_key FROM chiave WHERE entity = ? AND espo_id = ?",
            (entity, espo_id),
        ).fetchone()
    return row["external_key"] if row else ""


def remember_sink(pipeline_id: str, espo_id: str, payload: dict) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO sink_item (pipeline_id, espo_id, payload_json, created_at) VALUES (?, ?, ?, ?)",
            (pipeline_id, espo_id, json.dumps(payload, ensure_ascii=False), time.strftime("%Y-%m-%d %H:%M:%S")),
        )


def ask_model(url: str, payload: dict) -> list:
    clean = str(url or "").strip()
    if not clean.startswith("http://") and not clean.startswith("https://"):
        return []
    raw = json.dumps(payload, ensure_ascii=False).encode()
    request = urllib.request.Request(clean, data=raw, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            body = json.loads(response.read().decode())
    except Exception:
        return []
    if isinstance(body, dict):
        body = body.get("rows") or body.get("suggestions") or []
    if not isinstance(body, list):
        return []
    return [item for item in body if isinstance(item, dict)]


def complete_with_model(body: dict) -> dict:
    columns = list(body.get("columns") or [])
    fields = list(body.get("fields") or [])
    samples = list(body.get("samples") or [])
    rows = carico.propose(columns, frasi.lingua_corrente(), fields, samples)
    url = setting_value("model_url")
    if not str(url or "").strip():
        return {"rows": rows, "model": False}
    suggestions = ask_model(url, carico.model_request(columns, samples, fields, frasi.lingua_corrente()))
    return {"rows": carico.complete_empty(rows, suggestions, fields), "model": True}


def remember_outbound_cursor(pipeline_id: str, item: dict) -> bool:
    stamp = item.get("modifiedAt") or ""
    espo_id = item.get("espoId") or ""
    if not stamp and not espo_id:
        return False
    save_cursor(pipeline_id, stamp, espo_id)
    return not bool(stamp)


def pull(pipeline_id: str) -> dict:
    records = outbound_rows(pipeline_id)
    delivered = []
    last = None
    stopped = ""
    for item in records:
        if item.get("missingKey"):
            stopped = str(item["missingKey"])
            break
        remember_sink(pipeline_id, item["espoId"], item["payload"])
        delivered.append(item)
        if item.get("espoId") or item.get("modifiedAt"):
            last = item
    missing_date = remember_outbound_cursor(pipeline_id, last) if last else False
    cursor = join_cursor(last["modifiedAt"], last["espoId"]) if last else load_cursor(pipeline_id)
    result = {
        "exported": len(delivered),
        "cursor": cursor,
        "missingDate": missing_date,
        "records": [item["payload"] for item in delivered],
    }
    if stopped:
        result["stopped"] = stopped
    return result


def source_rows_of(pipeline: sqlite3.Row, link: sqlite3.Row | None) -> list[dict] | None:
    if link is None:
        return None
    if link["kind"] == "csv":
        folder = SCAMBIO / link["id"]
        if not folder.is_dir() or not any(folder.glob("*.csv")):
            return None
        rows: list[dict] = []
        for path in sorted(folder.glob("*.csv")):
            _headers, file_rows = read_csv_file(path)
            rows.extend(file_rows)
        return rows
    if link["kind"] == "database":
        config = stored_config(link["config_json"])
        return read_database(config)
    return None


def capture_balance(pipeline: sqlite3.Row, rows: list[dict]) -> dict:
    mapping = json.loads(pipeline["mapping_json"])
    amount = next((rule for rule in mapping if rule.get("kind") == "importo"), None)
    source_keys: set[str] = set()
    source_amount = 0.0 if amount else None
    for payload in rows:
        try:
            source_keys.add(render_key(pipeline["key_template"], payload))
        except Exception:
            continue
        if amount is not None and source_amount is not None:
            source_amount += carico.parse_amount(payload.get(amount.get("from")))
    with connect() as conn:
        known = conn.execute(
            "SELECT external_key, espo_id FROM chiave WHERE entity = ?",
            (pipeline["espo_entity"],),
        ).fetchall()
        queued = conn.execute(
            "SELECT external_id, mapped_json FROM queue_item WHERE pipeline_id = ?",
            (pipeline["id"],),
        ).fetchall()
    prefix = pipeline["key_template"].split("{", 1)[0]
    espo_keys = {row["external_key"] for row in known if str(row["external_key"]).startswith(prefix)}
    espo_amount = None
    if amount is not None:
        espo_amount = 0.0
        by_external = {row["external_id"]: row["mapped_json"] for row in queued}
        for key in espo_keys:
            external = key[len(prefix):] if key.startswith(prefix) else ""
            raw = by_external.get(external)
            if not raw:
                continue
            mapped = json.loads(raw)
            espo_amount += carico.parse_amount(mapped.get(amount.get("to")))
    result = carico.quadratura(source_keys, espo_keys, source_amount, espo_amount)
    with connect() as conn:
        conn.execute(
            "UPDATE pipeline SET balance_json = ? WHERE id = ?",
            (json.dumps(result, ensure_ascii=False), pipeline["id"]),
        )
    return result


def measure_balance(pipeline_id: str) -> dict | None:
    with connect() as conn:
        pipeline = conn.execute("SELECT * FROM pipeline WHERE id = ?", (pipeline_id,)).fetchone()
        link = None
        if pipeline and pipeline["connection_id"]:
            link = conn.execute("SELECT * FROM connection WHERE id = ?", (pipeline["connection_id"],)).fetchone()
    if pipeline is None or pipeline["direction"] != "in":
        return None
    rows = source_rows_of(pipeline, link)
    if rows is None:
        return None
    return capture_balance(pipeline, rows)


def folder_has_csv(connection_id: str) -> bool:
    folder = SCAMBIO / connection_id
    return folder.is_dir() and (any(folder.glob("*.csv")) or any(folder.glob("*.xlsx")))


def notice_absent(now: datetime | None = None) -> list[str]:
    moment = now or datetime.now()
    day = moment.strftime("%Y-%m-%d")
    noted: list[str] = []
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT pipeline.id, pipeline.name, pipeline.expect_at, pipeline.last_success, pipeline.connection_id
            FROM pipeline
            JOIN connection ON connection.id = pipeline.connection_id
            WHERE connection.kind = 'csv' AND pipeline.expect_at IS NOT NULL AND pipeline.expect_at != ''
            """
        ).fetchall()
    for row in rows:
        state = carico.file_wait(moment, row["expect_at"], row["last_success"], folder_has_csv(row["connection_id"]))
        with connect() as conn:
            if state in ("mancante", "in_attesa"):
                conn.execute("UPDATE pipeline SET file_alert = 1 WHERE id = ?", (row["id"],))
            else:
                conn.execute("UPDATE pipeline SET file_alert = 0 WHERE id = ?", (row["id"],))
            if state == "mancante":
                detail = f"file atteso entro le {row['expect_at']}, non arrivato"
                already = conn.execute(
                    """
                    SELECT 1 FROM run_log
                    WHERE pipeline_id = ? AND status = 'mancante' AND created_at LIKE ?
                    """,
                    (row["id"], day + "%"),
                ).fetchone()
                if already is None:
                    conn.execute(
                        "INSERT INTO run_log (pipeline_id, status, detail, created_at) VALUES (?, 'mancante', ?, ?)",
                        (row["id"], detail, moment.strftime("%Y-%m-%d %H:%M:%S")),
                    )
                    noted.append(row["id"])
    return noted


def deliver_notice(notice: dict) -> None:
    """Punto unico per la posta del motore. Senza SMTP non invia, e non usa la posta di Espo."""
    if not carico.mail_ready(setting_value("smtp_host")):
        return None
    name = str(notice.get("name") or notice.get("pipelineId") or "")
    kind = str(notice.get("kind") or "avviso")
    subject = f"Nesso: {name}"
    if kind == "silenzio":
        body = f"{name} tace da più di {notice.get('minutes') or 0} minuti."
    else:
        body = f"{name}: il giro non è riuscito."
    queue_mail(kind, subject, body)
    return None


def queue_mail(kind: str, subject: str, body: str) -> int:
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO mail_queue (kind, subject, body, status, attempts, next_at, created_at)
            VALUES (?, ?, ?, 'attesa', 0, ?, ?)
            """,
            (kind, subject, body, now, now),
        )
        queued = cursor.lastrowid
    retry_mail()
    return int(queued or 0)


def send_smtp(subject: str, body: str) -> None:
    host = setting_value("smtp_host")
    if not carico.mail_ready(host):
        raise RuntimeError("manca l'indirizzo SMTP")
    import smtplib
    from email.message import EmailMessage

    message = EmailMessage()
    message["From"] = setting_value("smtp_from") or "nesso@localhost"
    message["To"] = setting_value("smtp_to") or message["From"]
    message["Subject"] = subject
    message.set_content(body)
    port = int(setting_value("smtp_port") or "587")
    with smtplib.SMTP(host, port, timeout=15) as client:
        if setting_value("smtp_tls") == "1":
            client.starttls()
        user = setting_value("smtp_user")
        secret = setting_value("smtp_secret")
        if user:
            client.login(user, secret)
        client.send_message(message)


def retry_mail(sender=None) -> int:
    if not carico.mail_ready(setting_value("smtp_host")):
        return 0
    caller = sender or send_smtp
    sent = 0
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM mail_queue WHERE status = 'attesa' AND (next_at IS NULL OR next_at <= ?) ORDER BY id",
            (now,),
        ).fetchall()
    for row in rows:
        try:
            caller(row["subject"], row["body"])
        except Exception as error:
            attempts = int(row["attempts"] or 0) + 1
            wait = min(60 * (2 ** min(attempts, 6)), 24 * 60)
            later = (datetime.now() + timedelta(minutes=wait)).strftime("%Y-%m-%d %H:%M:%S")
            status = "attesa" if attempts < 8 else "scarto"
            with connect() as conn:
                conn.execute(
                    "UPDATE mail_queue SET attempts = ?, status = ?, next_at = ?, last_error = ? WHERE id = ?",
                    (attempts, status, later, str(error)[:180], row["id"]),
                )
            continue
        with connect() as conn:
            conn.execute("UPDATE mail_queue SET status = 'inviato', attempts = attempts + 1 WHERE id = ?", (row["id"],))
        sent += 1
    return sent


def imap_fetch() -> list[dict]:
    host = setting_value("imap_host")
    if not carico.mail_ready(host):
        return []
    import email
    import imaplib

    port = int(setting_value("imap_port") or "993")
    client = imaplib.IMAP4_SSL(host, port, timeout=8)
    try:
        client.login(setting_value("imap_user"), setting_value("imap_secret"))
        client.select("INBOX")
        _kind, data = client.search(None, "UNSEEN")
        found = []
        for number in (data[0] or b"").split()[:20]:
            _kind, payload = client.fetch(number, "(RFC822)")
            raw = payload[0][1] if payload and isinstance(payload[0], tuple) else b""
            parsed = email.message_from_bytes(raw)
            text = ""
            if parsed.is_multipart():
                for part in parsed.walk():
                    if part.get_content_type() == "text/plain":
                        text = (part.get_payload(decode=True) or b"").decode(errors="replace")
                        break
            else:
                text = (parsed.get_payload(decode=True) or b"").decode(errors="replace")
            found.append({
                "id": (parsed.get("Message-ID") or number.decode(errors="replace"))[:180],
                "da": parsed.get("From") or "",
                "oggetto": parsed.get("Subject") or "",
                "testo": text[:4000],
            })
            client.store(number, "+FLAGS", "\\Seen")
        return found
    finally:
        try:
            client.logout()
        except Exception:
            pass


def take_mail(messages: list[dict], pipeline_id: str) -> int:
    taken = 0
    for message in messages:
        if not isinstance(message, dict):
            continue
        result = ingest_row(pipeline_id, message)
        if result.get("status") != "scartato":
            taken += 1
    return taken


def poll_imap() -> int:
    pipeline_id = setting_value("imap_pipeline")
    if not carico.mail_ready(setting_value("imap_host")) or not pipeline_id:
        return 0
    try:
        messages = imap_fetch()
    except Exception as error:
        print("[motore] imap", type(error).__name__)
        return 0
    return take_mail(messages, pipeline_id)


def open_notice(pipeline_id: str, kind: str, minutes: int = 0) -> bool:
    with connect() as conn:
        already = conn.execute(
            "SELECT 1 FROM notice WHERE pipeline_id = ? AND kind = ? AND open = 1",
            (pipeline_id, kind),
        ).fetchone()
        if already is not None:
            return False
        conn.execute(
            "INSERT INTO notice (pipeline_id, kind, detail, created_at, open) VALUES (?, ?, ?, ?, 1)",
            (pipeline_id, kind, str(minutes or ""), time.strftime("%Y-%m-%d %H:%M:%S")),
        )
        name_row = conn.execute("SELECT name FROM pipeline WHERE id = ?", (pipeline_id,)).fetchone()
        name = name_row["name"] if name_row else pipeline_id
    deliver_notice({
        "pipelineId": pipeline_id,
        "kind": kind,
        "name": name,
        "minutes": minutes,
    })
    return True


def close_notices(pipeline_id: str, kind: str | None = None) -> None:
    with connect() as conn:
        if kind:
            conn.execute(
                "UPDATE notice SET open = 0 WHERE pipeline_id = ? AND kind = ? AND open = 1",
                (pipeline_id, kind),
            )
        else:
            conn.execute("UPDATE notice SET open = 0 WHERE pipeline_id = ? AND open = 1", (pipeline_id,))


def notice_quiet(now: datetime | None = None) -> list[str]:
    moment = now or datetime.now()
    noted: list[str] = []
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, last_success, alert_minutes FROM pipeline
            WHERE COALESCE(enabled, 1) = 1 AND alert_minutes IS NOT NULL AND alert_minutes > 0
            """
        ).fetchall()
    for row in rows:
        if not carico.silence_elapsed(row["last_success"], int(row["alert_minutes"]), moment):
            continue
        if open_notice(row["id"], "silenzio", int(row["alert_minutes"])):
            noted.append(row["id"])
    return noted


def scan_person_badges() -> None:
    with connect() as conn:
        entities = [
            row["espo_entity"]
            for row in conn.execute(
                "SELECT DISTINCT espo_entity FROM pipeline WHERE direction = 'in' AND espo_entity != ''"
            )
        ]
    for entity in entities:
        stamp = setting_value(f"badge_scan_{entity}", "1970-01-01 00:00:00")
        try:
            rows = espo_page(
                entity,
                "id,modifiedAt,modifiedByName",
                [("after", "modifiedAt", stamp)],
                "modifiedAt",
            )
        except Exception:
            continue
        apply_person_badges(entity, rows)
        if rows:
            last = max(str(row.get("modifiedAt") or "") for row in rows)
            if last:
                set_setting(f"badge_scan_{entity}", last[:19])


def engine_names_default() -> set[str]:
    names = {"admin", "Admin", "Nesso", "nesso", "Nesso Servizio"}
    for key in ("espo_service_user", "espo_service_label"):
        value = setting_value(key, "")
        if value:
            names.add(value)
    return names


def apply_person_badges(entity: str, records: list[dict], engine_names: set[str] | None = None) -> int:
    names = engine_names if engine_names is not None else engine_names_default()
    field = publish_field_name(entity, "nessoBadge")
    changed = 0
    for record in records:
        espo_id = str(record.get("id") or "")
        if not espo_id:
            continue
        with connect() as conn:
            stored = conn.execute("SELECT modified_at FROM badge_state WHERE espo_id = ?", (espo_id,)).fetchone()
        decision = carico.badge_decision(
            stored["modified_at"] if stored else None,
            record.get("modifiedAt"),
            record.get("modifiedByName"),
            names,
        )
        if decision != "persona":
            continue
        stamp = str(record.get("modifiedAt") or "")[:19]
        when = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
        text = carico.badge_persona(str(record.get("modifiedByName") or "").strip(), when, frasi.lingua_corrente())
        code, _result = espo_request("PUT", f"/api/v1/{entity}/{espo_id}", {field: text})
        if code not in (200, 201):
            continue
        remember_badge(espo_id, stamp, "persona", text)
        changed += 1
    return changed


def registry_morning(pipelines: list[dict], now: datetime | None = None) -> dict:
    moment = now or datetime.now()
    rows = [item for item in pipelines if item.get("direction") == "in" and item.get("espo_entity") == "Account"]
    if not rows:
        return {
            "percent": None,
            "tone": "niente",
            "today": False,
            "text": "Nessuna integrazione di anagrafiche.",
            "textKey": "Nessuna integrazione di anagrafiche.",
            "textParams": {},
        }
    source = aligned = 0
    last_success = None
    failed_today = False
    today = moment.strftime("%Y-%m-%d")
    for item in rows:
        part_source, part_aligned = carico.alignment_counts(item.get("counts"))
        source += part_source
        aligned += part_aligned
        stamp = carico.success_stamp(item.get("last_success"), item.get("last_run"), item.get("last_status"), item.get("counts"))
        if stamp and (last_success is None or stamp > last_success):
            last_success = stamp
        ran_today = str(item.get("last_run") or "")[:10] == today
        if ran_today and item.get("last_status") not in ("ok", "lettura", "conferma", "attesa", "sospeso", None, ""):
            failed_today = True
    status = "errore" if failed_today else "ok"
    return carico.morning_alignment(source, aligned, last_success, status, moment)


def snapshot() -> dict:
    notice_absent()
    notice_quiet()
    with connect() as conn:
        pipelines = [dict(row) for row in conn.execute("SELECT * FROM pipeline ORDER BY direction, id")]
        for item in pipelines:
            item["mapping"] = json.loads(item.pop("mapping_json"))
            raw_counts = item.get("last_counts")
            item["counts"] = json.loads(raw_counts) if raw_counts else None
            raw_balance = item.get("balance_json")
            item["balance"] = json.loads(raw_balance) if raw_balance else None
            item["file_alert"] = int(item.get("file_alert") or 0)
            raw_keys = item.get("key_columns")
            try:
                parsed_keys = json.loads(raw_keys) if raw_keys else []
            except json.JSONDecodeError:
                parsed_keys = []
            item["keyColumns"] = parsed_keys if isinstance(parsed_keys, list) else []
        watch = [dict(row) for row in conn.execute("SELECT * FROM watch_item ORDER BY id DESC LIMIT 30")]
        queue = [dict(row) for row in conn.execute("SELECT * FROM queue_item ORDER BY updated_at DESC LIMIT 30")]
        sink = [dict(row) for row in conn.execute("SELECT * FROM sink_item ORDER BY id DESC LIMIT 20")]
        connections = [public_connection(row) for row in conn.execute("SELECT * FROM connection ORDER BY name")]
        deliveries = [dict(row) for row in conn.execute("SELECT * FROM delivery ORDER BY id DESC LIMIT 20")]
        rejects = [dict(row) for row in conn.execute("SELECT * FROM scarto ORDER BY id DESC LIMIT 30")]
        runs = [dict(row) for row in conn.execute("SELECT * FROM run_log ORDER BY id DESC LIMIT 20")]
        silence = [dict(row) for row in conn.execute("SELECT * FROM silence_window ORDER BY start_on, id")]
        plan = [dict(row) for row in conn.execute("SELECT * FROM plan_step ORDER BY position")]
        proposals = [dict(row) for row in conn.execute("SELECT * FROM stage_proposal ORDER BY id DESC LIMIT 30")]
        notices = [dict(row) for row in conn.execute(
            """
            SELECT notice.kind, notice.detail, notice.pipeline_id, pipeline.name
            FROM notice
            LEFT JOIN pipeline ON pipeline.id = notice.pipeline_id
            WHERE notice.open = 1
            ORDER BY notice.id
            """
        )]
        last_errors: dict[str, sqlite3.Row] = {}
        for row in conn.execute(
            "SELECT pipeline_id, created_at, detail FROM run_log WHERE status = 'errore' ORDER BY id DESC"
        ):
            if row["pipeline_id"] not in last_errors:
                last_errors[row["pipeline_id"]] = row
    moment = datetime.now()
    for item in pipelines:
        error = last_errors.get(item["id"])
        item["pace"] = carico.run_pace(
            moment,
            item.get("schedule_at"),
            int(item.get("schedule_minutes") or 0),
            item.get("last_run"),
            item.get("last_success"),
            error["created_at"] if error else None,
            error["detail"] if error else None,
        )
    kinds = {item["id"]: item["kind"] for item in connections}
    for item in pipelines:
        if item.get("direction") == "in" and kinds.get(item.get("connection_id")) == "csv":
            try:
                fresh = measure_balance(item["id"])
            except Exception:
                fresh = None
            if fresh:
                item["balance"] = fresh
    alerts = []
    for item in pipelines:
        if item.get("file_alert"):
            alerts.append({
                "text": f"{item['name']}: il file atteso non è stato elaborato.",
                "textKey": "{nome}: il file atteso non è stato elaborato.",
                "textParams": {"nome": item["name"]},
            })
        if item.get("silence_held"):
            alerts.append({
                "text": f"{item['name']}: un file è in attesa della finestra di silenzio.",
                "textKey": "{nome}: un file è in attesa della finestra di silenzio.",
                "textParams": {"nome": item["name"]},
            })
        balance = item.get("balance")
        if isinstance(balance, dict) and balance.get("ok") is False:
            alerts.append({
                "text": f"{item['name']}: {balance.get('text')}",
                "textKey": "{nome}: {testo}",
                "textParams": {"nome": item["name"], "testo": balance.get("text")},
            })
    for item in notices:
        name = item.get("name") or item.get("pipeline_id")
        if item.get("kind") == "silenzio":
            minutes = item.get("detail") or ""
            alerts.append({
                "text": f"{name}: tace da più di {minutes} minuti.",
                "textKey": "{nome}: tace da più di {minuti} minuti.",
                "textParams": {"nome": name, "minuti": minutes},
            })
        else:
            alerts.append({
                "text": f"{name}: il giro non è riuscito.",
                "textKey": "{nome}: il giro non è riuscito.",
                "textParams": {"nome": name},
            })
    return {
        "state": STATE,
        "espoPublicUrl": ESPO_PUBLIC,
        "publicBase": PUBLIC_BASE,
        "pipelines": pipelines,
        "connections": connections,
        "queue": queue,
        "sink": sink,
        "deliveries": deliveries,
        "rejects": rejects,
        "runs": runs,
        "watch": watch,
        "writesEnabled": setting_value("writes", "1") != "0",
        "morning": registry_morning(pipelines),
        "alerts": alerts,
        "silence": silence,
        "plan": plan,
        "proposals": proposals,
    }


WRITABLE = {
    "varchar", "text", "enum", "email", "phone", "int", "float", "bool",
    "date", "datetime", "datetimeOptional", "url", "wysiwyg", "multiEnum", "currency",
    "password",
}
# Schede usate da un CRM aziendale che Espo non marca come object+tab.
CATALOG_ALSO = {
    "Team", "Role", "DocumentFolder", "KnowledgeBaseCategory",
    "EmailTemplate", "Template", "TargetListCategory", "EmailTemplateCategory",
    "Report", "BpmnFlowchart",
}
CATALOG: dict = {"at": 0.0, "data": None}


def slugify(text: str) -> str:
    chars = []
    for char in text.lower().strip():
        if char.isalnum():
            chars.append(char)
        elif char in " -_":
            chars.append("-")
    slug = "".join(chars).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:40] or "integrazione"


def load_catalog() -> list[dict]:
    if CATALOG["data"] is not None and time.time() - CATALOG["at"] < 120:
        return CATALOG["data"]
    code, scopes = espo_request("GET", "/api/v1/Metadata", query={"key": "scopes"})
    if code != 200 or not isinstance(scopes, dict):
        raise RuntimeError(f"schede Espo non disponibili: HTTP {code}")
    code, i18n = espo_request("GET", "/api/v1/I18n/it_IT")
    labels = i18n if code == 200 and isinstance(i18n, dict) else {}
    scope_names = (labels.get("Global") or {}).get("scopeNames") or {}
    global_fields = (labels.get("Global") or {}).get("fields") or {}
    entities = []
    for name, scope in scopes.items():
        if not isinstance(scope, dict):
            continue
        if not scope.get("entity") or scope.get("disabled"):
            continue
        if not (scope.get("object") and scope.get("tab")) and name not in CATALOG_ALSO:
            continue
        field_code, fields = espo_request(
            "GET", "/api/v1/Metadata", query={"key": f"entityDefs.{name}.fields"}
        )
        if field_code != 200 or not isinstance(fields, dict):
            continue
        link_code, links = espo_request(
            "GET", "/api/v1/Metadata", query={"key": f"entityDefs.{name}.links"}
        )
        if link_code != 200 or not isinstance(links, dict):
            links = {}
        field_labels = (labels.get(name) or {}).get("fields") or {}
        link_labels = (labels.get(name) or {}).get("links") or {}
        custom = scope.get("module") == "Custom" or bool(scope.get("isCustom"))
        usable = []
        for field_name, field_def in fields.items():
            if not isinstance(field_def, dict):
                continue
            link = links.get(field_name) if isinstance(links.get(field_name), dict) else {}
            if field_def.get("readOnly") or field_def.get("disabled"):
                continue
            label = link_labels.get(field_name) or field_labels.get(field_name) or field_name
            if field_def.get("type") == "link" and link.get("type") == "belongsTo" and link.get("entity"):
                usable.append({
                    "name": field_name,
                    "idName": field_name + "Id",
                    "label": f"{label} (collegamento)",
                    "type": "link",
                    "foreignEntity": link.get("entity"),
                })
                continue
            if field_def.get("type") == "linkMultiple" and link.get("type") == "hasMany" and link.get("entity"):
                usable.append({
                    "name": field_name,
                    "idName": field_name + "Ids",
                    "label": f"{label} (più collegamenti)",
                    "type": "linkMultiple",
                    "foreignEntity": link.get("entity"),
                })
                continue
            if field_def.get("type") == "linkParent":
                usable.append({
                    "name": field_name,
                    "idName": field_name + "Id",
                    "label": f"{label} (attività sulla scheda)",
                    "type": "linkParent",
                })
                continue
            if field_def.get("type") == "file":
                usable.append({
                    "name": field_name,
                    "idName": field_name + "Id",
                    "label": f"{label} (file)",
                    "type": "file",
                })
                continue
            if field_def.get("type") not in WRITABLE or field_def.get("readOnly") or field_def.get("disabled"):
                continue
            if field_name in ("cExternalKey", "externalKey"):
                usable.append({"name": field_name, "label": "Chiave esterna", "type": "varchar"})
                continue
            field = {
                "name": field_name,
                "label": field_labels.get(field_name) or global_fields.get(field_name) or field_name,
                "type": field_def.get("type"),
            }
            if field_def.get("type") in ("enum", "multiEnum") and isinstance(field_def.get("options"), list):
                field["options"] = field_def.get("options")
            usable.append(field)
        seen = {item["name"] for item in usable}
        for link_name, link in links.items():
            if link_name in seen or not isinstance(link, dict):
                continue
            if link.get("type") == "hasMany" and link.get("entity"):
                label = link_labels.get(link_name) or link_name
                usable.append({
                    "name": link_name,
                    "idName": link_name + "Ids",
                    "label": f"{label} (più collegamenti)",
                    "type": "linkMultiple",
                    "foreignEntity": link.get("entity"),
                })
        usable.sort(key=lambda item: item["label"].lower())
        entities.append({
            "name": name,
            "label": scope_names.get(name) or name,
            "keyField": "externalKey" if custom else "cExternalKey",
            "fields": usable,
        })
    entities.sort(key=lambda item: item["label"].lower())
    CATALOG["data"] = entities
    CATALOG["at"] = time.time()
    return entities


def prepare_lookup(catalog: list[dict], foreign: str, lookup_by: str) -> tuple[dict, str]:
    foreign_meta = next((item for item in catalog if item["name"] == foreign), None)
    if foreign_meta is None:
        raise RuntimeError("scegli la scheda a cui collegare il record")
    lookup_by = lookup_by or foreign_meta["keyField"]
    known = {field["name"] for field in foreign_meta["fields"]}
    if lookup_by not in known:
        if lookup_by == foreign_meta["keyField"] and scope_customizable(foreign):
            ensure_field(foreign, "externalKey", "Chiave esterna", 180)
        elif lookup_by != foreign_meta["keyField"]:
            raise RuntimeError("campo di riconoscimento non trovato sulla scheda collegata")
    return foreign_meta, lookup_by


def miss_policy(rule: dict) -> str:
    value = rule.get("onMiss") or "fail"
    if value not in ("fail", "skip", "create"):
        raise RuntimeError("scegli se scartare la riga, lasciare il legame vuoto o creare il record")
    return value


def kept_transform(rule: dict) -> str:
    raw = str(rule.get("transform") or "copy")
    if raw.startswith("const:"):
        if len(raw) > 400:
            raise RuntimeError("valore fisso troppo lungo")
        return raw
    if raw in ("copy", "split_first", "split_last", "map", "file"):
        return raw
    raise RuntimeError("trasformazione non riconosciuta")


def kept_map(rule: dict) -> dict | None:
    raw = rule.get("valueMap")
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise RuntimeError("la mappa dei valori non è valida")
    clean = {}
    for key, value in list(raw.items())[:80]:
        clean[str(key)[:80]] = str(value)[:180]
    return clean


def with_policy(rule: dict, compiled: dict) -> dict:
    compiled["onMiss"] = miss_policy(rule)
    return keep_extras(rule, compiled)


def keep_extras(rule: dict, item: dict) -> dict:
    if rule.get("zone"):
        item["zone"] = str(rule["zone"])
    if rule.get("currencyDefault"):
        item["currencyDefault"] = str(rule["currencyDefault"])
    if rule.get("currencyField"):
        item["currencyField"] = str(rule["currencyField"])
    if rule.get("as") == "chiave":
        item["as"] = "chiave"
        if rule.get("lookupEntity"):
            item["lookupEntity"] = str(rule["lookupEntity"])
    return item


def compile_rules(entity: str, rules: list, creating: bool, back_label: str | None = None) -> list[dict]:
    catalog = load_catalog()
    meta = next((item for item in catalog if item["name"] == entity), None)
    if meta is None:
        raise RuntimeError("scheda Espo non disponibile")
    by_name = {field["name"]: field for field in meta["fields"]}
    compiled = []
    layout_names = []
    for rule in rules:
        source = str(rule.get("from") or "").strip()
        target = str(rule.get("to") or "").strip()
        role = rule.get("role") or "field"
        if role == "visibility":
            compiled.extend(carico.compile_visibility(rule))
            continue
        transform = kept_transform(rule)
        if transform.startswith("const:"):
            source = source or "_const"
        if not source or (not target and not transform.startswith("const:")):
            continue
        if not target:
            continue
        if role in ("link", "links", "parent"):
            foreign = str(rule.get("lookupEntity") or "").strip()
            foreign_meta, lookup_by = prepare_lookup(catalog, foreign, str(rule.get("lookupBy") or "").strip())
            if role == "parent":
                compiled.append(with_policy(rule, {
                    "from": source,
                    "to": "parentId",
                    "transform": "lookup",
                    "lookupEntity": foreign,
                    "lookupBy": lookup_by,
                    "parentType": foreign,
                }))
                continue
            if role == "links":
                chosen = by_name.get(target)
                if not (chosen and chosen.get("type") == "linkMultiple" and chosen.get("foreignEntity") == foreign):
                    matches = [
                        field for field in meta["fields"]
                        if field.get("type") == "linkMultiple" and field.get("foreignEntity") == foreign
                    ]
                    if len(matches) != 1:
                        raise RuntimeError("indica il collegamento multiplo verso " + foreign)
                    chosen = matches[0]
                compiled.append(with_policy(rule, {
                    "from": source,
                    "to": chosen["idName"],
                    "transform": "lookups",
                    "lookupEntity": foreign,
                    "lookupBy": lookup_by,
                }))
                continue
            existing = by_name.get(target)
            wanted = str(rule.get("linkName") or "").strip()
            if existing and existing.get("type") == "link" and existing.get("foreignEntity") == foreign:
                link_name = target
            else:
                matches = [
                    field for field in meta["fields"]
                    if field.get("type") == "link" and field.get("foreignEntity") == foreign
                ]
                if wanted and any(field.get("name") == wanted for field in matches):
                    link_name = wanted
                elif len(matches) == 1 and not wanted:
                    link_name = matches[0]["name"]
                elif len(matches) > 1 and not wanted:
                    raise RuntimeError("indica il nome del collegamento")
                else:
                    link_name = create_lookup(entity, foreign, foreign_meta["label"], back_label, wanted or None)
            compiled.append(with_policy(rule, {
                "from": source,
                "to": link_name + "Id",
                "transform": "lookup",
                "lookupEntity": foreign,
                "lookupBy": lookup_by,
            }))
            layout_names.append(link_name)
            continue
        chosen = by_name.get(target)
        if transform == "file" or (chosen and chosen.get("type") == "file"):
            if not chosen or chosen.get("type") != "file":
                raise RuntimeError("questo campo non è un file")
            compiled.append({"from": source, "to": chosen["idName"], "transform": "file"})
            continue
        if chosen and chosen.get("type") in ("linkMultiple", "linkParent"):
            raise RuntimeError("questo collegamento va indicato come collegamento a più record, o come attività")
        if creating and (target not in by_name or by_name[target].get("type") == "link"):
            requested = camel_name(target)
            kind = str(rule.get("fieldType") or "varchar").strip()
            raw_options = rule.get("options") if isinstance(rule.get("options"), list) else None
            actual = ensure_field(entity, requested, target, 180, kind, raw_options)
            compiled.append({"from": source, "to": actual, "transform": "copy"})
            layout_names.append(actual)
            continue
        if target not in by_name or by_name[target].get("type") == "link":
            raise RuntimeError("campi Espo non riconosciuti: " + target)
        item = {"from": source, "to": target, "transform": transform, "owner": carico.owner_of(rule)}
        if rule.get("required") in (True, 1, "1", "true", "si", "sì"):
            item["required"] = True
        label = chosen.get("label") or ""
        if chosen and chosen.get("type") == "bool":
            item["kind"] = "bool"
        elif chosen and chosen.get("type") == "phone":
            item["kind"] = "phone"
        elif chosen and chosen.get("type") in ("date", "datetime", "datetimeOptional"):
            item["kind"] = "date"
        elif chosen and chosen.get("type") in ("currency", "float"):
            item["kind"] = "importo"
        elif carico.is_fiscal_field(target, label):
            item["kind"] = "fiscale"
        elif chosen and chosen.get("type") == "enum":
            item["kind"] = "enum"
            item["options"] = list(chosen.get("options") or [])
        mapped_values = kept_map(rule)
        if transform == "map" and mapped_values:
            item["valueMap"] = mapped_values
        compiled.append(keep_extras(rule, item))
    if not compiled:
        raise RuntimeError("abbina almeno un campo")
    show_on_layout(entity, layout_names)
    CATALOG["at"] = 0
    return compiled


def save_pipeline(body: dict) -> dict:
    name = str(body.get("name") or "").strip()
    direction = body.get("direction")
    entity = str(body.get("espoEntity") or "").strip()
    external_id_field = str(body.get("externalIdField") or "").strip()
    mapping = body.get("mapping") or []
    if not name:
        raise RuntimeError("manca il nome dell'integrazione")
    if direction not in ("in", "out"):
        raise RuntimeError("scegli se i dati entrano o escono")
    if not entity:
        raise RuntimeError("scegli la scheda Espo")
    if direction == "in" and not external_id_field:
        raise RuntimeError("indica il campo che identifica il record nel sistema esterno")
    if not isinstance(mapping, list) or not mapping:
        raise RuntimeError("abbina almeno un campo")
    creating = False
    if entity == "__new__":
        if direction != "in":
            raise RuntimeError("una scheda nuova si crea quando i dati entrano in Espo")
        singular = str(body.get("newSingular") or "").strip()
        plural = str(body.get("newPlural") or "").strip()
        if not singular or not plural:
            raise RuntimeError("indica il nome singolare e plurale della scheda")
        entity = create_espo_entity(singular, plural)
        creating = True
    if direction == "in":
        clean = compile_rules(entity, mapping, creating, str(body.get("newPlural") or "").strip() or None)
        catalog = load_catalog()
        meta = next((item for item in catalog if item["name"] == entity), None)
        if meta is None:
            raise RuntimeError("scheda Espo non disponibile")
        if scope_customizable(entity):
            ensure_field(entity, "externalKey", "Chiave esterna", 180)
            key_field = meta["keyField"]
        else:
            key_field = ""
        CATALOG["at"] = 0
    else:
        clean = []
        catalog = load_catalog()
        meta = next((item for item in catalog if item["name"] == entity), None)
        if meta is None:
            raise RuntimeError("scheda Espo non disponibile")
        known = {field["name"] for field in meta["fields"]}
        for rule in mapping:
            source = str(rule.get("from") or "").strip()
            target = str(rule.get("to") or "").strip()
            if not source or not target:
                continue
            if source not in known:
                raise RuntimeError("campi Espo non riconosciuti: " + source)
            clean.append(keep_extras(rule, {"from": source, "to": target, "transform": "copy"}))
        if not clean:
            raise RuntimeError("abbina almeno un campo")
        key_field = meta["keyField"]
    schedule = int(body.get("scheduleMinutes") or 0)
    if schedule not in (0, 5, 15, 60):
        raise RuntimeError("la cadenza può essere manuale, 5, 15 o 60 minuti")
    schedule_at = str(body.get("scheduleAt") or "").strip()
    if schedule_at:
        carico._clock(schedule_at)
    expect_at = str(body.get("expectAt") or "").strip()
    if expect_at:
        carico._clock(expect_at)
    connection_id = str(body.get("connectionId") or "").strip()
    on_duplicate = str(body.get("onDuplicate") or "fail")
    if on_duplicate not in ("fail", "adopt"):
        raise RuntimeError("sul duplicato si scarta oppure si aggiorna il record già presente")
    cursor_column = str(body.get("cursorColumn") or "").strip()
    if cursor_column:
        safe_ident(cursor_column)
    raw_parents = body.get("dependsOn")
    parent_list = carico.parent_ids("", raw_parents) if isinstance(raw_parents, list) else []
    depends_on = parent_list[0] if parent_list else str(raw_parents or "").strip()
    with connect() as conn:
        if connection_id:
            link = conn.execute("SELECT * FROM connection WHERE id = ?", (connection_id,)).fetchone()
            if link is None:
                raise RuntimeError("collegamento non trovato")
            if link["kind"] == "http":
                expected = "out"
            elif link["kind"] in ("sftp", "ftps"):
                expected = direction
            else:
                expected = "in"
            if direction != expected:
                raise RuntimeError("il collegamento e il verso non coincidono")
        else:
            connection_id = None
        pipeline_id = str(body.get("id") or "").strip()
        previous = None
        if pipeline_id:
            previous = conn.execute("SELECT * FROM pipeline WHERE id = ?", (pipeline_id,)).fetchone()
            if previous is None:
                raise RuntimeError("integrazione non trovata")
        else:
            pipeline_id = slugify(name)
            suffix = 2
            base = pipeline_id
            while conn.execute("SELECT 1 FROM pipeline WHERE id = ?", (pipeline_id,)).fetchone():
                pipeline_id = f"{base}-{suffix}"
                suffix += 1
        if "enabled" in body:
            enabled = 0 if body.get("enabled") in (False, 0, "0") else 1
        elif previous is not None and previous["enabled"] is not None:
            enabled = previous["enabled"]
        else:
            enabled = 1
        if "dependsOn" not in body and previous is not None:
            depends_on = previous["depends_on"] or ""
            parent_list = []
            if previous["depends_json"]:
                try:
                    kept = json.loads(previous["depends_json"])
                    parent_list = kept if isinstance(kept, list) else []
                except json.JSONDecodeError:
                    parent_list = []
        if "cursorColumn" not in body and previous is not None:
            cursor_column = previous["cursor_column"] or ""
        if "onDuplicate" not in body and previous is not None and previous["on_duplicate"]:
            on_duplicate = previous["on_duplicate"]
        if "scheduleAt" not in body and previous is not None:
            schedule_at = previous["schedule_at"] or ""
        if "expectAt" not in body and previous is not None:
            expect_at = previous["expect_at"] or ""
        close_field = None
        close_value = None
        if direction == "in" and meta is not None:
            choice = carico.close_field_of(
                [field["name"] for field in meta["fields"]],
                {field["name"]: field.get("options") or [] for field in meta["fields"]},
            )
            if choice:
                close_field, close_value = choice
        if len(parent_list) > 1:
            depends_on = parent_list[0]
        if depends_on:
            if depends_on == pipeline_id or pipeline_id in parent_list:
                raise RuntimeError("un'integrazione non può aspettare sé stessa")
            seen = {pipeline_id}
            current = depends_on
            while current:
                if current in seen:
                    raise RuntimeError("le integrazioni si aspettano in cerchio")
                seen.add(current)
                parent = conn.execute("SELECT depends_on FROM pipeline WHERE id = ?", (current,)).fetchone()
                if parent is None:
                    raise RuntimeError("l'integrazione da eseguire prima non esiste")
                current = parent["depends_on"]
        if "keyColumns" in body and isinstance(body.get("keyColumns"), list):
            chosen = []
            for item in body.get("keyColumns") or []:
                name = str(item or "").strip()
                if name and name not in chosen:
                    chosen.append(name)
            if external_id_field and external_id_field not in chosen:
                chosen.insert(0, external_id_field)
            if len(chosen) >= 2:
                key_columns = json.dumps(chosen, ensure_ascii=False)
                external_id_field = chosen[0]
            else:
                key_columns = None
        elif previous is not None and previous["key_columns"]:
            key_columns = previous["key_columns"]
        else:
            key_columns = None
        multi = bool(key_columns)
        if direction == "in" and multi:
            names = json.loads(key_columns)
            key_template = pipeline_id + ":" + "|".join("{" + name + "}" for name in names)
        elif direction == "in" and previous is not None and previous["external_id_field"] == external_id_field and previous["key_template"]:
            key_template = previous["key_template"]
        else:
            key_template = f"{pipeline_id}:{{{external_id_field}}}" if direction == "in" else ""
        if direction == "out":
            external_id_field = external_id_field or "id"
        if enabled and (previous is None or not previous["enabled"]):
            step = conn.execute(
                "SELECT position, plan_id FROM plan_step WHERE pipeline_id = ?",
                (pipeline_id,),
            ).fetchone()
            if step is not None:
                earlier = conn.execute(
                    "SELECT confirmed FROM plan_step WHERE plan_id = ? AND position = ?",
                    (step["plan_id"], step["position"] - 1),
                ).fetchone()
                allowed, blocked = carico.step_may_enable(
                    True,
                    step["position"],
                    bool(earlier and earlier["confirmed"]),
                )
                if not allowed:
                    raise RuntimeError(blocked)
        conn.execute(
            """
            INSERT INTO pipeline
            (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field, connection_id, schedule_minutes, depends_on, cursor_column, enabled, on_duplicate, schedule_at, close_field, close_value, expect_at, key_columns)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                direction = excluded.direction,
                espo_entity = excluded.espo_entity,
                external_id_field = excluded.external_id_field,
                key_template = excluded.key_template,
                mapping_json = excluded.mapping_json,
                key_field = excluded.key_field,
                connection_id = excluded.connection_id,
                schedule_minutes = excluded.schedule_minutes,
                depends_on = excluded.depends_on,
                cursor_column = excluded.cursor_column,
                enabled = excluded.enabled,
                on_duplicate = excluded.on_duplicate,
                schedule_at = excluded.schedule_at,
                close_field = excluded.close_field,
                close_value = excluded.close_value,
                expect_at = excluded.expect_at,
                key_columns = excluded.key_columns
            """,
            (
                pipeline_id, name, direction, entity, external_id_field, key_template,
                json.dumps(clean, ensure_ascii=False), key_field, connection_id, schedule,
                depends_on or None, cursor_column or None, enabled, on_duplicate,
                schedule_at or None, close_field, close_value, expect_at or None, key_columns,
            ),
        )
        if "proposeFrom" in body or "proposeEntity" in body or "proposeField" in body or "proposeValue" in body:
            conn.execute(
                """
                UPDATE pipeline
                SET propose_from = ?, propose_entity = ?, propose_field = ?, propose_value = ?
                WHERE id = ?
                """,
                (
                    str(body.get("proposeFrom") or "").strip() or None,
                    str(body.get("proposeEntity") or "").strip() or None,
                    str(body.get("proposeField") or "").strip() or None,
                    str(body.get("proposeValue") or "").strip() or None,
                    pipeline_id,
                ),
            )
        if "alertMinutes" in body:
            raw = str(body.get("alertMinutes") or "").strip()
            minutes = int(raw) if raw.isdigit() and int(raw) > 0 else None
            conn.execute("UPDATE pipeline SET alert_minutes = ? WHERE id = ?", (minutes, pipeline_id))
        depends_json = json.dumps(parent_list, ensure_ascii=False) if len(parent_list) > 1 else None
        if "dependsOn" not in body and previous is not None:
            depends_json = previous["depends_json"]
        write_back = int(previous["write_back"] or 0) if previous is not None else 0
        write_fields = previous["write_fields"] if previous is not None else None
        activity_json = previous["activity_json"] if previous is not None else None
        portal_json = previous["portal_json"] if previous is not None else None
        if "writeBack" in body:
            write_back = 0 if body.get("writeBack") in (False, 0, "0", "", None) else 1
        if "writeFields" in body and isinstance(body.get("writeFields"), list):
            write_fields = json.dumps([str(item) for item in body["writeFields"] if str(item).strip()], ensure_ascii=False)
        if "activity" in body:
            activity_json = json.dumps(body.get("activity") or {}, ensure_ascii=False) if body.get("activity") else None
        if "portal" in body:
            portal_json = json.dumps(body.get("portal") or {}, ensure_ascii=False) if body.get("portal") else None
        conn.execute(
            """
            UPDATE pipeline
            SET depends_json = ?, write_back = ?, write_fields = ?, activity_json = ?, portal_json = ?
            WHERE id = ?
            """,
            (depends_json, write_back, write_fields, activity_json, portal_json, pipeline_id),
        )
        remember_version(pipeline_id, clean, str(body.get("author") or ""))
    try:
        sync_service_role()
    except Exception as error:
        print("[motore] ruolo Nesso", error)
    return {"id": pipeline_id, "name": name, "direction": direction, "espoEntity": entity}


def delete_pipeline(pipeline_id: str) -> dict:
    with connect() as conn:
        found = conn.execute("SELECT id FROM pipeline WHERE id = ?", (pipeline_id,)).fetchone()
        if found is None:
            raise KeyError(pipeline_id)
        conn.execute("DELETE FROM queue_item WHERE pipeline_id = ?", (pipeline_id,))
        conn.execute("DELETE FROM sink_item WHERE pipeline_id = ?", (pipeline_id,))
        conn.execute("DELETE FROM cursor_state WHERE pipeline_id = ?", (pipeline_id,))
        conn.execute("DELETE FROM scarto WHERE pipeline_id = ?", (pipeline_id,))
        conn.execute("DELETE FROM run_log WHERE pipeline_id = ?", (pipeline_id,))
        conn.execute("DELETE FROM watch_item WHERE pipeline_id = ?", (pipeline_id,))
        conn.execute("DELETE FROM field_history WHERE pipeline_id = ?", (pipeline_id,))
        conn.execute("DELETE FROM presenza WHERE pipeline_id = ?", (pipeline_id,))
        conn.execute("DELETE FROM pending_close WHERE pipeline_id = ?", (pipeline_id,))
        conn.execute("DELETE FROM stage_proposal WHERE pipeline_id = ?", (pipeline_id,))
        conn.execute("DELETE FROM notice WHERE pipeline_id = ?", (pipeline_id,))
        conn.execute("DELETE FROM pipeline WHERE id = ?", (pipeline_id,))
    return {"deleted": pipeline_id}


def public_connection(row: sqlite3.Row) -> dict:
    config = json.loads(row["config_json"])
    if config.get("password"):
        config["hasPassword"] = True
        config["password"] = ""
    if config.get("tunnelPassword"):
        config["hasTunnelPassword"] = True
        config["tunnelPassword"] = ""
    if config.get("token"):
        config["hasToken"] = True
        config["token"] = ""
    if config.get("headerValue"):
        config["hasHeader"] = True
        config["headerValue"] = ""
    for secret, flag in (
        ("signSecret", "hasSignSecret"),
        ("clientSecret", "hasClientSecret"),
        ("accessToken", "hasAccessToken"),
        ("refreshToken", "hasRefreshToken"),
    ):
        if config.get(secret):
            config[flag] = True
            config[secret] = ""
    item = {"id": row["id"], "name": row["name"], "kind": row["kind"], "config": config}
    if row["kind"] == "webhook":
        item["url"] = f"{PUBLIC_BASE}/hook/{row['id']}/{row['token']}"
    if row["kind"] == "http":
        item["inboxUrl"] = f"{PUBLIC_BASE}/inbox/{row['id']}/{row['token']}"
    if row["kind"] == "csv" or row["kind"] == "pdf":
        item["folder"] = str(SCAMBIO / row["id"])
        config["columns"] = csv_headers(row["id"]) if row["kind"] == "csv" else []
    return item


def validate_select(query: str) -> str:
    sql = str(query or "").strip().rstrip(";").strip()
    if not sql:
        raise RuntimeError("manca la query")
    if len(sql) > 4000:
        raise RuntimeError("query troppo lunga")
    if ";" in sql or not re.match(r"(?is)^(select|with)\b", sql):
        raise RuntimeError("è ammessa una sola SELECT")
    return sql


def remember_delivery(pipeline_id: str | None, connection_id: str | None, payload: dict, status: str, detail: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO delivery (pipeline_id, connection_id, payload_json, status, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                pipeline_id,
                connection_id,
                json.dumps(payload, ensure_ascii=False),
                status,
                detail[:500],
                time.strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )


def mark_run(pipeline_id: str, status: str, detail: str, counts: dict | None = None) -> None:
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    text = detail[:500]
    raw_counts = json.dumps(counts, ensure_ascii=False) if counts else None
    productive = bool(counts) and any(counts.get(name) for name in ("created", "updated", "unchanged", "closed"))
    keep_clock = status == "errore" and setting_value("retry_failed") == "1"
    with connect() as conn:
        if keep_clock and raw_counts is None:
            conn.execute(
                "UPDATE pipeline SET last_status = ?, last_detail = ? WHERE id = ?",
                (status, text, pipeline_id),
            )
        elif keep_clock:
            conn.execute(
                "UPDATE pipeline SET last_status = ?, last_detail = ?, last_counts = ? WHERE id = ?",
                (status, text, raw_counts, pipeline_id),
            )
        elif raw_counts is None:
            conn.execute(
                "UPDATE pipeline SET last_run = ?, last_status = ?, last_detail = ? WHERE id = ?",
                (now, status, text, pipeline_id),
            )
        else:
            conn.execute(
                "UPDATE pipeline SET last_run = ?, last_status = ?, last_detail = ?, last_counts = ? WHERE id = ?",
                (now, status, text, raw_counts, pipeline_id),
            )
        if status == "ok" and productive:
            conn.execute(
                "UPDATE pipeline SET last_success = ?, file_alert = 0 WHERE id = ?",
                (now, pipeline_id),
            )
        conn.execute(
            "INSERT INTO run_log (pipeline_id, status, detail, created_at) VALUES (?, ?, ?, ?)",
            (pipeline_id, status, text, now),
        )
    if status == "errore":
        open_notice(pipeline_id, "fallito")
    elif status == "ok":
        close_notices(pipeline_id, None if productive else "fallito")


def remember_reject(pipeline_id: str, external_id: str, payload, detail: str) -> None:
    if not isinstance(payload, dict):
        payload = {"valore": str(payload)[:500]}
    raw = json.dumps(payload, ensure_ascii=False, default=str)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO scarto (pipeline_id, external_id, payload_json, detail, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                pipeline_id,
                (external_id or "")[:180],
                raw[:4000],
                detail[:500],
                time.strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
    queue_retry(pipeline_id, (external_id or "")[:180], raw[:4000])


def queue_retry(pipeline_id: str, external_id: str, payload: str) -> None:
    if setting_value("retry_queue") != "1" or not external_id.strip():
        return
    nxt = (datetime.now() + timedelta(minutes=carico.retry_wait(0))).strftime("%Y-%m-%d %H:%M:%S")
    with connect() as conn:
        existing = conn.execute(
            "SELECT id FROM retry_item WHERE pipeline_id = ? AND external_id = ? AND status = 'attesa'",
            (pipeline_id, external_id),
        ).fetchone()
        if existing:
            return
        conn.execute(
            """
            INSERT INTO retry_item (pipeline_id, external_id, payload_json, attempts, next_at, status)
            VALUES (?, ?, ?, 0, ?, 'attesa')
            """,
            (pipeline_id, external_id, payload, nxt),
        )


def retry_rejects() -> int:
    if setting_value("retry_queue") != "1":
        return 0
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM retry_item
            WHERE status = 'attesa' AND next_at <= ?
            ORDER BY id LIMIT 20
            """,
            (now,),
        ).fetchall()
    done = 0
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        result = ingest_row(row["pipeline_id"], payload)
        with connect() as conn:
            if result.get("status") != "scartato":
                conn.execute("UPDATE retry_item SET status = 'fatto' WHERE id = ?", (row["id"],))
                done += 1
                continue
            attempts = int(row["attempts"] or 0) + 1
            if attempts >= 8:
                conn.execute(
                    "UPDATE retry_item SET status = 'scarto', attempts = ? WHERE id = ?",
                    (attempts, row["id"]),
                )
                continue
            nxt = (datetime.now() + timedelta(minutes=carico.retry_wait(attempts))).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "UPDATE retry_item SET attempts = ?, next_at = ? WHERE id = ?",
                (attempts, nxt, row["id"]),
            )
    return done


def ingest_row(pipeline_id: str, payload: dict, hold: bool = False) -> dict:
    try:
        return ingest(pipeline_id, payload, hold=hold)
    except Exception as error:
        external = ""
        key = ""
        if isinstance(payload, dict):
            with connect() as conn:
                row = conn.execute(
                    "SELECT external_id_field, key_template FROM pipeline WHERE id = ?",
                    (pipeline_id,),
                ).fetchone()
            if row is not None:
                try:
                    external = external_of(row, payload)
                except Exception:
                    external = str(payload.get(row["external_id_field"]) or "")
                try:
                    key = render_key(row["key_template"], payload)
                except Exception:
                    key = ""
        remember_reject(pipeline_id, external, payload, str(error))
        return {"status": "scartato", "detail": str(error), "externalKey": key}


def fresh_counts() -> dict:
    return {
        "created": 0, "updated": 0, "unchanged": 0, "failed": 0, "closed": 0,
        "queued": 0, "held": False, "confirm": False, "first": "", "pericolose": [],
    }


def tally(item: dict, counts: dict) -> None:
    status = item.get("status")
    if status == "lettura":
        counts["held"] = True
        status = item.get("would") or "invariato"
    for diff in item.get("diffs") or []:
        if len(counts["pericolose"]) < 20:
            counts["pericolose"].append(diff)
    if status == "creato":
        counts["created"] += 1
    elif status == "aggiornato":
        counts["updated"] += 1
    elif status == "invariato":
        counts["unchanged"] += 1
    elif status == "in coda":
        counts["queued"] += 1
    elif status == "chiuso":
        counts["closed"] += 1
    else:
        counts["failed"] += 1
        if not counts["first"]:
            counts["first"] = item.get("detail") or ""


def finish_counts(prefix: str, counts: dict) -> tuple[str, str]:
    detail = carico.summary_line(counts, prefix)
    if counts.get("queued"):
        detail += f", {counts['queued']} in coda"
    worked = counts["created"] or counts["updated"] or counts["unchanged"] or counts["closed"] or counts["queued"]
    if counts.get("confirm"):
        return "conferma", detail
    if counts.get("held"):
        return "lettura", detail
    status = "errore" if counts["failed"] and not worked else "ok"
    return status, detail


def save_connection(body: dict) -> dict:
    name = str(body.get("name") or "").strip()
    kind = body.get("kind")
    if not name:
        raise RuntimeError("manca il nome del collegamento")
    if kind not in ("webhook", "database", "csv", "http", "pdf", "sftp", "ftps", "documento"):
        raise RuntimeError("tipo di collegamento non riconosciuto")
    config = body.get("config") or {}
    if kind == "database":
        for field in ("host", "database", "user", "query"):
            if not str(config.get(field) or "").strip():
                raise RuntimeError(f"manca {field}")
        engine = str(config.get("engine") or "mysql")
        if engine not in carico.ENGINES:
            raise RuntimeError("motore database non riconosciuto")
        config["query"] = validate_select(config["query"])
        config["engine"] = engine
        config["port"] = int(config.get("port") or carico.engine_port(engine))
        config["host"] = str(config["host"]).strip()
        config["database"] = str(config["database"]).strip()
        config["user"] = str(config["user"]).strip()
        config["tls"] = bool(config.get("tls"))
        config["sslCa"] = str(config.get("sslCa") or "").strip()
        config["tunnelHost"] = str(config.get("tunnelHost") or "").strip()
        config["tunnelPort"] = int(config.get("tunnelPort") or 22) if config.get("tunnelHost") else ""
        config["tunnelUser"] = str(config.get("tunnelUser") or "").strip()
        config["tunnelPassword"] = str(config.get("tunnelPassword") or "")
    if kind in ("sftp", "ftps"):
        for field in ("host", "user", "path"):
            if not str(config.get(field) or "").strip():
                raise RuntimeError(f"manca {field}")
        config = {
            "host": str(config["host"]).strip(),
            "port": int(config.get("port") or (22 if kind == "sftp" else 21)),
            "user": str(config["user"]).strip(),
            "password": str(config.get("password") or ""),
            "path": str(config["path"]).strip(),
        }
    if kind == "http":
        url = str(config.get("url") or "").strip()
        if url and not url.startswith(("http://", "https://")):
            raise RuntimeError("l'indirizzo di destinazione deve essere http o https")
        auth = str(config.get("auth") or "none")
        if auth not in ("none", "bearer", "basic", "header", "oauth"):
            raise RuntimeError("autenticazione della destinazione non riconosciuta")
        header_name = str(config.get("headerName") or "").strip()
        if auth == "header" and not re.match(r"^[A-Za-z0-9-]{1,40}$", header_name):
            raise RuntimeError("nome intestazione non valido")
        token_url = str(config.get("tokenUrl") or "").strip()
        if auth == "oauth" and token_url and not token_url.startswith(("http://", "https://")):
            raise RuntimeError("l'indirizzo del token deve essere http o https")
        config = {
            "url": url,
            "auth": auth,
            "token": str(config.get("token") or ""),
            "user": str(config.get("user") or "").strip(),
            "password": str(config.get("password") or ""),
            "headerName": header_name,
            "headerValue": str(config.get("headerValue") or ""),
            "tokenUrl": token_url,
            "clientId": str(config.get("clientId") or "").strip(),
            "clientSecret": str(config.get("clientSecret") or ""),
            "scope": str(config.get("scope") or "").strip(),
            "accessToken": str(config.get("accessToken") or ""),
            "refreshToken": str(config.get("refreshToken") or ""),
            "tokenObtained": str(config.get("tokenObtained") or ""),
            "expiresIn": int(config.get("expiresIn") or 0),
            "deliverTo": str(config.get("deliverTo") or "").strip(),
        }
    if kind == "documento":
        config = {
            "documentFolder": str(config.get("documentFolder") or "").strip(),
            "team": str(config.get("team") or "").strip(),
        }
    if kind == "webhook":
        config = {"signSecret": str(config.get("signSecret") or "").strip()}
    if kind == "csv":
        config = {}
    if kind == "pdf":
        config = {
            "documentFolder": str(config.get("documentFolder") or "").strip(),
            "team": str(config.get("team") or "").strip(),
        }
    with connect() as conn:
        connection_id = str(body.get("id") or "").strip()
        if connection_id:
            current = conn.execute("SELECT * FROM connection WHERE id = ?", (connection_id,)).fetchone()
            if current is None:
                raise RuntimeError("collegamento non trovato")
            token = current["token"]
            previous = json.loads(current["config_json"])
            opened = carico.open_config(previous, secret_key())
            if kind == "database" and not str(config.get("password") or "") and opened.get("password"):
                config["password"] = opened["password"]
            if kind == "database" and not str(config.get("tunnelPassword") or "") and opened.get("tunnelPassword"):
                config["tunnelPassword"] = opened["tunnelPassword"]
            if kind in ("sftp", "ftps") and not str(config.get("password") or "") and opened.get("password"):
                config["password"] = opened["password"]
            if kind == "http":
                if not config.get("token") and opened.get("token"):
                    config["token"] = opened["token"]
                if not config.get("password") and opened.get("password"):
                    config["password"] = opened["password"]
                if not config.get("headerValue") and opened.get("headerValue"):
                    config["headerValue"] = opened["headerValue"]
                if not config.get("clientSecret") and opened.get("clientSecret"):
                    config["clientSecret"] = opened["clientSecret"]
                for kept in ("accessToken", "refreshToken", "tokenObtained", "expiresIn"):
                    if opened.get(kept) and not config.get(kept):
                        config[kept] = opened[kept]
            if kind == "webhook" and not config.get("signSecret") and opened.get("signSecret"):
                config["signSecret"] = opened["signSecret"]
        else:
            connection_id = slugify(name)
            suffix = 2
            base = connection_id
            while conn.execute("SELECT 1 FROM connection WHERE id = ?", (connection_id,)).fetchone():
                connection_id = f"{base}-{suffix}"
                suffix += 1
            token = secrets.token_urlsafe(24)
        if kind == "http" and config.get("auth") == "oauth":
            if not str(config.get("tokenUrl") or "").startswith(("http://", "https://")):
                raise RuntimeError("l'indirizzo del token deve essere http o https")
            if not config.get("clientId"):
                raise RuntimeError("manca clientId")
            if not config.get("clientSecret"):
                raise RuntimeError("manca clientSecret")
        if kind == "database":
            columns = read_database(config, sample=1)
            config["columns"] = list(columns[0].keys()) if columns else []
            config_note = columns
        else:
            config_note = []
        conn.execute(
            """
            INSERT INTO connection (id, name, kind, config_json, token)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                kind = excluded.kind,
                config_json = excluded.config_json
            """,
            (connection_id, name, kind, json.dumps(carico.seal_config(config, secret_key()), ensure_ascii=False), token),
        )
    if kind == "csv" or kind == "documento":
        folder = SCAMBIO / connection_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "elaborati").mkdir(exist_ok=True)
    result = {"id": connection_id, "name": name, "kind": kind}
    if kind == "webhook":
        result["url"] = f"{PUBLIC_BASE}/hook/{connection_id}/{token}"
    if kind == "http":
        result["inboxUrl"] = f"{PUBLIC_BASE}/inbox/{connection_id}/{token}"
    if kind == "database":
        result["columns"] = list(config_note[0].keys()) if config_note else []
    if kind == "csv":
        result["folder"] = connection_id
    return result


def mysql_kwargs(config: dict) -> dict:
    import pymysql

    kwargs = {
        "host": config["host"],
        "port": int(config.get("port") or 3306),
        "user": config["user"],
        "password": config.get("password") or "",
        "database": config["database"],
        "connect_timeout": 8,
        "read_timeout": 30,
        "cursorclass": pymysql.cursors.DictCursor,
    }
    if config.get("tls"):
        ssl = {}
        if config.get("sslCa"):
            ssl["ca"] = str(config["sslCa"])
        kwargs["ssl"] = ssl
    return kwargs


def open_sql(config: dict):
    engine = str(config.get("engine") or "mysql")
    host = config["host"]
    port = int(config.get("port") or carico.engine_port(engine))
    user = config["user"]
    password = config.get("password") or ""
    database = config["database"]
    if engine == "mysql":
        import pymysql

        return pymysql.connect(**mysql_kwargs(config))
    if engine == "postgres":
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=database,
            connect_timeout=8,
            sslmode="require" if config.get("tls") else "disable",
            row_factory=dict_row,
        )
    if engine == "mssql":
        try:
            import pymssql
        except ImportError as error:
            raise RuntimeError("il driver mssql non è installato") from error
        return pymssql.connect(
            server=host,
            port=port,
            user=user,
            password=password,
            database=database,
            login_timeout=8,
            timeout=30,
            as_dict=True,
            tds_version="7.4",
        )
    if engine == "oracle":
        import oracledb

        protocol = "tcps" if config.get("tls") else "tcp"
        return oracledb.connect(
            user=user,
            password=password,
            dsn=f"{protocol}://{host}:{port}/{database}",
        )
    raise RuntimeError("motore database non riconosciuto")


def start_tunnel(config: dict, dest_host: str, dest_port: int):
    import socket
    import threading

    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        str(config["tunnelHost"]),
        port=int(config.get("tunnelPort") or 22),
        username=str(config.get("tunnelUser") or ""),
        password=str(config.get("tunnelPassword") or ""),
        timeout=8,
        allow_agent=False,
        look_for_keys=False,
    )
    transport = client.get_transport()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    local_port = listener.getsockname()[1]
    stopped = threading.Event()

    def serve() -> None:
        while not stopped.is_set():
            listener.settimeout(0.5)
            try:
                sock, _peer = listener.accept()
            except OSError:
                continue
            try:
                channel = transport.open_channel(
                    "direct-tcpip",
                    (dest_host, int(dest_port)),
                    sock.getpeername(),
                )
            except Exception:
                sock.close()
                continue

            def pipe(source, target) -> None:
                try:
                    while True:
                        data = source.recv(65536)
                        if not data:
                            break
                        target.sendall(data)
                except Exception:
                    pass
                try:
                    source.close()
                except Exception:
                    pass
                try:
                    target.close()
                except Exception:
                    pass

            threading.Thread(target=pipe, args=(sock, channel), daemon=True).start()
            threading.Thread(target=pipe, args=(channel, sock), daemon=True).start()

    threading.Thread(target=serve, daemon=True).start()

    def close() -> None:
        stopped.set()
        try:
            listener.close()
        except OSError:
            pass
        client.close()

    return close, local_port


def fetch_dicts(connection, sql: str, params: list) -> list[dict]:
    cursor = connection.cursor()
    try:
        cursor.execute(sql, params or None)
        raw = cursor.fetchall()
        if raw and not isinstance(raw[0], dict):
            columns = [item[0] for item in cursor.description]
            raw = [dict(zip(columns, row)) for row in raw]
    finally:
        cursor.close()
    return [
        {key: None if value is None else str(value) for key, value in row.items()}
        for row in raw
    ]


def read_database(
    config: dict,
    sample: int | None = None,
    cursor_column: str | None = None,
    cursor_value: str | None = None,
    id_column: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    engine = str(config.get("engine") or "mysql")
    if engine not in carico.ENGINES:
        raise RuntimeError("motore database non riconosciuto")
    sql = validate_select(config["query"])
    where = ""
    order = ""
    params: list[str] = []
    active = dict(config)
    closer = None
    if config.get("tunnelHost"):
        dest_port = int(config.get("port") or carico.engine_port(engine))
        closer, local_port = start_tunnel(config, config["host"], dest_port)
        active["host"] = "127.0.0.1"
        active["port"] = local_port
        active["tunnelHost"] = ""
    if cursor_column and id_column and not sample:
        column = safe_ident(cursor_column)
        identity = safe_ident(id_column)
        quoted_column = carico.quote_ident(column, engine)
        quoted_identity = carico.quote_ident(identity, engine)
        order = f"ORDER BY {quoted_column}, {quoted_identity}"
        stamp, last_id = split_cursor(cursor_value or "")
        if stamp:
            if engine == "oracle":
                where = (
                    f"WHERE {quoted_column} > :1 OR "
                    f"({quoted_column} = :2 AND {quoted_identity} > :3)"
                )
            else:
                where = (
                    f"WHERE {quoted_column} > %s OR "
                    f"({quoted_column} = %s AND {quoted_identity} > %s)"
                )
            params = [stamp, stamp, last_id]
    escape = bool(params) and engine != "oracle"
    source = sql.replace("%", "%%") if escape else sql

    def page(size: int, offset: int) -> list[dict]:
        if engine == "mysql":
            wrapped = (
                f"SELECT * FROM ({source}) AS sorgente {where} {order} "
                f"LIMIT {int(size)} OFFSET {int(offset)}"
            )
        else:
            wrapped = carico.page_sql(source, engine, where, order, size, offset)
        connection = open_sql(active)
        try:
            return fetch_dicts(connection, wrapped, params)
        finally:
            connection.close()

    try:
        if sample or limit is not None:
            return page(5 if sample and limit is None else int(limit or 5), 0)
        return carico.collect_pages(page, carico.PAGE_SIZE)
    finally:
        if closer:
            closer()


def csv_delimiter(header: str) -> str:
    return ";" if header.count(";") > header.count(",") else ","


def sheet_paths(folder: Path) -> list[Path]:
    found = list(folder.glob("*.csv")) + list(folder.glob("*.xlsx"))
    return sorted(found, key=lambda path: path.name.lower())


def read_table(path: Path) -> tuple[list[str], list[dict]]:
    if path.suffix.lower() == ".xlsx":
        return carico.rows_from_xlsx(path.read_bytes())
    return read_csv_file(path)


def csv_headers(connection_id: str) -> list[str]:
    folder = SCAMBIO / connection_id
    if not folder.is_dir():
        return []
    for path in sheet_paths(folder):
        try:
            headers, _rows = read_table(path)
        except (OSError, IndexError, ValueError):
            return []
        return headers
    return []


def read_csv_folder(connection_id: str) -> list[tuple[Path, dict]]:
    folder = SCAMBIO / connection_id
    folder.mkdir(parents=True, exist_ok=True)
    done = folder / "elaborati"
    done.mkdir(exist_ok=True)
    found = []
    for path in sheet_paths(folder):
        _headers, rows = read_table(path)
        for row in rows:
            found.append((path, row))
    return found


def destination_headers(config: dict) -> dict:
    headers = {}
    auth = config.get("auth") or "none"
    if auth == "bearer" and config.get("token"):
        headers["Authorization"] = "Bearer " + str(config["token"])
    elif auth == "basic" and config.get("user"):
        raw = f"{config.get('user')}:{config.get('password') or ''}".encode()
        headers["Authorization"] = "Basic " + __import__("base64").b64encode(raw).decode()
    elif auth == "header" and config.get("headerName") and config.get("headerValue"):
        headers[str(config["headerName"])] = str(config["headerValue"])
    return headers


def request_oauth(config: dict, grant: str) -> dict:
    fields = {
        "grant_type": grant,
        "client_id": str(config.get("clientId") or ""),
        "client_secret": str(config.get("clientSecret") or ""),
    }
    if grant == "refresh_token":
        fields["refresh_token"] = str(config.get("refreshToken") or "")
    elif config.get("scope"):
        fields["scope"] = str(config["scope"])
    data = urllib.parse.urlencode(fields).encode()
    request = urllib.request.Request(str(config.get("tokenUrl") or ""), data=data, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"token OAuth HTTP {error.code}") from error
    if not isinstance(payload, dict):
        raise RuntimeError("OAuth non ha restituito un token")
    return payload


def store_oauth(connection_id: str, updates: dict) -> None:
    with connect() as conn:
        row = conn.execute("SELECT config_json FROM connection WHERE id = ?", (connection_id,)).fetchone()
        if row is None:
            return
        current = carico.open_config(json.loads(row["config_json"]), secret_key())
        current.update(updates)
        sealed = carico.seal_config(current, secret_key())
        conn.execute(
            "UPDATE connection SET config_json = ? WHERE id = ?",
            (json.dumps(sealed, ensure_ascii=False), connection_id),
        )


def fresh_oauth_token(connection_id: str, config: dict, now: datetime | None = None, fetch=None) -> str:
    moment = now or datetime.now()
    caller = fetch or request_oauth
    if config.get("accessToken") and not carico.oauth_expired(
        config.get("tokenObtained"), int(config.get("expiresIn") or 0), moment
    ):
        return str(config["accessToken"])
    grant = "refresh_token" if config.get("refreshToken") else "client_credentials"
    try:
        payload = caller(config, grant)
    except Exception:
        if grant != "refresh_token":
            raise
        payload = caller(config, "client_credentials")
    token = str((payload or {}).get("access_token") or "")
    if not token:
        raise RuntimeError("OAuth non ha restituito un token")
    expires = int((payload or {}).get("expires_in") or 3600)
    updates = {
        "accessToken": token,
        "tokenObtained": moment.strftime("%Y-%m-%d %H:%M:%S"),
        "expiresIn": expires,
    }
    if (payload or {}).get("refresh_token"):
        updates["refreshToken"] = str(payload["refresh_token"])
    store_oauth(connection_id, updates)
    config.update(updates)
    return token


def outbound_headers(connection_id: str, config: dict) -> dict:
    if (config.get("auth") or "none") != "oauth":
        return destination_headers(config)
    return {"Authorization": "Bearer " + fresh_oauth_token(connection_id, config)}


def post_json(url: str, payload: dict, headers: dict | None = None) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode()
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status >= 300:
                raise RuntimeError(f"destinazione HTTP {response.status}")
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"destinazione HTTP {error.code}") from error


def accept_hook(
    connection_id: str,
    token: str,
    body: dict | list,
    raw: bytes | None = None,
    signature: str | None = None,
) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM connection WHERE id = ?", (connection_id,)).fetchone()
        pipelines = [
            item["id"]
            for item in conn.execute(
                """
                SELECT id FROM pipeline
                WHERE connection_id = ? AND direction = 'in' AND COALESCE(enabled, 1) = 1
                """,
                (connection_id,),
            )
        ]
        any_pipeline = conn.execute(
            "SELECT 1 FROM pipeline WHERE connection_id = ? AND direction = 'in'",
            (connection_id,),
        ).fetchone()
    if row is None or row["kind"] != "webhook" or not hmac.compare_digest(row["token"], token):
        raise PermissionError("collegamento non valido")
    secret = str(stored_config(row["config_json"]).get("signSecret") or "")
    if secret and not carico.signature_matches(secret, raw if raw is not None else b"", signature or ""):
        raise PermissionError("firma non valida")
    if isinstance(body, dict) and isinstance(body.get("records"), list):
        records = body["records"]
    elif isinstance(body, list):
        records = body
    elif isinstance(body, dict):
        records = [body]
    else:
        raise RuntimeError("il corpo deve essere un oggetto o un elenco")
    if not pipelines:
        if any_pipeline:
            raise RuntimeError("le integrazioni di questo collegamento sono in pausa")
        raise RuntimeError("nessuna integrazione usa questo collegamento")
    done = []
    failed = 0
    for pipeline_id in pipelines:
        decision = silence_for(pipeline_id)
        if decision["action"] != "scrivi":
            for record in records:
                if isinstance(record, dict):
                    park_silence(pipeline_id, record, decision.get("reason") or "")
                else:
                    remember_reject(pipeline_id, "", {"valore": str(record)[:300]}, "la riga non è un oggetto")
            done.append({"status": "attesa", "pipelineId": pipeline_id})
            continue
        counts = fresh_counts()
        for record in records:
            if not isinstance(record, dict):
                remember_reject(pipeline_id, "", {"valore": str(record)[:300]}, "la riga non è un oggetto")
                tally({"status": "scartato", "detail": "la riga non è un oggetto"}, counts)
                continue
            with connect() as conn:
                pipeline = conn.execute("SELECT * FROM pipeline WHERE id = ?", (pipeline_id,)).fetchone()
            held = writes_held(pipeline)[0] if pipeline is not None else False
            item = ingest_row(pipeline_id, record, hold=held)
            tally(item, counts)
            done.append(item)
        failed += counts["failed"]
        status, detail = finish_counts(f"{len(records)} record via webhook", counts)
        mark_run(pipeline_id, status, detail, counts)
    return {"accepted": len(done) - failed, "failed": failed, "results": done}


def accept_inbox(connection_id: str, token: str, body: dict) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM connection WHERE id = ?", (connection_id,)).fetchone()
    if row is None or row["kind"] != "http" or not hmac.compare_digest(row["token"], token):
        raise PermissionError("casella non valida")
    remember_delivery(None, connection_id, body, "ricevuto", "sistema esterno")
    delivered = deliver_inbox(connection_id, body)
    return {"stored": True, "delivered": delivered}


def deliver_inbox(connection_id: str, body: dict) -> bool:
    with connect() as conn:
        row = conn.execute("SELECT config_json FROM connection WHERE id = ?", (connection_id,)).fetchone()
        if row is None:
            return False
        config = stored_config(row["config_json"])
        target = str(config.get("deliverTo") or "").strip()
        if not target:
            return False
        pipeline = conn.execute("SELECT enabled FROM pipeline WHERE id = ?", (target,)).fetchone()
    if pipeline is None or pipeline["enabled"] == 0:
        return False
    latest = None
    with connect() as conn:
        latest = conn.execute(
            "SELECT id, status FROM delivery WHERE connection_id = ? ORDER BY id DESC LIMIT 1",
            (connection_id,),
        ).fetchone()
    if latest is None or latest["status"] == "consegnato":
        return False
    result = ingest_row(target, body if isinstance(body, dict) else {"valore": body})
    if result.get("status") == "scartato":
        return False
    with connect() as conn:
        conn.execute("UPDATE delivery SET status = 'consegnato' WHERE id = ?", (latest["id"],))
    return True


def pipeline_due(row: sqlite3.Row, now: float | None = None) -> bool:
    if row["enabled"] == 0:
        return False
    schedule_at = row["schedule_at"] if "schedule_at" in row.keys() else None
    if schedule_at:
        moment = datetime.fromtimestamp(now if now is not None else time.time())
        return carico.fixed_due(schedule_at, row["last_run"], moment)
    if not row["schedule_minutes"]:
        return not row["last_run"]
    if not row["last_run"]:
        return True
    moment = now if now is not None else time.time()
    previous = time.mktime(time.strptime(row["last_run"], "%Y-%m-%d %H:%M:%S"))
    return moment - previous >= row["schedule_minutes"] * 60


def preview_row(pipeline: sqlite3.Row, payload: dict) -> dict:
    external = external_of(pipeline, payload)
    if pipeline["direction"] == "in" and not external:
        raise RuntimeError(f"manca il campo {pipeline['external_id_field']}")
    key = render_key(pipeline["key_template"], payload) if pipeline["direction"] == "in" else None
    mapped = map_payload(
        json.loads(pipeline["mapping_json"]),
        payload,
        key,
        pipeline["key_field"] or "cExternalKey",
        dry=True,
    )
    return {"externalId": external, "mapped": mapped}


def dry_run(pipeline_id: str, sample=None) -> dict:
    with connect() as conn:
        pipeline = conn.execute("SELECT * FROM pipeline WHERE id = ?", (pipeline_id,)).fetchone()
        link = None
        if pipeline and pipeline["connection_id"]:
            link = conn.execute("SELECT * FROM connection WHERE id = ?", (pipeline["connection_id"],)).fetchone()
    if pipeline is None:
        raise KeyError(pipeline_id)
    if pipeline["direction"] == "out":
        rows = outbound_rows(pipeline_id, limit=5)
        return {"rows": [{"espoId": item["espoId"], "mapped": item["payload"]} for item in rows]}
    if link is None:
        raise RuntimeError("collega un sistema esterno prima della prova")
    if link["kind"] == "webhook":
        if sample is None:
            return {"detail": "Il webhook non ha righe da leggere. L'anteprima si fa quando il sistema esterno chiama.", "rows": []}
        try:
            records = carico.hook_records(sample)
        except RuntimeError as error:
            return {"detail": str(error), "rows": []}
        rows = []
        for payload in records:
            if not isinstance(payload, dict):
                rows.append({"status": "scartato", "detail": "il corpo deve essere un oggetto o un elenco"})
                continue
            try:
                rows.append(preview_row(pipeline, payload))
            except Exception as error:
                rows.append({"status": "scartato", "detail": str(error)})
        return {"rows": rows}
    config = stored_config(link["config_json"])
    if link["kind"] == "database":
        source = read_database(
            config,
            limit=5,
            cursor_column=pipeline["cursor_column"],
            cursor_value=load_cursor(pipeline_id) if pipeline["cursor_column"] else None,
            id_column=pipeline["external_id_field"] if pipeline["cursor_column"] else None,
        )
        payloads = source
    elif link["kind"] == "csv":
        payloads = [row for _path, row in read_csv_folder(link["id"])[:5]]
    elif link["kind"] in ("sftp", "ftps"):
        remote = open_remote(link["kind"], config)
        try:
            payloads = []
            for name in carico.remote_file_names(remote.names()):
                _headers, rows = carico.rows_from_bytes(name, remote.read(name))
                payloads.extend(rows)
                if len(payloads) >= 5:
                    payloads = payloads[:5]
                    break
        finally:
            remote.close()
    else:
        raise RuntimeError("questo collegamento non ha una prova a secco")
    rows = []
    for payload in payloads:
        try:
            rows.append(preview_row(pipeline, payload))
        except Exception as error:
            rows.append({"status": "scartato", "detail": str(error)})
    return {"rows": rows, "samples": column_samples(json.loads(pipeline["mapping_json"]), payloads)}


def note_rows(pipeline_id: str, rows: list[dict], counts: dict, hold: bool) -> set[str]:
    seen: set[str] = set()
    for row in rows:
        item = ingest_row(pipeline_id, row, hold=hold)
        if item.get("externalKey"):
            seen.add(item["externalKey"])
        tally(item, counts)
    return seen


def column_samples(mapping: list[dict], payloads: list[dict]) -> list[dict]:
    samples = []
    for rule in mapping:
        source = str(rule.get("from") or "")
        if not source or source.startswith("_"):
            continue
        kind = rule.get("kind")
        options = rule.get("options")
        field = rule.get("to") or source

        def interpret(raw, kind=kind, options=options, field=field):
            if not str(raw or "").strip() or kind not in ("date", "fiscale", "enum"):
                return raw
            return carico.check_quality(raw, kind, options, field)

        samples.append(carico.column_samples(
            payloads,
            source,
            interpret if kind in ("date", "fiscale", "enum") else None,
        ))
    return samples


def read_csv_file(path: Path) -> tuple[list[str], list[dict]]:
    header = path.read_text(encoding="utf-8-sig").splitlines()[:1]
    delimiter = csv_delimiter(header[0] if header else "")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        headers = [name.strip() for name in (reader.fieldnames or []) if name and str(name).strip()]
        rows = [{key: value for key, value in row.items() if key} for row in reader]
    return headers, rows


def settle_closes(pipeline: sqlite3.Row, seen: set[str], counts: dict, full: bool, hold: bool, preview: bool = False) -> None:
    if not full or pipeline["direction"] != "in":
        return
    with connect() as conn:
        known_rows = conn.execute(
            "SELECT external_key, espo_id FROM presenza WHERE pipeline_id = ?",
            (pipeline["id"],),
        ).fetchall()
    known = {row["external_key"] for row in known_rows}
    ids = {row["external_key"]: row["espo_id"] for row in known_rows}
    missing = carico.disappeared(known, seen)
    decision = carico.close_decision(
        missing,
        bool(pipeline["close_confirmed"]),
        bool(pipeline["close_field"]),
        bool(pipeline["cursor_column"]),
    )
    if decision["action"] == "conferma":
        if not preview:
            with connect() as conn:
                conn.execute("DELETE FROM pending_close WHERE pipeline_id = ?", (pipeline["id"],))
                for key in missing:
                    conn.execute(
                        "INSERT INTO pending_close (pipeline_id, external_key) VALUES (?, ?)",
                        (pipeline["id"], key),
                    )
        counts["confirm"] = True
        counts["wouldClose"] = len(missing)
        listed = ", ".join(missing[:8])
        counts["first"] = counts["first"] or f"{decision['reason']}: {listed}"
        return
    if decision["action"] == "salta" and decision["reason"] and missing:
        counts["first"] = counts["first"] or decision["reason"]
        return
    if decision["action"] != "chiudi":
        return
    if hold:
        counts["closed"] += len(missing)
        counts["held"] = True
        return
    field = pipeline["close_field"]
    value = pipeline["close_value"] or "Closed"
    for key in missing:
        espo_id = ids.get(key)
        if not espo_id:
            continue
        code, _result = espo_request("PUT", f"/api/v1/{pipeline['espo_entity']}/{espo_id}", {field: value})
        if code in (200, 201):
            counts["closed"] += 1
            with connect() as conn:
                conn.execute(
                    "DELETE FROM presenza WHERE pipeline_id = ? AND external_key = ?",
                    (pipeline["id"], key),
                )
        else:
            counts["failed"] += 1
            if not counts["first"]:
                counts["first"] = f"chiusura HTTP {code}"


def run_result(rows: int, counts: dict, status: str) -> dict:
    return {
        "rows": rows,
        "created": counts["created"],
        "updated": counts["updated"],
        "unchanged": counts["unchanged"],
        "failed": counts["failed"],
        "closed": counts["closed"],
        "status": status,
        "pericolose": counts["pericolose"],
    }


def note_stage(row, payload: dict) -> None:
    source = str(row["propose_from"] or "") if "propose_from" in row.keys() else ""
    entity = str(row["propose_entity"] or "") if "propose_entity" in row.keys() else ""
    field = str(row["propose_field"] or "stage") if "propose_field" in row.keys() else "stage"
    value = str(row["propose_value"] or "") if "propose_value" in row.keys() else ""
    offer_key = str(payload.get(source) or "").strip() if source else ""
    if not source or not entity or not value.strip() or not offer_key:
        return
    espo_id = offer_espo_id(entity, offer_key)
    current = ""
    if espo_id:
        code, record = espo_request("GET", f"/api/v1/{entity}/{espo_id}", query={"select": field})
        if code == 200 and isinstance(record, dict):
            current = record.get(field) or ""
    proposed = carico.stage_proposal(current, value)
    if not proposed:
        return
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO stage_proposal
            (pipeline_id, offer_key, entity, espo_id, field_name, proposed, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(pipeline_id, offer_key) DO UPDATE SET
                entity = excluded.entity,
                espo_id = excluded.espo_id,
                field_name = excluded.field_name,
                proposed = excluded.proposed,
                created_at = excluded.created_at
            """,
            (row["id"], offer_key, entity, espo_id or "", field, proposed, now),
        )


def offer_espo_id(entity: str, key: str) -> str:
    with connect() as conn:
        rows = conn.execute(
            "SELECT external_key, espo_id FROM chiave WHERE entity = ?",
            (entity,),
        ).fetchall()
    exact = [item for item in rows if item["external_key"] == key]
    if exact:
        return exact[0]["espo_id"]
    suffix = [item for item in rows if str(item["external_key"]).endswith(":" + key)]
    if len(suffix) == 1:
        return suffix[0]["espo_id"]
    return ""


def confirm_proposal(proposal_id: int) -> dict:
    with connect() as conn:
        item = conn.execute("SELECT * FROM stage_proposal WHERE id = ?", (proposal_id,)).fetchone()
    if item is None:
        raise RuntimeError("proposta non trovata")
    pipeline, _link = load_pipeline(item["pipeline_id"])
    held, reason = writes_held(pipeline)
    if held:
        raise RuntimeError(reason)
    if not item["espo_id"]:
        raise RuntimeError("l'offerta non è ancora in Espo")
    code, _result = espo_request(
        "PUT",
        f"/api/v1/{item['entity']}/{item['espo_id']}",
        {item["field_name"]: item["proposed"]},
    )
    if code not in (200, 201):
        raise RuntimeError(f"fase HTTP {code}")
    with connect() as conn:
        conn.execute("DELETE FROM stage_proposal WHERE id = ?", (proposal_id,))
    return {"confirmed": True, "id": proposal_id}


def leave_proposal(proposal_id: int) -> dict:
    with connect() as conn:
        found = conn.execute("SELECT id FROM stage_proposal WHERE id = ?", (proposal_id,)).fetchone()
        if found is None:
            raise RuntimeError("proposta non trovata")
        conn.execute("DELETE FROM stage_proposal WHERE id = ?", (proposal_id,))
    return {"left": True, "id": proposal_id}


def privacy_for(contact: str, company: str) -> dict:
    if not str(contact or "").strip() and not str(company or "").strip():
        raise RuntimeError("indica il contatto o l'azienda")
    with connect() as conn:
        found = conn.execute(
            """
            SELECT h.run_at AS at, p.espo_entity AS entity, pr.external_key AS external_key,
                   h.espo_id AS espo_id, h.field_name AS field, h.written_value AS value
            FROM field_history h
            JOIN pipeline p ON p.id = h.pipeline_id
            LEFT JOIN presenza pr ON pr.espo_id = h.espo_id AND pr.pipeline_id = h.pipeline_id
            """
        ).fetchall()
        kept = conn.execute("SELECT COUNT(*) AS n FROM field_history").fetchone()["n"]
    rows = carico.privacy_export([dict(item) for item in found], contact, company)
    return {"rows": rows, "kept": kept}


def account_keys() -> list[str]:
    found: list[str] = []
    with connect() as conn:
        for row in conn.execute("SELECT external_key FROM chiave WHERE entity = 'Account'"):
            key = str(row["external_key"] or "")
            found.append(key)
            if ":" in key:
                found.append(key.rsplit(":", 1)[-1])
        for row in conn.execute(
            """
            SELECT q.external_id FROM queue_item q
            JOIN pipeline p ON p.id = q.pipeline_id
            WHERE p.espo_entity = 'Account'
            """
        ):
            found.append(str(row["external_id"] or ""))
    return found


def account_id_for(key: str) -> str:
    with connect() as conn:
        exact = conn.execute(
            "SELECT espo_id FROM chiave WHERE entity = 'Account' AND external_key = ?",
            (key,),
        ).fetchone()
        if exact:
            return exact["espo_id"]
        rows = conn.execute(
            "SELECT external_key, espo_id FROM chiave WHERE entity = 'Account'"
        ).fetchall()
    hits = [item for item in rows if str(item["external_key"]).endswith(":" + key)]
    if len(hits) == 1:
        return hits[0]["espo_id"]
    return ""


def execute_pdf(pipeline, link, held: bool) -> dict:
    config = stored_config(link["config_json"])
    folder_name = str(config.get("documentFolder") or "").strip()
    team_name = str(config.get("team") or "").strip()
    folder = SCAMBIO / link["id"]
    folder.mkdir(parents=True, exist_ok=True)
    done = folder / "elaborati"
    done.mkdir(exist_ok=True)
    attached = 0
    waiting = 0
    keys = account_keys()
    for path in sorted(folder.glob("*.pdf")):
        matched = carico.match_pdf(path.name, keys)
        if not matched:
            waiting += 1
            continue
        if held:
            waiting += 1
            continue
        account_id = account_id_for(matched)
        if not account_id:
            waiting += 1
            continue
        body = {"name": path.stem, "accountsIds": [account_id]}
        if folder_name:
            folder_id = find_by_key("DocumentFolder", "name", folder_name)
            if not folder_id:
                waiting += 1
                continue
            body["folderId"] = folder_id
        if team_name:
            team_id = find_by_key("Team", "name", team_name)
            if not team_id:
                waiting += 1
                continue
            body["teamsIds"] = [team_id]
        body["fileId"] = upload_attachment(path)
        code, result = espo_request("POST", "/api/v1/Document", body)
        if code not in (200, 201) or not isinstance(result, dict) or not result.get("id"):
            waiting += 1
            continue
        path.rename(done / f"{time.strftime('%Y%m%d%H%M%S')}-{path.name}")
        attached += 1
    detail = f"{attached} pdf attaccati, {waiting} in attesa"
    status = "lettura" if held else "ok"
    mark_run(pipeline["id"], status, detail)
    return {"attached": attached, "waiting": waiting, "status": status, "detail": detail}


class RemoteDir:
    def names(self) -> list[str]:
        raise NotImplementedError

    def read(self, name: str) -> bytes:
        raise NotImplementedError

    def rename(self, name: str, dest: str) -> None:
        raise NotImplementedError

    def put(self, name: str, data: bytes) -> None:
        raise NotImplementedError

    def close(self) -> None:
        return None


class SftpDir(RemoteDir):
    def __init__(self, config: dict):
        import paramiko

        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(
            config["host"],
            port=int(config.get("port") or 22),
            username=config["user"],
            password=config.get("password") or "",
            timeout=8,
            allow_agent=False,
            look_for_keys=False,
        )
        self.sftp = self.client.open_sftp()
        self.sftp.chdir(str(config.get("path") or "."))

    def names(self) -> list[str]:
        return self.sftp.listdir()

    def read(self, name: str) -> bytes:
        with self.sftp.open(name, "rb") as handle:
            return handle.read()

    def rename(self, name: str, dest: str) -> None:
        folder = dest.rsplit("/", 1)[0] if "/" in dest else ""
        if folder:
            try:
                self.sftp.stat(folder)
            except OSError:
                self.sftp.mkdir(folder)
        self.sftp.rename(name, dest)

    def put(self, name: str, data: bytes) -> None:
        with self.sftp.open(name, "wb") as handle:
            handle.write(data)

    def close(self) -> None:
        try:
            self.sftp.close()
        finally:
            self.client.close()


class FtpsDir(RemoteDir):
    def __init__(self, config: dict):
        import ftplib

        self.ftp = ftplib.FTP_TLS()
        self.ftp.connect(config["host"], int(config.get("port") or 21), timeout=8)
        self.ftp.login(config["user"], config.get("password") or "")
        self.ftp.prot_p()
        self.ftp.cwd(str(config.get("path") or "."))

    def names(self) -> list[str]:
        return self.ftp.nlst()

    def read(self, name: str) -> bytes:
        chunks: list[bytes] = []
        self.ftp.retrbinary("RETR " + name, chunks.append)
        return b"".join(chunks)

    def rename(self, name: str, dest: str) -> None:
        folder = dest.rsplit("/", 1)[0] if "/" in dest else ""
        if folder:
            try:
                self.ftp.mkd(folder)
            except Exception:
                pass
        self.ftp.rename(name, dest)

    def put(self, name: str, data: bytes) -> None:
        import io

        self.ftp.storbinary("STOR " + name, io.BytesIO(data))

    def close(self) -> None:
        try:
            self.ftp.quit()
        except Exception:
            self.ftp.close()


def open_remote(kind: str, config: dict) -> RemoteDir:
    if kind == "sftp":
        return SftpDir(config)
    if kind == "ftps":
        return FtpsDir(config)
    raise RuntimeError("tipo di collegamento non riconosciuto")


def consume_tables(pipeline, pipeline_id: str, tables: list[tuple[str, list[str], list[dict]]], move, held: bool, prefix: str) -> dict:
    mapping = json.loads(pipeline["mapping_json"])
    required = carico.required_columns(
        pipeline["external_id_field"],
        mapping,
        key_column_list(pipeline)[1:],
    )
    counts = fresh_counts()
    seen: set[str] = set()
    taken = 0
    processed = 0
    read_rows: list[dict] = []
    for name, headers, file_rows in tables:
        missing = carico.missing_headers(headers, required)
        if missing:
            detail = "manca la colonna " + missing[0]
            remember_reject(pipeline_id, "", {"file": name}, detail)
            tally({"status": "scartato", "detail": detail}, counts)
            continue
        seen.update(note_rows(pipeline_id, file_rows, counts, held))
        read_rows.extend(file_rows)
        taken += len(file_rows)
        move(name)
        processed += 1
    settle_closes(pipeline, seen, counts, full=processed > 0 and not pipeline["cursor_column"], hold=held)
    status, detail = finish_counts(f"{taken} {prefix}", counts)
    mark_run(pipeline_id, status, detail, counts)
    if read_rows and not held:
        try:
            capture_balance(pipeline, read_rows)
        except Exception:
            pass
    return run_result(taken, counts, status)


def execute_remote_in(pipeline, kind: str, config: dict, held: bool) -> dict:
    remote = open_remote(kind, config)
    try:
        names = carico.remote_file_names(remote.names())
        tables = []
        for name in names:
            headers, rows = carico.rows_from_bytes(name, remote.read(name))
            tables.append((name, headers, rows))

        def move(name: str) -> None:
            remote.rename(name, f"elaborati/{time.strftime('%Y%m%d%H%M%S')}-{name}")

        return consume_tables(pipeline, pipeline["id"], tables, move, held, "righe dal file remoto")
    finally:
        remote.close()


def execute_remote_out(pipeline_id: str, kind: str, config: dict) -> dict:
    records = outbound_rows(pipeline_id)
    if not records:
        mark_run(pipeline_id, "ok", "0 record depositati")
        return {"sent": 0, "missingDate": False}
    remote = open_remote(kind, config)
    try:
        if records:
            name = f"nesso-{time.strftime('%Y%m%d%H%M%S')}.csv"
            remote.put(name, carico.csv_bytes([item["payload"] for item in records]))
        last = None
        for item in records:
            remember_sink(pipeline_id, item["espoId"], item["payload"])
            if item.get("espoId") or item.get("modifiedAt"):
                last = item
        missing_date = remember_outbound_cursor(pipeline_id, last) if last else False
    except Exception:
        remote.close()
        raise
    remote.close()
    detail = f"{len(records)} record depositati"
    if missing_date:
        detail += ". manca la data di modifica, il cursore segue l'id"
    mark_run(pipeline_id, "ok", detail)
    return {"sent": len(records), "missingDate": missing_date}


def write_source(pipeline: sqlite3.Row, link: sqlite3.Row, rows: list[dict]) -> int:
    if "write_back" not in pipeline.keys() or not int(pipeline["write_back"] or 0):
        return 0
    if link is None or link["kind"] != "database":
        return 0
    config = stored_config(link["config_json"])
    raw_fields = pipeline["write_fields"] or "[]"
    try:
        columns = json.loads(raw_fields)
    except json.JSONDecodeError:
        columns = []
    if not isinstance(columns, list):
        columns = []
    names = [str(item) for item in columns if str(item).strip()]
    sql = carico.write_back_sql(
        True,
        str(config.get("writeTable") or ""),
        pipeline["external_id_field"],
        names,
        str(config.get("engine") or "mysql"),
    )
    if not sql:
        raise RuntimeError("manca la tabella di ritorno")
    written = 0
    connection = open_sql(config)
    try:
        for row in rows:
            key = str(row.get(pipeline["external_id_field"]) or "")
            if not key:
                continue
            values = [row.get(name) for name in names]
            connection.cursor().execute(sql, (*values, key))
            written += 1
        connection.commit()
    finally:
        connection.close()
    return written


def execute_documento(pipeline: sqlite3.Row, link: sqlite3.Row, held: bool) -> dict:
    config = stored_config(link["config_json"])
    folder = SCAMBIO / link["id"]
    folder.mkdir(parents=True, exist_ok=True)
    done = folder / "elaborati"
    done.mkdir(exist_ok=True)
    taken = 0
    for path in sorted(folder.iterdir()):
        if not path.is_file():
            continue
        if held:
            taken += 1
            continue
        try:
            file_id = upload_attachment(path)
        except Exception as error:
            remember_reject(pipeline["id"], path.name, {"file": path.name}, str(error))
            continue
        code, result = espo_request(
            "POST",
            "/api/v1/Document",
            {
                "name": path.name,
                "fileId": file_id,
                "folderId": config.get("documentFolder") or None,
                "teamsIds": [config["team"]] if config.get("team") else [],
            },
        )
        if code not in (200, 201):
            remember_reject(pipeline["id"], path.name, {"file": path.name}, f"documento HTTP {code}")
            continue
        path.rename(done / f"{time.strftime('%Y%m%d%H%M%S')}-{path.name}")
        taken += 1
    status = "lettura" if held else "ok"
    mark_run(pipeline["id"], status, f"{taken} documenti")
    return {"taken": taken, "held": held}


def replay_reject(scarto_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM scarto WHERE id = ?", (scarto_id,)).fetchone()
    if row is None:
        raise KeyError(scarto_id)
    try:
        payload = json.loads(row["payload_json"])
    except json.JSONDecodeError:
        payload = {}
    try:
        result = ingest(row["pipeline_id"], payload if isinstance(payload, dict) else {})
    except Exception as error:
        with connect() as conn:
            conn.execute("UPDATE scarto SET detail = ?, resolved = 0 WHERE id = ?", (str(error)[:500], scarto_id))
        return {"status": "scartato", "detail": str(error)}
    with connect() as conn:
        conn.execute(
            "UPDATE scarto SET detail = ?, resolved = 1 WHERE id = ?",
            ("riuscita " + str(result.get("status") or ""), scarto_id),
        )
    return result


def rename_field(entity: str, name: str, label: str) -> dict:
    label = str(label or "").strip()
    if not label:
        raise RuntimeError("indica l'etichetta del campo")
    with connect() as conn:
        row = conn.execute(
            "SELECT name FROM sheet_field WHERE entity = ? AND name = ?",
            (entity, name),
        ).fetchone()
    if row is None:
        raise RuntimeError("questo campo non l'ha creato Nesso")
    status, result = espo_request("PUT", f"/api/v1/Admin/fieldManager/{entity}/{name}", {"label": label})
    if status not in (200, 201):
        raise RuntimeError(f"{entity}.{name}: HTTP {status}")
    with connect() as conn:
        conn.execute("UPDATE sheet_field SET label = ? WHERE entity = ? AND name = ?", (label, entity, name))
    return {"name": name, "label": label}


def remember_version(pipeline_id: str, mapping: list, author: str) -> None:
    raw = json.dumps(mapping, ensure_ascii=False)
    with connect() as conn:
        previous = conn.execute(
            "SELECT mapping_json FROM mapping_version WHERE pipeline_id = ? ORDER BY id DESC LIMIT 1",
            (pipeline_id,),
        ).fetchone()
        if previous is not None and previous["mapping_json"] == raw:
            return
        conn.execute(
            "INSERT INTO mapping_version (pipeline_id, mapping_json, author, saved_at) VALUES (?, ?, ?, ?)",
            (pipeline_id, raw, author or "", time.strftime("%Y-%m-%d %H:%M:%S")),
        )


def mapping_versions(pipeline_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, author, saved_at FROM mapping_version WHERE pipeline_id = ? ORDER BY id DESC",
            (pipeline_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def restore_version(pipeline_id: str, version_id: int, author: str = "") -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT mapping_json FROM mapping_version WHERE id = ? AND pipeline_id = ?",
            (version_id, pipeline_id),
        ).fetchone()
        current = conn.execute("SELECT * FROM pipeline WHERE id = ?", (pipeline_id,)).fetchone()
    if row is None or current is None:
        raise KeyError(version_id)
    body = {
        "id": pipeline_id,
        "name": current["name"],
        "direction": current["direction"],
        "espoEntity": current["espo_entity"],
        "externalIdField": current["external_id_field"],
        "connectionId": current["connection_id"],
        "mapping": json.loads(row["mapping_json"]),
        "author": author,
    }
    return save_pipeline(body)


def passaggio_config() -> dict:
    data = export_config()
    data["passaggio"] = True
    data["ambiente"] = setting_value("ambiente") or "prova"
    for item in data.get("connections") or []:
        config = dict(item.get("config") or {})
        for key in ("host", "url", "tokenUrl", "tunnelHost"):
            if config.get(key):
                config[key] = ""
        for key in ("password", "token", "headerValue", "clientSecret", "signSecret", "accessToken", "refreshToken", "tunnelPassword"):
            config.pop(key, None)
            config.pop("has" + key[:1].upper() + key[1:], None)
        item["config"] = config
    return data


def execute_pipeline(pipeline_id: str) -> dict:
    with connect() as conn:
        pipeline = conn.execute("SELECT * FROM pipeline WHERE id = ?", (pipeline_id,)).fetchone()
        link = None
        if pipeline and pipeline["connection_id"]:
            link = conn.execute(
                "SELECT * FROM connection WHERE id = ?",
                (pipeline["connection_id"],),
            ).fetchone()
    if pipeline is None:
        raise KeyError(pipeline_id)
    if link is None:
        if pipeline["direction"] == "out":
            result = pull(pipeline_id)
            detail = f"letti {result['exported']} record, senza destinazione"
            if result.get("missingDate"):
                detail += ". manca la data di modifica, il cursore segue l'id"
            mark_run(pipeline_id, "ok", detail)
            return result
        raise RuntimeError("collega un sistema esterno prima di eseguire")
    config = stored_config(link["config_json"])
    if link["kind"] == "webhook":
        mark_run(pipeline_id, "ok", "in attesa che il sistema esterno chiami l'indirizzo")
        return {"waiting": True, "url": f"{PUBLIC_BASE}/hook/{link['id']}/{link['token']}"}
    held = writes_held(pipeline)[0]
    if link["kind"] == "database":
        rows = read_database(
            config,
            cursor_column=pipeline["cursor_column"],
            cursor_value=load_cursor(pipeline_id) if pipeline["cursor_column"] else None,
            id_column=pipeline["external_id_field"] if pipeline["cursor_column"] else None,
        )
        counts = fresh_counts()
        seen = note_rows(pipeline_id, rows, counts, held)
        if pipeline["cursor_column"] and rows and not held:
            last = rows[-1]
            stamp = str(last.get(pipeline["cursor_column"]) or "")
            identity = external_of(pipeline, last)
            if stamp:
                save_cursor(pipeline_id, stamp, identity)
        settle_closes(pipeline, seen, counts, full=not pipeline["cursor_column"], hold=held)
        status, detail = finish_counts(f"{len(rows)} righe dal database", counts)
        if "write_back" in pipeline.keys() and int(pipeline["write_back"] or 0):
            try:
                write_source(pipeline, link, rows)
            except Exception as error:
                status = "errore"
                detail = detail + ". " + str(error)
        mark_run(pipeline_id, status, detail, counts)
        return run_result(len(rows), counts, status)
    if link["kind"] == "csv":
        mapping = json.loads(pipeline["mapping_json"])
        required = carico.required_columns(
            pipeline["external_id_field"],
            mapping,
            key_column_list(pipeline)[1:],
        )
        folder = SCAMBIO / link["id"]
        folder.mkdir(parents=True, exist_ok=True)
        done = folder / "elaborati"
        done.mkdir(exist_ok=True)
        counts = fresh_counts()
        seen: set[str] = set()
        taken = 0
        processed = 0
        read_rows: list[dict] = []
        for path in sheet_paths(folder):
            headers, file_rows = read_table(path)
            missing = carico.missing_headers(headers, required)
            if missing:
                detail = "manca la colonna " + missing[0]
                remember_reject(pipeline_id, "", {"file": path.name}, detail)
                tally({"status": "scartato", "detail": detail}, counts)
                continue
            seen.update(note_rows(pipeline_id, file_rows, counts, held))
            read_rows.extend(file_rows)
            taken += len(file_rows)
            path.rename(done / f"{time.strftime('%Y%m%d%H%M%S')}-{path.name}")
            processed += 1
        settle_closes(pipeline, seen, counts, full=processed > 0 and not pipeline["cursor_column"], hold=held)
        status, detail = finish_counts(f"{taken} righe dai file CSV", counts)
        mark_run(pipeline_id, status, detail, counts)
        if read_rows and not held:
            try:
                capture_balance(pipeline, read_rows)
            except Exception:
                pass
        return run_result(taken, counts, status)
    if link["kind"] == "pdf":
        return execute_pdf(pipeline, link, held)
    if link["kind"] == "documento":
        return execute_documento(pipeline, link, held)
    if link["kind"] == "http":
        records = outbound_rows(pipeline_id)
        url = str(config.get("url") or "").strip() or f"http://127.0.0.1:{PORT}/inbox/{link['id']}/{link['token']}"
        sent = 0
        failed = ""
        last = None
        headers = outbound_headers(link["id"], config) if records else {}
        for item in records:
            if item.get("missingKey"):
                failed = "manca la chiave esterna di " + item["missingKey"]
                remember_delivery(pipeline_id, link["id"], item["payload"], "errore", failed)
                remember_reject(pipeline_id, item["espoId"] or "", item["payload"], failed)
                break
            try:
                post_json(url, item["payload"], headers)
            except Exception as error:
                failed = str(error)
                remember_delivery(pipeline_id, link["id"], item["payload"], "errore", failed)
                remember_reject(pipeline_id, item["espoId"] or "", item["payload"], failed)
                break
            remember_delivery(pipeline_id, link["id"], item["payload"], "inviato", url)
            remember_sink(pipeline_id, item["espoId"], item["payload"])
            last = item
            sent += 1
        missing_date = remember_outbound_cursor(pipeline_id, last) if last else False
        detail = f"{sent} record inviati a {url}"
        if missing_date:
            detail += ". manca la data di modifica, il cursore segue l'id"
        if failed:
            detail += ". " + failed
        mark_run(pipeline_id, "errore" if failed else "ok", detail)
        return {"sent": sent, "url": url, "failed": bool(failed)}
    if link["kind"] in ("sftp", "ftps"):
        if pipeline["direction"] == "out":
            return execute_remote_out(pipeline_id, link["kind"], config)
        return execute_remote_in(pipeline, link["kind"], config, held)
    raise RuntimeError("tipo di collegamento non gestito")


def execute_chain(pipeline_id: str, seen: set[str], with_dependencies: bool) -> dict:
    if pipeline_id in seen:
        raise RuntimeError("le integrazioni si aspettano in cerchio")
    seen.add(pipeline_id)
    lock = pipeline_lock(pipeline_id)
    if not lock.acquire(blocking=False):
        raise RuntimeError("un'esecuzione è già in corso")
    try:
        return _execute_chain(pipeline_id, seen, with_dependencies)
    finally:
        lock.release()


def _execute_chain(pipeline_id: str, seen: set[str], with_dependencies: bool) -> dict:
    with connect() as conn:
        pipeline = conn.execute("SELECT * FROM pipeline WHERE id = ?", (pipeline_id,)).fetchone()
    if pipeline is None:
        raise KeyError(pipeline_id)
    extra = []
    if "depends_json" in pipeline.keys() and pipeline["depends_json"]:
        try:
            parsed = json.loads(pipeline["depends_json"])
        except json.JSONDecodeError:
            parsed = []
        if isinstance(parsed, list):
            extra = [str(item) for item in parsed if str(item).strip()]
    if len(extra) > 1:
        blocked = []
        for parent_id in extra:
            with connect() as conn:
                parent_row = conn.execute("SELECT * FROM pipeline WHERE id = ?", (parent_id,)).fetchone()
            label = parent_row["name"] if parent_row else parent_id
            if parent_row is None or carico.blocked_parent(parent_row["enabled"], parent_row["last_status"]):
                blocked.append(label)
                continue
            if parent_row["last_status"] != "ok":
                try:
                    execute_chain(parent_id, seen, True)
                except Exception:
                    blocked.append(label)
                    continue
                with connect() as conn:
                    again = conn.execute("SELECT last_status FROM pipeline WHERE id = ?", (parent_id,)).fetchone()
                if again is None or again["last_status"] != "ok":
                    blocked.append(label)
        if blocked:
            detail = "manca " + blocked[0]
            mark_run(pipeline_id, "errore", detail)
            return {"waiting": True, "missing": blocked, "detail": detail}
        return execute_pipeline(pipeline_id)
    parent = pipeline["depends_on"]
    if parent:
        run_parent = with_dependencies
        if not run_parent:
            with connect() as conn:
                parent_row = conn.execute("SELECT * FROM pipeline WHERE id = ?", (parent,)).fetchone()
            run_parent = parent_row is not None and pipeline_due(parent_row)
        if run_parent:
            try:
                execute_chain(parent, seen, with_dependencies)
            except Exception as error:
                print("[motore] dipendenza", parent, error)
    return execute_pipeline(pipeline_id)


def run_pipeline(pipeline_id: str, with_dependencies: bool = False) -> dict:
    with connect() as conn:
        exists = conn.execute("SELECT 1 FROM pipeline WHERE id = ?", (pipeline_id,)).fetchone()
    if exists is not None:
        decision = silence_for(pipeline_id)
        if decision["action"] != "scrivi":
            if decision["action"] == "attesa":
                note_silence(pipeline_id, decision.get("reason") or "")
            return silence_reply(decision)
    lock = pipeline_lock(pipeline_id)
    if not lock.acquire(blocking=False):
        raise RuntimeError("un'esecuzione è già in corso")
    try:
        return execute_chain(pipeline_id, set(), with_dependencies)
    except Exception as error:
        mark_run(pipeline_id, "errore", str(error))
        raise
    finally:
        lock.release()


def load_pipeline(pipeline_id: str) -> tuple:
    with connect() as conn:
        pipeline = conn.execute("SELECT * FROM pipeline WHERE id = ?", (pipeline_id,)).fetchone()
        link = None
        if pipeline and pipeline["connection_id"]:
            link = conn.execute("SELECT * FROM connection WHERE id = ?", (pipeline["connection_id"],)).fetchone()
    if pipeline is None:
        raise KeyError(pipeline_id)
    return pipeline, link


def anteprima(pipeline_id: str) -> dict:
    pipeline, link = load_pipeline(pipeline_id)
    if link is None or link["kind"] == "webhook":
        with connect() as conn:
            conn.execute("UPDATE plan_step SET previewed = 1 WHERE pipeline_id = ?", (pipeline_id,))
        return {
            "detail": "Il webhook non ha righe da leggere. L'anteprima si fa quando il sistema esterno chiama.",
            "created": 0, "updated": 0, "closed": 0, "failed": 0, "unchanged": 0, "pericolose": [],
        }
    config = stored_config(link["config_json"])
    counts = fresh_counts()
    seen: set[str] = set()
    full = False
    if link["kind"] == "database":
        rows = read_database(
            config,
            cursor_column=pipeline["cursor_column"],
            cursor_value=load_cursor(pipeline_id) if pipeline["cursor_column"] else None,
            id_column=pipeline["external_id_field"] if pipeline["cursor_column"] else None,
        )
        seen = note_rows(pipeline_id, rows, counts, True)
        full = not pipeline["cursor_column"]
        taken = len(rows)
    elif link["kind"] == "csv":
        required = carico.required_columns(
            pipeline["external_id_field"],
            json.loads(pipeline["mapping_json"]),
            key_column_list(pipeline)[1:],
        )
        folder = SCAMBIO / link["id"]
        taken = 0
        processed = 0
        if folder.is_dir():
            for path in sorted(folder.glob("*.csv")):
                headers, file_rows = read_csv_file(path)
                missing = carico.missing_headers(headers, required)
                if missing:
                    tally({"status": "scartato", "detail": "manca la colonna " + missing[0]}, counts)
                    continue
                seen.update(note_rows(pipeline_id, file_rows, counts, True))
                taken += len(file_rows)
                processed += 1
        full = processed > 0 and not pipeline["cursor_column"]
    else:
        raise RuntimeError("questo collegamento non ha un'anteprima")
    settle_closes(pipeline, seen, counts, full=full, hold=True, preview=True)
    with connect() as conn:
        conn.execute("UPDATE plan_step SET previewed = 1 WHERE pipeline_id = ?", (pipeline_id,))
    _status, detail = finish_counts(f"{taken} righe in anteprima", counts)
    return {
        "detail": detail,
        "created": counts["created"],
        "updated": counts["updated"],
        "closed": counts.get("wouldClose", counts["closed"]),
        "unchanged": counts["unchanged"],
        "failed": counts["failed"],
        "pericolose": counts["pericolose"],
        "confirm": counts["confirm"],
    }


def set_read_mode(pipeline_id: str, enabled: bool, hours: int = 48) -> dict:
    load_pipeline(pipeline_id)
    with connect() as conn:
        if not enabled:
            conn.execute("UPDATE pipeline SET read_only = 0, read_until = NULL WHERE id = ?", (pipeline_id,))
            return {"id": pipeline_id, "readOnly": False}
        until = carico.read_deadline(int(hours or 48), datetime.now())
        conn.execute(
            "UPDATE pipeline SET read_only = 1, read_until = ? WHERE id = ?",
            (until, pipeline_id),
        )
    return {"id": pipeline_id, "readOnly": True, "until": until}


def undo_last(pipeline_id: str) -> dict:
    pipeline, _link = load_pipeline(pipeline_id)
    held, reason = writes_held(pipeline)
    if held:
        raise RuntimeError(reason)
    with connect() as conn:
        latest = conn.execute(
            "SELECT run_at FROM field_history WHERE pipeline_id = ? ORDER BY id DESC LIMIT 1",
            (pipeline_id,),
        ).fetchone()
        rows = []
        if latest:
            rows = conn.execute(
                "SELECT * FROM field_history WHERE pipeline_id = ? AND run_at = ?",
                (pipeline_id, latest["run_at"]),
            ).fetchall()
    if not rows:
        raise RuntimeError("non c'è un giro da annullare")
    restored = 0
    kept = 0
    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(row["espo_id"], []).append(row)
    for espo_id, fields in grouped.items():
        names = [field["field_name"] for field in fields]
        current = record_fields(pipeline["espo_entity"], espo_id, names)
        body = {}
        for field in fields:
            if carico.restorable(field["previous_value"] or "", field["written_value"] or "", current.get(field["field_name"])):
                body[field["field_name"]] = field["previous_value"] or ""
            else:
                kept += 1
        if not body:
            continue
        code, _result = espo_request("PUT", f"/api/v1/{pipeline['espo_entity']}/{espo_id}", body)
        if code not in (200, 201):
            raise RuntimeError(f"annullamento HTTP {code}")
        restored += len(body)
    return {"restored": restored, "kept": kept}


def confirm_closes(pipeline_id: str) -> dict:
    pipeline, _link = load_pipeline(pipeline_id)
    held, reason = writes_held(pipeline)
    if held:
        raise RuntimeError(reason)
    if not pipeline["close_field"]:
        raise RuntimeError("la scheda non ha uno stato di chiusura")
    with connect() as conn:
        pending = conn.execute(
            "SELECT external_key FROM pending_close WHERE pipeline_id = ?",
            (pipeline_id,),
        ).fetchall()
        conn.execute("UPDATE pipeline SET close_confirmed = 1 WHERE id = ?", (pipeline_id,))
    closed = 0
    field = pipeline["close_field"]
    value = pipeline["close_value"] or "Closed"
    for row in pending:
        with connect() as conn:
            found = conn.execute(
                "SELECT espo_id FROM presenza WHERE pipeline_id = ? AND external_key = ?",
                (pipeline_id, row["external_key"]),
            ).fetchone()
        if found is None:
            continue
        code, _result = espo_request(
            "PUT",
            f"/api/v1/{pipeline['espo_entity']}/{found['espo_id']}",
            {field: value},
        )
        if code not in (200, 201):
            raise RuntimeError(f"chiusura HTTP {code}")
        closed += 1
        with connect() as conn:
            conn.execute(
                "DELETE FROM presenza WHERE pipeline_id = ? AND external_key = ?",
                (pipeline_id, row["external_key"]),
            )
    with connect() as conn:
        conn.execute("DELETE FROM pending_close WHERE pipeline_id = ?", (pipeline_id,))
    return {"closed": closed}


def connection_sample(connection_id: str) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM connection WHERE id = ?", (connection_id,)).fetchone()
    if row is None:
        raise KeyError(connection_id)
    if row["kind"] == "csv":
        folder = SCAMBIO / connection_id
        if not folder.is_dir():
            return {"rows": []}
        for path in sorted(folder.glob("*.csv")):
            _headers, rows = read_csv_file(path)
            return {"rows": rows[:3]}
        return {"rows": []}
    if row["kind"] == "database":
        return {"rows": read_database(stored_config(row["config_json"]), limit=3)}
    return {"rows": []}


def resolve_watch(watch_id: int, keep: str) -> dict:
    if keep not in ("espo", "sorgente"):
        raise RuntimeError("si tiene il valore di Espo oppure quello in arrivo")
    with connect() as conn:
        row = conn.execute("SELECT * FROM watch_item WHERE id = ?", (watch_id,)).fetchone()
    if row is None:
        raise KeyError(watch_id)
    pipeline, _link = load_pipeline(row["pipeline_id"])
    if keep == "sorgente":
        held, reason = writes_held(pipeline)
        if held:
            raise RuntimeError(reason)
        with connect() as conn:
            found = conn.execute(
                "SELECT espo_id FROM queue_item WHERE pipeline_id = ? AND external_id = ?",
                (row["pipeline_id"], row["external_id"]),
            ).fetchone()
        if found is None or not found["espo_id"]:
            raise RuntimeError("il record non è ancora in Espo")
        code, _result = espo_request(
            "PUT",
            f"/api/v1/{pipeline['espo_entity']}/{found['espo_id']}",
            {row["field_name"]: row["incoming_value"]},
        )
        if code not in (200, 201):
            raise RuntimeError(f"scrittura HTTP {code}")
    with connect() as conn:
        conn.execute("DELETE FROM watch_item WHERE id = ?", (watch_id,))
    return {"id": watch_id, "kept": keep}


def silence_windows_of(pipeline_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT start_on, end_on, reason FROM silence_window
            WHERE pipeline_id IS NULL OR pipeline_id = '' OR pipeline_id = ?
            """,
            (pipeline_id,),
        ).fetchall()
    return [{"start": row["start_on"], "end": row["end_on"], "reason": row["reason"]} for row in rows]


def silence_for(pipeline_id: str, now: datetime | None = None) -> dict:
    moment = now or datetime.now()
    with connect() as conn:
        row = conn.execute("SELECT silence_held FROM pipeline WHERE id = ?", (pipeline_id,)).fetchone()
    if row is None:
        raise KeyError(pipeline_id)
    held = bool(row["silence_held"]) if "silence_held" in row.keys() else False
    return carico.silence_decision(moment.strftime("%Y-%m-%d"), silence_windows_of(pipeline_id), held)


def source_waiting(pipeline_id: str) -> bool:
    with connect() as conn:
        pipeline = conn.execute("SELECT connection_id FROM pipeline WHERE id = ?", (pipeline_id,)).fetchone()
        if pipeline is None:
            return False
        queued = conn.execute(
            "SELECT 1 FROM silence_payload WHERE pipeline_id = ? LIMIT 1",
            (pipeline_id,),
        ).fetchone()
        link = None
        if pipeline["connection_id"]:
            link = conn.execute(
                "SELECT kind FROM connection WHERE id = ?",
                (pipeline["connection_id"],),
            ).fetchone()
    if queued:
        return True
    if link is None:
        return False
    if link["kind"] == "csv":
        return folder_has_csv(pipeline["connection_id"])
    return link["kind"] == "database"


def note_silence(pipeline_id: str, reason: str, now: datetime | None = None) -> None:
    if not source_waiting(pipeline_id):
        return
    moment = now or datetime.now()
    stamp = moment.strftime("%Y-%m-%d %H:%M:%S")
    detail = f"finestra di silenzio: {reason}" if reason else "finestra di silenzio"
    with connect() as conn:
        conn.execute("UPDATE pipeline SET silence_held = 1 WHERE id = ?", (pipeline_id,))
        already = conn.execute(
            """
            SELECT 1 FROM run_log
            WHERE pipeline_id = ? AND status = 'attesa' AND created_at LIKE ?
            """,
            (pipeline_id, stamp[:10] + "%"),
        ).fetchone()
        if already is None:
            conn.execute(
                "UPDATE pipeline SET last_run = ?, last_status = ?, last_detail = ? WHERE id = ?",
                (stamp, "attesa", detail[:500], pipeline_id),
            )
            conn.execute(
                "INSERT INTO run_log (pipeline_id, status, detail, created_at) VALUES (?, 'attesa', ?, ?)",
                (pipeline_id, detail[:500], stamp),
            )


def park_silence(pipeline_id: str, payload: dict, reason: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO silence_payload (pipeline_id, payload_json, created_at)
            VALUES (?, ?, ?)
            """,
            (pipeline_id, json.dumps(payload, ensure_ascii=False), time.strftime("%Y-%m-%d %H:%M:%S")),
        )
    note_silence(pipeline_id, reason)


def silence_reply(decision: dict) -> dict:
    if decision["action"] == "fermo":
        return {
            "silence": "fermo",
            "detail": "la finestra è finita e il file è in attesa",
            "textKey": "La finestra è finita e il file è in attesa. Conferma il file oppure scartalo.",
            "textParams": {},
        }
    reason = decision.get("reason") or "silenzio"
    return {
        "silence": "attesa",
        "detail": f"finestra di silenzio: {reason}",
        "textKey": "Finestra di silenzio: {motivo}. Il file resta in attesa.",
        "textParams": {"motivo": reason},
    }


def save_silence(body: dict) -> dict:
    start = carico.parse_day(body.get("start"))
    end = carico.parse_day(body.get("end"))
    if end < start:
        raise RuntimeError("la finestra finisce prima di iniziare")
    reason = str(body.get("reason") or "").strip()
    if not reason:
        raise RuntimeError("indica il motivo della finestra")
    pipeline_id = str(body.get("pipelineId") or "").strip() or None
    if pipeline_id:
        load_pipeline(pipeline_id)
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO silence_window (pipeline_id, start_on, end_on, reason) VALUES (?, ?, ?, ?)",
            (pipeline_id, start, end, reason[:180]),
        )
        number = cursor.lastrowid
    return {"id": number, "pipelineId": pipeline_id, "start": start, "end": end, "reason": reason[:180]}


def delete_silence(number: int) -> dict:
    with connect() as conn:
        deleted = conn.execute("DELETE FROM silence_window WHERE id = ?", (number,)).rowcount
    if not deleted:
        raise RuntimeError("finestra non trovata")
    return {"deleted": number}


def confirm_silence(pipeline_id: str) -> dict:
    pipeline, link = load_pipeline(pipeline_id)
    if silence_for(pipeline_id)["action"] == "attesa":
        raise RuntimeError("la finestra di silenzio è ancora aperta")
    if not pipeline["silence_held"]:
        raise RuntimeError("non c'è un file in attesa")
    with connect() as conn:
        payloads = conn.execute(
            "SELECT id, payload_json FROM silence_payload WHERE pipeline_id = ? ORDER BY id",
            (pipeline_id,),
        ).fetchall()
        conn.execute("UPDATE pipeline SET silence_held = 0 WHERE id = ?", (pipeline_id,))
    replayed = 0
    for item in payloads:
        ingest(pipeline_id, json.loads(item["payload_json"]))
        with connect() as conn:
            conn.execute("DELETE FROM silence_payload WHERE id = ?", (item["id"],))
        replayed += 1
    kind = link["kind"] if link is not None else ""
    if kind in ("csv", "database"):
        result = run_pipeline(pipeline_id)
        result["replayed"] = replayed
        return result
    return {"replayed": replayed}


def discard_silence(pipeline_id: str) -> dict:
    pipeline, link = load_pipeline(pipeline_id)
    if not pipeline["silence_held"]:
        raise RuntimeError("non c'è un file in attesa")
    moved = 0
    if link is not None and link["kind"] == "csv":
        folder = SCAMBIO / link["id"]
        side = folder / "scartati"
        side.mkdir(parents=True, exist_ok=True)
        for path in sorted(folder.glob("*.csv")):
            path.rename(side / f"{time.strftime('%Y%m%d%H%M%S')}-{path.name}")
            moved += 1
    with connect() as conn:
        dropped = conn.execute("DELETE FROM silence_payload WHERE pipeline_id = ?", (pipeline_id,)).rowcount
        conn.execute("UPDATE pipeline SET silence_held = 0 WHERE id = ?", (pipeline_id,))
    mark_run(pipeline_id, "sospeso", "file in attesa scartato, senza scrivere")
    return {"discarded": moved, "payloads": dropped}


def plan_block(pipeline_id: str) -> str:
    with connect() as conn:
        step = conn.execute("SELECT * FROM plan_step WHERE pipeline_id = ?", (pipeline_id,)).fetchone()
        if step is None:
            return ""
        earlier = conn.execute(
            "SELECT confirmed FROM plan_step WHERE plan_id = ? AND position = ?",
            (step["plan_id"], step["position"] - 1),
        ).fetchone()
    allowed, reason = carico.step_may_enable(True, step["position"], bool(earlier and earlier["confirmed"]))
    return "" if allowed else reason


def save_plan(body: dict) -> dict:
    raw = body.get("steps") if isinstance(body, dict) else None
    if not isinstance(raw, list):
        raise RuntimeError("il piano ha almeno un gradino")
    steps: list[str] = []
    for item in raw:
        pipeline_id = str(item or "").strip()
        if not pipeline_id or pipeline_id in steps:
            continue
        load_pipeline(pipeline_id)
        steps.append(pipeline_id)
    with connect() as conn:
        if not steps:
            conn.execute("DELETE FROM plan_step")
            return {"id": "accensione", "steps": []}
        conn.execute("DELETE FROM plan_step")
        for index, pipeline_id in enumerate(steps, start=1):
            conn.execute(
                """
                INSERT INTO plan_step (pipeline_id, plan_id, position, confirmed, previewed)
                VALUES (?, 'accensione', ?, 0, 0)
                """,
                (pipeline_id, index),
            )
    return {"id": "accensione", "steps": steps}


def confirm_step(pipeline_id: str) -> dict:
    with connect() as conn:
        step = conn.execute("SELECT * FROM plan_step WHERE pipeline_id = ?", (pipeline_id,)).fetchone()
        allowed, reason = carico.step_may_confirm(step is not None, bool(step and step["previewed"]))
        if not allowed:
            raise RuntimeError(reason)
        conn.execute("UPDATE plan_step SET confirmed = 1 WHERE pipeline_id = ?", (pipeline_id,))
        following = conn.execute(
            """
            SELECT pipeline.enabled
            FROM plan_step
            JOIN pipeline ON pipeline.id = plan_step.pipeline_id
            WHERE plan_step.plan_id = ? AND plan_step.position = ?
            """,
            (step["plan_id"], step["position"] + 1),
        ).fetchone()
    return {
        "id": pipeline_id,
        "confirmed": True,
        "nextEnabled": None if following is None else bool(following["enabled"]),
    }


def set_enabled(pipeline_id: str, enabled: bool) -> dict:
    with connect() as conn:
        found = conn.execute("SELECT id, enabled FROM pipeline WHERE id = ?", (pipeline_id,)).fetchone()
        if found is None:
            raise KeyError(pipeline_id)
        current = int(found["enabled"] or 0)
    if enabled and not current:
        blocked = plan_block(pipeline_id)
        if blocked:
            raise RuntimeError(blocked)
    with connect() as conn:
        conn.execute("UPDATE pipeline SET enabled = ? WHERE id = ?", (1 if enabled else 0, pipeline_id))
    try:
        sync_service_role()
    except Exception as error:
        print("[motore] ruolo Nesso", error)
    return {"id": pipeline_id, "enabled": bool(enabled)}


def consegna_view() -> dict:
    current = snapshot()
    return carico.consegna(
        current.get("publicBase") or "",
        current.get("espoPublicUrl") or "",
        current.get("writesEnabled"),
        current.get("pipelines") or [],
        current.get("connections") or [],
        current.get("silence") or [],
    )


def sheet_export() -> str:
    return carico.sheet_csv(snapshot().get("pipelines") or [], frasi.lingua_corrente())


def import_sheet(text: str) -> dict:
    rows = carico.parse_sheet(text)
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        pipeline_id = str(row.get("pipeline") or "").strip()
        if not pipeline_id:
            raise RuntimeError("manca l'integrazione nel foglio")
        grouped.setdefault(pipeline_id, []).append(row)
    updated = 0
    with connect() as conn:
        for pipeline_id, group in grouped.items():
            current = conn.execute(
                "SELECT mapping_json, direction FROM pipeline WHERE id = ?",
                (pipeline_id,),
            ).fetchone()
            if current is None:
                raise RuntimeError(f"integrazione non trovata {pipeline_id}")
            if current["direction"] != "in":
                raise RuntimeError("il foglio vale per le integrazioni in ingresso")
            mapping = json.loads(current["mapping_json"])
            revised = carico.apply_sheet(mapping, group)
            conn.execute(
                "UPDATE pipeline SET mapping_json = ? WHERE id = ?",
                (json.dumps(revised, ensure_ascii=False), pipeline_id),
            )
            updated += 1
    return {"pipelines": updated, "rows": len(rows)}


def export_config() -> dict:
    current = snapshot()
    pipelines = []
    for item in current["pipelines"]:
        pipelines.append({
            "id": item["id"],
            "name": item["name"],
            "direction": item["direction"],
            "espoEntity": item["espo_entity"],
            "externalIdField": item["external_id_field"],
            "keyTemplate": item["key_template"],
            "keyField": item["key_field"],
            "connectionId": item["connection_id"],
            "scheduleMinutes": item["schedule_minutes"],
            "dependsOn": item.get("depends_on"),
            "cursorColumn": item.get("cursor_column"),
            "enabled": item.get("enabled", 1),
            "onDuplicate": item.get("on_duplicate") or "fail",
            "scheduleAt": item.get("schedule_at") or "",
            "expectAt": item.get("expect_at") or "",
            "keyColumns": item.get("keyColumns") or [],
            "mapping": item["mapping"],
        })
    return {"connections": current["connections"], "pipelines": pipelines}


def import_config(body: dict) -> dict:
    if not isinstance(body, dict):
        raise RuntimeError("il file non è una configurazione")
    if body.get("passaggio"):
        holes = carico.passaggio_holes(body.get("connections") or [])
        return {"passaggio": True, "mancano": holes, "salvate": 0}
    saved_connections = 0
    for item in body.get("connections") or []:
        if not isinstance(item, dict):
            continue
        save_connection({
            "id": item.get("id"),
            "name": item.get("name"),
            "kind": item.get("kind"),
            "config": item.get("config") or {},
        })
        saved_connections += 1
    saved_pipelines = 0
    for item in body.get("pipelines") or []:
        if not isinstance(item, dict) or not item.get("id") or not item.get("mapping"):
            continue
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO pipeline
                (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field, connection_id, schedule_minutes, depends_on, cursor_column, enabled, on_duplicate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    direction = excluded.direction,
                    espo_entity = excluded.espo_entity,
                    external_id_field = excluded.external_id_field,
                    key_template = excluded.key_template,
                    mapping_json = excluded.mapping_json,
                    key_field = excluded.key_field,
                    connection_id = excluded.connection_id,
                    schedule_minutes = excluded.schedule_minutes,
                    depends_on = excluded.depends_on,
                    cursor_column = excluded.cursor_column,
                    enabled = excluded.enabled,
                    on_duplicate = excluded.on_duplicate
                """,
                (
                    item["id"], item.get("name") or item["id"], item.get("direction") or "in",
                    item.get("espoEntity") or "", item.get("externalIdField") or "",
                    item.get("keyTemplate") or "", json.dumps(item["mapping"], ensure_ascii=False),
                    item.get("keyField") or "cExternalKey", item.get("connectionId"),
                    int(item.get("scheduleMinutes") or 0), item.get("dependsOn"),
                    item.get("cursorColumn"), 0 if item.get("enabled") in (False, 0, "0") else 1,
                    item.get("onDuplicate") or "fail",
                ),
            )
            if isinstance(item.get("keyColumns"), list) and len(item.get("keyColumns") or []) >= 2:
                conn.execute(
                    "UPDATE pipeline SET key_columns = ? WHERE id = ?",
                    (json.dumps(item["keyColumns"], ensure_ascii=False), item["id"]),
                )
        saved_pipelines += 1
    return {"connections": saved_connections, "pipelines": saved_pipelines}


def pipeline_scope_rows() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM pipeline").fetchall()
        kinds = {row["id"]: row["kind"] for row in conn.execute("SELECT id, kind FROM connection")}
    items = []
    for row in rows:
        try:
            mapping = json.loads(row["mapping_json"] or "[]")
        except json.JSONDecodeError:
            mapping = []
        items.append({
            "enabled": row["enabled"],
            "espo_entity": row["espo_entity"],
            "mapping": mapping,
            "kind": kinds.get(row["connection_id"] or ""),
        })
    return items


def app_user_name(info) -> str:
    if not isinstance(info, dict):
        return ""
    if info.get("userName"):
        return str(info["userName"])
    user = info.get("user")
    if isinstance(user, dict) and user.get("userName"):
        return str(user["userName"])
    return ""


def espo_find(entity: str, attribute: str, value: str) -> str:
    code, result = espo_admin("GET", f"/api/v1/{entity}", query={"select": "id,userName,name", "maxSize": "200"})
    if code != 200 or not isinstance(result, dict):
        return ""
    for row in result.get("list") or []:
        if str(row.get(attribute) or "") == value:
            return str(row.get("id") or "")
    return ""


def sync_service_role() -> None:
    if not setting_value("espo_service_user", "") or not setting_value("espo_role_id", ""):
        return
    role_id = setting_value("espo_role_id", "")
    entities = carico.role_scope(pipeline_scope_rows())
    code, result = espo_admin(
        "PUT",
        f"/api/v1/Role/{role_id}",
        {"data": carico.role_data(entities), "assignmentPermission": "all"},
    )
    if code not in (200, 201):
        raise RuntimeError(f"ruolo Nesso HTTP {code}: {result}")
    set_setting("espo_role_entities", json.dumps(entities, ensure_ascii=False))


def ensure_service_user() -> None:
    """Crea, via API, l'utente con cui i giri scrivono. La password resta nei segreti locali."""
    user = setting_value("espo_service_user", "")
    secret = setting_value("espo_service_secret", "")
    if user and secret:
        code, info = espo_call("GET", "/api/v1/App/user", user=user, password=secret)
        if code == 200 and app_user_name(info) == user:
            sync_service_role()
            return
    secret = secret or secrets.token_urlsafe(24)
    role_id = setting_value("espo_role_id", "") or espo_find("Role", "name", "Nesso")
    if not role_id:
        code, result = espo_admin(
            "POST",
            "/api/v1/Role",
            {
                "name": "Nesso",
                "assignmentPermission": "no",
                "userPermission": "no",
                "messagePermission": "no",
                "data": {},
            },
        )
        if code not in (200, 201) or not isinstance(result, dict) or not result.get("id"):
            raise RuntimeError(f"ruolo Nesso HTTP {code}: {result}")
        role_id = str(result["id"])
    user_id = espo_find("User", "userName", "nesso")
    payload = {
        "userName": "nesso",
        "firstName": "Nesso",
        "lastName": "Servizio",
        "type": "regular",
        "password": secret,
        "passwordConfirm": secret,
        "isActive": True,
        "rolesIds": [role_id],
    }
    if user_id:
        code, result = espo_admin("PUT", f"/api/v1/User/{user_id}", payload)
    else:
        code, result = espo_admin("POST", "/api/v1/User", payload)
    if code not in (200, 201):
        raise RuntimeError(f"utente Nesso HTTP {code}: {result}")
    check, info = espo_call("GET", "/api/v1/App/user", user="nesso", password=secret)
    if check != 200 or app_user_name(info) != "nesso":
        raise RuntimeError(f"l'utente Nesso non entra: HTTP {check}")
    set_setting("espo_role_id", role_id)
    set_setting("espo_service_secret", secret)
    set_setting("espo_service_label", "Nesso Servizio")
    set_setting("espo_service_user", "nesso")
    sync_service_role()


def actor_count() -> int:
    with connect() as conn:
        return int(conn.execute("SELECT COUNT(*) AS n FROM actor").fetchone()["n"])


def create_actor(name: str, password: str, gesture: str) -> dict:
    clean = str(name or "").strip()
    if gesture not in ("cambia", "lancia"):
        raise RuntimeError("il gesto è cambia oppure lancia")
    if not clean:
        raise RuntimeError("scrivi il nome")
    if len(str(password or "")) < 8:
        raise RuntimeError("la password ha almeno 8 caratteri")
    actor_id = secrets.token_hex(8)
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO actor (id, name, password_hash, gesture) VALUES (?, ?, ?, ?)",
                (actor_id, clean, carico.password_record(password), gesture),
            )
    except sqlite3.IntegrityError as error:
        raise RuntimeError("questo nome c'è già") from error
    return {"id": actor_id, "name": clean, "gesture": gesture}


def open_session(actor_id: str) -> str:
    token = secrets.token_urlsafe(32)
    with connect() as conn:
        conn.execute(
            "INSERT INTO session (token, actor_id, created_at) VALUES (?, ?, ?)",
            (token, actor_id, time.strftime("%Y-%m-%d %H:%M:%S")),
        )
    return token


def first_actor(body: dict) -> tuple[dict, str]:
    if actor_count():
        raise RuntimeError("l'ingresso c'è già")
    if str(body.get("gesture") or "cambia") != "cambia":
        raise RuntimeError("il primo ingresso cambia le integrazioni")
    actor = create_actor(str(body.get("name") or ""), str(body.get("password") or ""), "cambia")
    return actor, open_session(actor["id"])


def login_actor(body: dict) -> tuple[dict, str]:
    name = str(body.get("name") or "").strip()
    password = str(body.get("password") or "")
    with connect() as conn:
        row = conn.execute("SELECT * FROM actor WHERE name = ?", (name,)).fetchone()
    if row is None or not carico.password_matches(password, row["password_hash"]):
        raise PermissionError("ingresso non riuscito")
    return {"name": row["name"], "gesture": row["gesture"]}, open_session(row["id"])


def actor_from_cookie(handler: BaseHTTPRequestHandler) -> sqlite3.Row | None:
    raw = handler.headers.get("Cookie") or ""
    token = ""
    for piece in raw.split(";"):
        key, _, value = piece.strip().partition("=")
        if key == "nesso_sessione":
            token = value.strip()
    if not token:
        return None
    with connect() as conn:
        return conn.execute(
            """
            SELECT actor.id, actor.name, actor.gesture
            FROM session JOIN actor ON actor.id = session.actor_id
            WHERE session.token = ?
            """,
            (token,),
        ).fetchone()


def close_session(token: str) -> None:
    if not token:
        return
    with connect() as conn:
        conn.execute("DELETE FROM session WHERE token = ?", (token,))


def _planned(pipeline_id: str) -> None:
    try:
        run_pipeline(pipeline_id)
    except Exception as error:
        print("[motore] pianificazione", pipeline_id, error)


def scheduler() -> None:
    while True:
        time.sleep(30)
        try:
            now = time.time()
            with connect() as conn:
                rows = conn.execute(
                    """
                    SELECT id, schedule_minutes, schedule_at, last_run, enabled FROM pipeline
                    WHERE connection_id IS NOT NULL AND COALESCE(enabled, 1) = 1
                      AND (schedule_minutes > 0 OR (schedule_at IS NOT NULL AND schedule_at != ''))
                    """
                ).fetchall()
            for row in rows:
                if not pipeline_due(row, now):
                    continue
                if pipeline_lock(row["id"]).locked():
                    continue
                threading.Thread(target=_planned, args=(row["id"],), daemon=True).start()
            try:
                notice_absent()
                notice_quiet()
                scan_person_badges()
                retry_mail()
                retry_rejects()
                poll_imap()
            except Exception as error:
                print("[motore] pianificazione", error)
        except Exception as error:
            print("[motore] pianificazione", error)


PAGE_PATH = Path(__file__).with_name("index.html")
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print("[motore]", self.address_string(), fmt % args)

    def send_json(self, code: int, payload: dict) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode()
        self.send_bytes(code, raw, "application/json; charset=utf-8")

    def send_bytes(self, code: int, raw: bytes, content_type: str, filename: str | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode())

    def send_fail(self, status: int, error) -> None:
        self.send_json(status, {"error": frasi.traduci(str(error), frasi.lingua_corrente())})

    def send_entry(self, code: int, payload: dict, token: str | None = None, clear: bool = False) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if token:
            self.send_header("Set-Cookie", f"nesso_sessione={token}; HttpOnly; SameSite=Lax; Path=/")
        if clear:
            self.send_header("Set-Cookie", "nesso_sessione=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def open_path(self, path: str) -> bool:
        if path in ("/", "/api/health", "/api/frasi", "/api/sessione", "/api/ingresso", "/api/ingresso/primo"):
            return True
        return path.startswith("/fonts/") or path.startswith("/hook/") or path.startswith("/inbox/")

    def refuse(self, path: str) -> bool:
        if self.open_path(path):
            return False
        actor = actor_from_cookie(self)
        if actor is None:
            self.send_fail(401, "serve l'ingresso")
            return True
        if not carico.gesture_can(actor["gesture"], self.command, path):
            self.send_fail(403, "questo gesto non modifica l'abbinamento")
            return True
        return False

    def cookie_token(self) -> str:
        raw = self.headers.get("Cookie") or ""
        for piece in raw.split(";"):
            key, _, value = piece.strip().partition("=")
            if key == "nesso_sessione":
                return value.strip()
        return ""

    def do_GET(self) -> None:
        frasi.imposta_lingua(self.headers.get("X-Nesso-Lang"))
        path = urllib.parse.urlparse(self.path).path
        if path == "/":
            raw = PAGE_PATH.read_text(encoding="utf-8").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if path.startswith("/fonts/"):
            name = Path(path).name
            font = Path(__file__).with_name("fonts") / name
            if name.endswith(".woff2") and font.is_file():
                raw = font.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "font/woff2")
                self.send_header("Cache-Control", "public, max-age=86400")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
        if path == "/api/sessione":
            actor = actor_from_cookie(self)
            if actor is None:
                self.send_json(401, {"error": frasi.traduci("serve l'ingresso", frasi.lingua_corrente()), "primo": actor_count() == 0})
                return
            self.send_json(200, {"name": actor["name"], "gesture": actor["gesture"]})
            return
        if self.refuse(path):
            return
        try:
            if path == "/api/state":
                self.send_json(200, snapshot())
                return
            if path == "/api/catalog":
                self.send_json(200, {"entities": load_catalog(), "espoPublicUrl": ESPO_PUBLIC})
                return
            if path == "/api/health":
                self.send_json(200, {"ok": True, **STATE})
                return
            if path == "/api/frasi":
                self.send_json(200, frasi.catalogo())
                return
            if path == "/api/export":
                self.send_json(200, export_config())
                return
            if path == "/api/foglio":
                self.send_bytes(200, sheet_export().encode("utf-8"), "text/csv; charset=utf-8", "nesso-abbinamento.csv")
                return
            if path == "/api/consegna":
                self.send_json(200, consegna_view())
                return
        except Exception as error:
            self.send_fail(400, error)
            return
        self.send_fail(404, "non trovato")

    def do_POST(self) -> None:
        frasi.imposta_lingua(self.headers.get("X-Nesso-Lang"))
        path = urllib.parse.urlparse(self.path).path
        parts = [part for part in path.split("/") if part]
        try:
            if path == "/api/ingresso/primo":
                actor, token = first_actor(self.read_json())
                self.send_entry(200, {"name": actor["name"], "gesture": actor["gesture"]}, token)
                return
            if path == "/api/ingresso":
                actor, token = login_actor(self.read_json())
                self.send_entry(200, actor, token)
                return
            if path == "/api/uscita":
                close_session(self.cookie_token())
                self.send_entry(200, {"ok": True}, clear=True)
                return
            if path == "/api/attori":
                if self.refuse(path):
                    return
                body = self.read_json()
                self.send_json(200, create_actor(str(body.get("name") or ""), str(body.get("password") or ""), str(body.get("gesture") or "")))
                return
            if not path.startswith("/hook/") and not path.startswith("/inbox/") and self.refuse(path):
                return
            if path == "/api/connections":
                self.send_json(200, save_connection(self.read_json()))
                return
            if path == "/api/pipelines":
                self.send_json(200, save_pipeline(self.read_json()))
                return
            if path == "/api/sheets":
                self.send_json(200, create_sheet(self.read_json()))
                return
            if len(parts) == 4 and parts[:2] == ["api", "sheets"] and parts[3] == "fields":
                self.send_json(200, add_sheet_field(parts[2], self.read_json()))
                return
            if path == "/api/import":
                self.send_json(200, import_config(self.read_json()))
                return
            if path == "/api/foglio":
                body = self.read_json()
                self.send_json(200, import_sheet(str(body.get("text") or "")))
                return
            if path == "/api/privacy":
                body = self.read_json()
                self.send_json(200, privacy_for(str(body.get("contact") or ""), str(body.get("company") or "")))
                return
            if len(parts) == 4 and parts[:2] == ["api", "pipelines"] and parts[3] == "run":
                body = self.read_json()
                self.send_json(200, run_pipeline(parts[2], bool(body.get("withDependencies"))))
                return
            if len(parts) == 4 and parts[:2] == ["api", "pipelines"] and parts[3] == "dry":
                length = int(self.headers.get("Content-Length") or 0)
                sample = None
                if length:
                    loaded = self.read_json()
                    if isinstance(loaded, dict) and "sample" in loaded:
                        sample = loaded.get("sample")
                    else:
                        sample = loaded
                self.send_json(200, dry_run(parts[2], sample))
                return
            if len(parts) == 6 and parts[:2] == ["api", "pipelines"] and parts[3] == "versioni" and parts[5] == "ripristina":
                actor = actor_from_cookie(self)
                self.send_json(200, restore_version(parts[2], int(parts[4]), actor["name"] if actor else ""))
                return
            if len(parts) == 4 and parts[:2] == ["api", "scarti"] and parts[3] == "ripeti":
                self.send_json(200, replay_reject(int(parts[2])))
                return
            if len(parts) == 5 and parts[:2] == ["api", "sheets"] and parts[3] == "fields":
                body = self.read_json()
                self.send_json(200, rename_field(parts[2], parts[4], str(body.get("label") or "")))
                return
            if path == "/api/passaggio":
                self.send_json(200, passaggio_config())
                return
            if path == "/api/ambiente":
                body = self.read_json()
                ambiente = str(body.get("ambiente") or "").strip()
                if ambiente not in ("prova", "esercizio"):
                    self.send_fail(400, "l'ambiente è prova o esercizio")
                    return
                set_setting("ambiente", ambiente)
                self.send_json(200, {"ambiente": ambiente})
                return
            if path == "/api/posta/prova":
                if not carico.mail_ready(setting_value("smtp_host")):
                    self.send_fail(400, "manca l'indirizzo SMTP")
                    return
                self.send_json(200, {"queued": queue_mail("prova", "Nesso: prova di invio", "Prova di invio del motore.")})
                return
            if len(parts) == 4 and parts[:2] == ["api", "pipelines"] and parts[3] == "versioni":
                self.send_json(200, {"versions": mapping_versions(parts[2])})
                return
            if len(parts) == 4 and parts[:2] == ["api", "pipelines"] and parts[3] == "anteprima":
                self.send_json(200, anteprima(parts[2]))
                return
            if len(parts) == 4 and parts[:2] == ["api", "pipelines"] and parts[3] == "lettura":
                body = self.read_json()
                self.send_json(200, set_read_mode(
                    parts[2],
                    body.get("enabled") not in (False, 0, "0"),
                    int(body.get("hours") or 48),
                ))
                return
            if len(parts) == 4 and parts[:2] == ["api", "pipelines"] and parts[3] == "annulla":
                self.send_json(200, undo_last(parts[2]))
                return
            if len(parts) == 4 and parts[:2] == ["api", "pipelines"] and parts[3] == "chiusure":
                self.send_json(200, confirm_closes(parts[2]))
                return
            if len(parts) == 3 and parts[:2] == ["api", "watch"]:
                body = self.read_json()
                self.send_json(200, resolve_watch(int(parts[2]), str(body.get("keep") or "")))
                return
            if path == "/api/scritture":
                body = self.read_json()
                enabled = body.get("enabled") not in (False, 0, "0")
                set_setting("writes", "1" if enabled else "0")
                self.send_json(200, {"writesEnabled": enabled})
                return
            if len(parts) == 4 and parts[:2] == ["api", "connections"] and parts[3] == "campione":
                self.send_json(200, connection_sample(parts[2]))
                return
            if path == "/api/silenzio":
                self.send_json(200, save_silence(self.read_json()))
                return
            if path == "/api/piani":
                self.send_json(200, save_plan(self.read_json()))
                return
            if path == "/api/proponi/modello":
                self.send_json(200, complete_with_model(self.read_json()))
                return
            if path == "/api/proponi":
                body = self.read_json()
                self.send_json(200, {
                    "rows": carico.propose(
                        list(body.get("columns") or []),
                        frasi.lingua_corrente(),
                        list(body.get("fields") or []),
                        list(body.get("samples") or []),
                    )
                })
                return
            if len(parts) == 3 and parts[:2] == ["api", "ricette"]:
                body = self.read_json()
                fields = list(body.get("fields") or [])
                recipes = {
                    "anagrafiche": carico.recipe_anagrafiche,
                    "contatti": carico.recipe_contatti,
                    "sedi": carico.recipe_sedi,
                    "listino": carico.recipe_listino,
                }
                recipe = recipes.get(parts[2])
                if recipe is None:
                    self.send_fail(404, "non trovato")
                    return
                self.send_json(200, recipe(fields))
                return
            if len(parts) == 5 and parts[:2] == ["api", "pipelines"] and parts[3] == "silenzio" and parts[4] == "conferma":
                self.send_json(200, confirm_silence(parts[2]))
                return
            if len(parts) == 5 and parts[:2] == ["api", "pipelines"] and parts[3] == "silenzio" and parts[4] == "scarta":
                self.send_json(200, discard_silence(parts[2]))
                return
            if len(parts) == 5 and parts[:2] == ["api", "pipelines"] and parts[3] == "gradino" and parts[4] == "conferma":
                self.send_json(200, confirm_step(parts[2]))
                return
            if len(parts) == 4 and parts[:2] == ["api", "proposte"] and parts[3] == "conferma":
                self.send_json(200, confirm_proposal(int(parts[2])))
                return
            if len(parts) == 4 and parts[:2] == ["api", "proposte"] and parts[3] == "lascia":
                self.send_json(200, leave_proposal(int(parts[2])))
                return
            if len(parts) == 4 and parts[:2] == ["api", "pipelines"] and parts[3] == "enabled":
                body = self.read_json()
                self.send_json(200, set_enabled(parts[2], body.get("enabled") not in (False, 0, "0")))
                return
            if len(parts) == 3 and parts[0] == "hook":
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw.decode()) if raw else {}
                except json.JSONDecodeError:
                    self.send_fail(400, "il corpo deve essere un oggetto o un elenco")
                    return
                self.send_json(200, accept_hook(parts[1], parts[2], body, raw, self.headers.get("X-Nesso-Firma") or ""))
                return
            if len(parts) == 3 and parts[0] == "inbox":
                self.send_json(200, accept_inbox(parts[1], parts[2], self.read_json()))
                return
            if path.startswith("/api/ingest/"):
                pipeline_id = path.removeprefix("/api/ingest/")
                body = self.read_json()
                try:
                    decision = silence_for(pipeline_id)
                    if decision["action"] != "scrivi":
                        if isinstance(body, dict):
                            park_silence(pipeline_id, body, decision.get("reason") or "")
                        self.send_json(200, silence_reply(decision))
                        return
                    self.send_json(200, ingest(pipeline_id, body))
                except Exception as error:
                    remember_reject(pipeline_id, "", body, str(error))
                    self.send_fail(400, error)
                return
            if path.startswith("/api/pull/"):
                self.send_json(200, pull(path.removeprefix("/api/pull/")))
                return
        except PermissionError as error:
            self.send_fail(401, error)
            return
        except KeyError:
            self.send_fail(404, "non trovato")
            return
        except Exception as error:
            self.send_fail(400, error)
            return
        self.send_fail(404, "non trovato")

    def do_DELETE(self) -> None:
        frasi.imposta_lingua(self.headers.get("X-Nesso-Lang"))
        path = urllib.parse.urlparse(self.path).path
        if self.refuse(path):
            return
        try:
            if path.startswith("/api/silenzio/"):
                self.send_json(200, delete_silence(int(path.removeprefix("/api/silenzio/"))))
                return
            if path.startswith("/api/pipelines/"):
                self.send_json(200, delete_pipeline(path.removeprefix("/api/pipelines/")))
                return
            if path.startswith("/api/connections/"):
                connection_id = path.removeprefix("/api/connections/")
                with connect() as conn:
                    conn.execute("UPDATE pipeline SET connection_id = NULL WHERE connection_id = ?", (connection_id,))
                    deleted = conn.execute("DELETE FROM connection WHERE id = ?", (connection_id,)).rowcount
                if not deleted:
                    self.send_fail(404, "collegamento non trovato")
                    return
                self.send_json(200, {"deleted": connection_id})
                return
        except Exception as error:
            self.send_fail(400, error)
            return
        self.send_fail(404, "non trovato")


def main() -> None:
    init_db()
    threading.Thread(target=prepare_espo, daemon=True).start()
    threading.Thread(target=scheduler, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"motore in ascolto su {PORT}, Espo interno {ESPO_BASE}")
    server.serve_forever()


if __name__ == "__main__":
    main()
