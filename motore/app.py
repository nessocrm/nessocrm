"""Motore di integrazione locale. Parla con Espo solo via API."""

from __future__ import annotations

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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DB_PATH = Path(os.environ.get("DB_PATH", "/data/motore.sqlite"))
ESPO_BASE = os.environ.get("ESPO_BASE_URL", "http://espocrm").rstrip("/")
ESPO_PUBLIC = os.environ.get("ESPO_PUBLIC_URL", "http://localhost:8088").rstrip("/")
ESPO_USER = os.environ.get("ESPO_USER", "admin")
ESPO_PASSWORD = os.environ.get("ESPO_PASSWORD", "locale-admin")
PORT = int(os.environ.get("LISTEN_PORT", "8091"))
PUBLIC_BASE = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8091").rstrip("/")
SCAMBIO = Path(os.environ.get("SCAMBIO_DIR", "/scambio"))
RUN_LOCK = threading.Lock()

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
        }
        for name, ddl in additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE pipeline ADD COLUMN {name} {ddl}")


def espo_request(method: str, path: str, body: dict | None = None, query: dict | None = None):
    url = ESPO_BASE + path
    if query:
        url += "?" + urllib.parse.urlencode(query, doseq=True)
    token = __import__("base64").b64encode(f"{ESPO_USER}:{ESPO_PASSWORD}".encode()).decode()
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
    boundary = "----Nesso" + hashlib.sha256(path.name.encode()).hexdigest()[:16]
    chunks = []
    for field, value in (("role", "Attachment"), ("field", "file"), ("parentType", "Document")):
        chunks.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"\r\n\r\n{value}\r\n".encode()
        )
    chunks.append(
        (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: {mime}\r\n\r\n"
        ).encode()
        + path.read_bytes()
        + b"\r\n"
    )
    chunks.append(f"--{boundary}--\r\n".encode())
    token = __import__("base64").b64encode(f"{ESPO_USER}:{ESPO_PASSWORD}".encode()).decode()
    req = urllib.request.Request(ESPO_BASE + "/api/v1/Attachment", data=b"".join(chunks), method="POST")
    req.add_header("Espo-Authorization", token)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as error:
        raw = error.read().decode()
        raise RuntimeError(f"caricamento file HTTP {error.code}: {raw}") from error
    if not isinstance(result, dict) or not result.get("id"):
        raise RuntimeError(f"caricamento file senza id: {result}")
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


def ensure_field(entity: str, name: str, label: str, length: int) -> str:
    status, result = espo_request(
        "POST",
        f"/api/v1/Admin/fieldManager/{entity}",
        {
            "name": name,
            "type": "varchar",
            "label": label,
            "maxLength": length,
        },
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


def create_lookup(entity: str, foreign: str, label: str, back_label: str | None = None) -> str:
    existing = links_of(entity)
    for link_name, link in existing.items():
        if isinstance(link, dict) and link.get("type") == "belongsTo" and link.get("entity") == foreign:
            return link_name
    source = bare_entity(foreign)
    source = source[0].lower() + source[1:]
    foreign_name = bare_entity(entity)
    if not foreign_name.endswith("s"):
        foreign_name += "s"
    foreign_name = foreign_name[0].lower() + foreign_name[1:]
    candidate = source
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


def show_on_layout(entity: str, names: list[str]) -> None:
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
            cols.append({"name": name})
            changed = True
    if changed:
        espo_request("PUT", f"/api/v1/{entity}/layout/list", cols)


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
        from demo_meridia import seed_demo
        seed_demo(connect, save_connection, save_pipeline, run_pipeline, ingest, SCAMBIO, espo_request)
    except Exception as error:
        print("[motore] demo", error)


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
    raise RuntimeError(f"transform sconosciuto: {transform}")


def map_payload(mapping: list[dict], payload: dict, key: str | None, key_field: str) -> dict:
    mapped: dict = {}
    for rule in mapping:
        if rule.get("transform") == "lookup":
            value = payload.get(rule["from"])
            if value is None or str(value).strip() == "":
                continue
            found = find_by_key(rule["lookupEntity"], rule["lookupBy"], str(value).strip())
            if not found:
                raise RuntimeError(
                    f"nessun {rule['lookupEntity']} con {rule['lookupBy']} uguale a {value}"
                )
            mapped[rule["to"]] = found
            if rule.get("parentType"):
                mapped["parentType"] = rule["parentType"]
            continue
        if rule.get("transform") == "lookups":
            raw = str(payload.get(rule["from"]) or "")
            parts = [part.strip() for part in re.split(r"[;,]", raw) if part.strip()]
            if not parts:
                continue
            ids = []
            for part in parts:
                found = find_by_key(rule["lookupEntity"], rule["lookupBy"], part)
                if not found:
                    raise RuntimeError(
                        f"nessun {rule['lookupEntity']} con {rule['lookupBy']} uguale a {part}"
                    )
                ids.append(found)
            mapped[rule["to"]] = ids
            continue
        if rule.get("transform") == "file":
            raw = str(payload.get(rule["from"]) or "").strip()
            if not raw:
                continue
            mapped[rule["to"]] = upload_attachment(resolve_import_file(raw))
            continue
        value = apply_transform(rule, payload)
        if value is not None and value != "":
            if rule.get("kind") == "bool":
                mapped[rule["to"]] = str(value).strip().lower() in {"1", "true", "si", "sì", "yes"}
            else:
                mapped[rule["to"]] = value
    if key:
        mapped[key_field] = key
    return mapped


def render_key(template: str, payload: dict) -> str:
    key = template
    for name, value in payload.items():
        key = key.replace("{" + name + "}", str(value))
    if "{" in key or not key:
        raise RuntimeError("chiave esterna incompleta")
    return key


def find_by_key(entity: str, key_field: str, key: str):
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


def upsert(entity: str, mapped: dict, existing_id: str | None, key_field: str) -> tuple[str, str]:
    if existing_id:
        code, result = espo_request("PUT", f"/api/v1/{entity}/{existing_id}", mapped)
        action = "aggiornato"
    else:
        found = find_by_key(entity, key_field, mapped[key_field])
        if found:
            code, result = espo_request("PUT", f"/api/v1/{entity}/{found}", mapped)
            action = "aggiornato"
            existing_id = found
        else:
            code, result = espo_request("POST", f"/api/v1/{entity}", mapped)
            action = "creato"
    if code == 409 and isinstance(result, list) and result and isinstance(result[0], dict):
        existing = result[0]
        if existing.get(key_field) == mapped.get(key_field) and existing.get("id"):
            code, result = espo_request("PUT", f"/api/v1/{entity}/{existing['id']}", mapped)
            action = "aggiornato"
        else:
            label = existing.get("name") or existing.get("id")
            raise RuntimeError(f"Espo ha già un record simile ({label}) con un'altra chiave")
    if code not in (200, 201) or not isinstance(result, dict) or "id" not in result:
        raise RuntimeError(f"scrittura {entity} HTTP {code}: {result}")
    return result["id"], action


def ingest(pipeline_id: str, payload: dict) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM pipeline WHERE id = ?", (pipeline_id,)).fetchone()
        if row is None:
            raise KeyError(pipeline_id)
        if row["direction"] != "in":
            raise RuntimeError("la pipeline non è in ingresso")
        external_id = str(payload.get(row["external_id_field"]) or "").strip()
        if not external_id:
            raise RuntimeError(f"manca il campo {row['external_id_field']}")
        key = render_key(row["key_template"], payload)
        mapping = json.loads(row["mapping_json"])
        key_field = row["key_field"] or "cExternalKey"
        mapped = map_payload(mapping, payload, key, key_field)
        if scope_is_custom(row["espo_entity"]) and not mapped.get("name"):
            mapped["name"] = external_id
        digest = hashlib.sha256(json.dumps(mapped, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        previous = conn.execute(
            "SELECT * FROM queue_item WHERE pipeline_id = ? AND external_id = ?",
            (pipeline_id, external_id),
        ).fetchone()
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        if previous and previous["hash"] == digest and previous["status"] == "synced":
            return {
                "status": "invariato",
                "espoId": previous["espo_id"],
                "externalKey": key,
                "entity": row["espo_entity"],
            }
        espo_id, action = upsert(
            row["espo_entity"], mapped, previous["espo_id"] if previous else None, key_field
        )
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
            (pipeline_id, external_id, json.dumps(payload, ensure_ascii=False), json.dumps(mapped, ensure_ascii=False), digest, espo_id, action, now),
        )
        return {"status": action, "espoId": espo_id, "externalKey": key, "entity": row["espo_entity"]}


def pull(pipeline_id: str) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM pipeline WHERE id = ?", (pipeline_id,)).fetchone()
        if row is None:
            raise KeyError(pipeline_id)
        if row["direction"] != "out":
            raise RuntimeError("la pipeline non è in uscita")
        cursor = conn.execute(
            "SELECT cursor_value FROM cursor_state WHERE pipeline_id = ?",
            (pipeline_id,),
        ).fetchone()
        cursor_value = cursor["cursor_value"] if cursor else "1970-01-01 00:00:00"
        mapping = json.loads(row["mapping_json"])
        select = ",".join(sorted({rule["from"] for rule in mapping}))
        code, result = espo_request(
            "GET",
            f"/api/v1/{row['espo_entity']}",
            query={
                "select": select,
                "maxSize": "50",
                "orderBy": "modifiedAt",
                "order": "asc",
                "where[0][type]": "after",
                "where[0][attribute]": "modifiedAt",
                "where[0][value]": cursor_value,
            },
        )
        if code != 200 or not isinstance(result, dict):
            raise RuntimeError(f"lettura Espo HTTP {code}: {result}")
        exported = 0
        records = []
        last = cursor_value
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        for item in result.get("list") or []:
            outgoing = {}
            for rule in mapping:
                value = item.get(rule["from"])
                if value is not None:
                    outgoing[rule["to"]] = value
            conn.execute(
                "INSERT INTO sink_item (pipeline_id, espo_id, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (pipeline_id, item.get("id"), json.dumps(outgoing, ensure_ascii=False), now),
            )
            records.append(outgoing)
            if item.get("modifiedAt") and item["modifiedAt"] > last:
                last = item["modifiedAt"]
            exported += 1
        if exported:
            conn.execute(
                """
                INSERT INTO cursor_state (pipeline_id, cursor_value) VALUES (?, ?)
                ON CONFLICT(pipeline_id) DO UPDATE SET cursor_value = excluded.cursor_value
                """,
                (pipeline_id, last),
            )
        return {"exported": exported, "cursor": last, "total": result.get("total"), "records": records}


def snapshot() -> dict:
    with connect() as conn:
        pipelines = [dict(row) for row in conn.execute("SELECT * FROM pipeline ORDER BY direction, id")]
        for item in pipelines:
            item["mapping"] = json.loads(item.pop("mapping_json"))
        queue = [dict(row) for row in conn.execute("SELECT * FROM queue_item ORDER BY updated_at DESC LIMIT 30")]
        sink = [dict(row) for row in conn.execute("SELECT * FROM sink_item ORDER BY id DESC LIMIT 20")]
        connections = [public_connection(row) for row in conn.execute("SELECT * FROM connection ORDER BY name")]
        deliveries = [dict(row) for row in conn.execute("SELECT * FROM delivery ORDER BY id DESC LIMIT 20")]
    return {
        "state": STATE,
        "espoPublicUrl": ESPO_PUBLIC,
        "publicBase": PUBLIC_BASE,
        "pipelines": pipelines,
        "connections": connections,
        "queue": queue,
        "sink": sink,
        "deliveries": deliveries,
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
            usable.append({
                "name": field_name,
                "label": field_labels.get(field_name) or global_fields.get(field_name) or field_name,
                "type": field_def.get("type"),
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
        if lookup_by == foreign_meta["keyField"]:
            ensure_field(foreign, "externalKey", "Chiave esterna", 180)
        else:
            raise RuntimeError("campo di riconoscimento non trovato sulla scheda collegata")
    return foreign_meta, lookup_by


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
        if not source or not target:
            continue
        if role in ("link", "links", "parent"):
            foreign = str(rule.get("lookupEntity") or "").strip()
            foreign_meta, lookup_by = prepare_lookup(catalog, foreign, str(rule.get("lookupBy") or "").strip())
            if role == "parent":
                compiled.append({
                    "from": source,
                    "to": "parentId",
                    "transform": "lookup",
                    "lookupEntity": foreign,
                    "lookupBy": lookup_by,
                    "parentType": foreign,
                })
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
                compiled.append({
                    "from": source,
                    "to": chosen["idName"],
                    "transform": "lookups",
                    "lookupEntity": foreign,
                    "lookupBy": lookup_by,
                })
                continue
            existing = by_name.get(target)
            if existing and existing.get("type") == "link" and existing.get("foreignEntity") == foreign:
                link_name = target
            else:
                link_name = create_lookup(entity, foreign, foreign_meta["label"], back_label)
            compiled.append({
                "from": source,
                "to": link_name + "Id",
                "transform": "lookup",
                "lookupEntity": foreign,
                "lookupBy": lookup_by,
            })
            layout_names.append(link_name)
            continue
        chosen = by_name.get(target)
        if chosen and chosen.get("type") == "file":
            compiled.append({"from": source, "to": chosen["idName"], "transform": "file"})
            continue
        if chosen and chosen.get("type") == "bool":
            compiled.append({"from": source, "to": target, "transform": "copy", "kind": "bool"})
            continue
        if chosen and chosen.get("type") in ("linkMultiple", "linkParent"):
            raise RuntimeError("questo collegamento va indicato come collegamento a più record, o come attività")
        if creating and (target not in by_name or by_name[target].get("type") == "link"):
            requested = camel_name(target)
            actual = ensure_field(entity, requested, target, 180)
            compiled.append({"from": source, "to": actual, "transform": "copy"})
            layout_names.append(actual)
            continue
        if target not in by_name or by_name[target].get("type") == "link":
            raise RuntimeError("campi Espo non riconosciuti: " + target)
        compiled.append({"from": source, "to": target, "transform": "copy"})
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
        key_field = meta["keyField"]
        ensure_field(entity, "externalKey", "Chiave esterna", 180)
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
            clean.append({"from": source, "to": target, "transform": "copy"})
        if not clean:
            raise RuntimeError("abbina almeno un campo")
        key_field = meta["keyField"]
    schedule = int(body.get("scheduleMinutes") or 0)
    if schedule not in (0, 5, 15, 60):
        raise RuntimeError("la cadenza può essere manuale, 5, 15 o 60 minuti")
    connection_id = str(body.get("connectionId") or "").strip()
    with connect() as conn:
        if connection_id:
            link = conn.execute("SELECT * FROM connection WHERE id = ?", (connection_id,)).fetchone()
            if link is None:
                raise RuntimeError("collegamento non trovato")
            expected = "out" if link["kind"] == "http" else "in"
            if direction != expected:
                raise RuntimeError("il collegamento e il verso non coincidono")
        else:
            connection_id = None
        pipeline_id = str(body.get("id") or "").strip()
        if pipeline_id:
            existing = conn.execute("SELECT id FROM pipeline WHERE id = ?", (pipeline_id,)).fetchone()
            if existing is None:
                raise RuntimeError("integrazione non trovata")
        else:
            pipeline_id = slugify(name)
            suffix = 2
            base = pipeline_id
            while conn.execute("SELECT 1 FROM pipeline WHERE id = ?", (pipeline_id,)).fetchone():
                pipeline_id = f"{base}-{suffix}"
                suffix += 1
        key_template = f"{pipeline_id}:{{{external_id_field}}}" if direction == "in" else ""
        if direction == "out":
            external_id_field = external_id_field or "id"
        conn.execute(
            """
            INSERT INTO pipeline
            (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field, connection_id, schedule_minutes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                direction = excluded.direction,
                espo_entity = excluded.espo_entity,
                external_id_field = excluded.external_id_field,
                key_template = excluded.key_template,
                mapping_json = excluded.mapping_json,
                key_field = excluded.key_field,
                connection_id = excluded.connection_id,
                schedule_minutes = excluded.schedule_minutes
            """,
            (
                pipeline_id, name, direction, entity, external_id_field, key_template,
                json.dumps(clean, ensure_ascii=False), key_field, connection_id, schedule,
            ),
        )
    return {"id": pipeline_id, "name": name, "direction": direction, "espoEntity": entity}


def delete_pipeline(pipeline_id: str) -> dict:
    with connect() as conn:
        found = conn.execute("SELECT id FROM pipeline WHERE id = ?", (pipeline_id,)).fetchone()
        if found is None:
            raise KeyError(pipeline_id)
        conn.execute("DELETE FROM queue_item WHERE pipeline_id = ?", (pipeline_id,))
        conn.execute("DELETE FROM sink_item WHERE pipeline_id = ?", (pipeline_id,))
        conn.execute("DELETE FROM cursor_state WHERE pipeline_id = ?", (pipeline_id,))
        conn.execute("DELETE FROM pipeline WHERE id = ?", (pipeline_id,))
    return {"deleted": pipeline_id}


def public_connection(row: sqlite3.Row) -> dict:
    config = json.loads(row["config_json"])
    if config.get("password"):
        config["hasPassword"] = True
        config["password"] = ""
    item = {"id": row["id"], "name": row["name"], "kind": row["kind"], "config": config}
    if row["kind"] == "webhook":
        item["url"] = f"{PUBLIC_BASE}/hook/{row['id']}/{row['token']}"
    if row["kind"] == "http":
        item["inboxUrl"] = f"{PUBLIC_BASE}/inbox/{row['id']}/{row['token']}"
    if row["kind"] == "csv":
        item["folder"] = str(SCAMBIO / row["id"])
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


def mark_run(pipeline_id: str, status: str, detail: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE pipeline SET last_run = ?, last_status = ?, last_detail = ? WHERE id = ?",
            (time.strftime("%Y-%m-%d %H:%M:%S"), status, detail[:500], pipeline_id),
        )


def save_connection(body: dict) -> dict:
    name = str(body.get("name") or "").strip()
    kind = body.get("kind")
    if not name:
        raise RuntimeError("manca il nome del collegamento")
    if kind not in ("webhook", "database", "csv", "http"):
        raise RuntimeError("tipo di collegamento non riconosciuto")
    config = body.get("config") or {}
    if kind == "database":
        for field in ("host", "database", "user", "query"):
            if not str(config.get(field) or "").strip():
                raise RuntimeError(f"manca {field}")
        config["query"] = validate_select(config["query"])
        config["port"] = int(config.get("port") or 3306)
        config["host"] = str(config["host"]).strip()
        config["database"] = str(config["database"]).strip()
        config["user"] = str(config["user"]).strip()
    if kind == "http":
        url = str(config.get("url") or "").strip()
        if url and not url.startswith(("http://", "https://")):
            raise RuntimeError("l'indirizzo di destinazione deve essere http o https")
        config = {"url": url}
    if kind == "csv":
        config = {}
    if kind == "webhook":
        config = {}
    with connect() as conn:
        connection_id = str(body.get("id") or "").strip()
        if connection_id:
            current = conn.execute("SELECT * FROM connection WHERE id = ?", (connection_id,)).fetchone()
            if current is None:
                raise RuntimeError("collegamento non trovato")
            token = current["token"]
            previous = json.loads(current["config_json"])
            if kind == "database" and not str(config.get("password") or "") and previous.get("password"):
                config["password"] = previous["password"]
        else:
            connection_id = slugify(name)
            suffix = 2
            base = connection_id
            while conn.execute("SELECT 1 FROM connection WHERE id = ?", (connection_id,)).fetchone():
                connection_id = f"{base}-{suffix}"
                suffix += 1
            token = secrets.token_urlsafe(24)
        if kind == "database":
            columns = read_database(config, sample=1)
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
            (connection_id, name, kind, json.dumps(config, ensure_ascii=False), token),
        )
    if kind == "csv":
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


def read_database(config: dict, sample: int | None = None) -> list[dict]:
    import pymysql

    sql = validate_select(config["query"])
    limit = 5 if sample else 500
    wrapped = f"SELECT * FROM ({sql}) AS sorgente LIMIT {limit}"
    connection = pymysql.connect(
        host=config["host"],
        port=int(config.get("port") or 3306),
        user=config["user"],
        password=config.get("password") or "",
        database=config["database"],
        connect_timeout=8,
        read_timeout=30,
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(wrapped)
            raw_rows = cursor.fetchall()
    finally:
        connection.close()
    return [
        {key: None if value is None else str(value) for key, value in row.items()}
        for row in raw_rows
    ]


def read_csv_folder(connection_id: str) -> list[tuple[str, dict]]:
    folder = SCAMBIO / connection_id
    folder.mkdir(parents=True, exist_ok=True)
    done = folder / "elaborati"
    done.mkdir(exist_ok=True)
    found = []
    for path in sorted(folder.glob("*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                found.append((path, {key: value for key, value in row.items() if key}))
    return found


def post_json(url: str, payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode()
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=20) as response:
        if response.status >= 300:
            raise RuntimeError(f"destinazione HTTP {response.status}")


def accept_hook(connection_id: str, token: str, body: dict | list) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM connection WHERE id = ?", (connection_id,)).fetchone()
        pipelines = [
            item["id"]
            for item in conn.execute(
                "SELECT id FROM pipeline WHERE connection_id = ? AND direction = 'in'",
                (connection_id,),
            )
        ]
    if row is None or row["kind"] != "webhook" or not hmac.compare_digest(row["token"], token):
        raise PermissionError("collegamento non valido")
    if isinstance(body, dict) and isinstance(body.get("records"), list):
        records = body["records"]
    elif isinstance(body, list):
        records = body
    elif isinstance(body, dict):
        records = [body]
    else:
        raise RuntimeError("il corpo deve essere un oggetto o un elenco")
    if not pipelines:
        raise RuntimeError("nessuna integrazione usa questo collegamento")
    done = []
    for pipeline_id in pipelines:
        for record in records:
            if not isinstance(record, dict):
                continue
            result = ingest(pipeline_id, record)
            done.append(result)
        mark_run(pipeline_id, "ok", f"{len(records)} record ricevuti via webhook")
    return {"accepted": len(done), "results": done}


def accept_inbox(connection_id: str, token: str, body: dict) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM connection WHERE id = ?", (connection_id,)).fetchone()
    if row is None or row["kind"] != "http" or not hmac.compare_digest(row["token"], token):
        raise PermissionError("casella non valida")
    remember_delivery(None, connection_id, body, "ricevuto", "sistema esterno")
    return {"stored": True}


def run_pipeline(pipeline_id: str) -> dict:
    if not RUN_LOCK.acquire(blocking=False):
        raise RuntimeError("un'esecuzione è già in corso")
    try:
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
                mark_run(pipeline_id, "ok", f"letti {result['exported']} record, senza destinazione")
                return result
            raise RuntimeError("collega un sistema esterno prima di eseguire")
        config = json.loads(link["config_json"])
        if link["kind"] == "webhook":
            mark_run(pipeline_id, "ok", "in attesa che il sistema esterno chiami l'indirizzo")
            return {"waiting": True, "url": f"{PUBLIC_BASE}/hook/{link['id']}/{link['token']}"}
        if link["kind"] == "database":
            rows = read_database(config)
            created = updated = unchanged = failed = 0
            first_error = ""
            for row in rows:
                try:
                    item = ingest(pipeline_id, row)
                except Exception as error:
                    failed += 1
                    first_error = first_error or str(error)
                    continue
                created += item["status"] == "creato"
                updated += item["status"] == "aggiornato"
                unchanged += item["status"] == "invariato"
            detail = f"{len(rows)} righe dal database, {created} create, {updated} aggiornate, {unchanged} invariate, {failed} scartate"
            if first_error:
                detail += ". " + first_error
            mark_run(pipeline_id, "errore" if failed and not (created or updated or unchanged) else "ok", detail)
            return {"rows": len(rows), "created": created, "updated": updated, "unchanged": unchanged, "failed": failed}
        if link["kind"] == "csv":
            rows = read_csv_folder(link["id"])
            results = []
            for _path, row in rows:
                results.append(ingest(pipeline_id, row))
            done = SCAMBIO / link["id"] / "elaborati"
            done.mkdir(parents=True, exist_ok=True)
            moved = set()
            for path, _row in rows:
                if path in moved or not path.exists():
                    continue
                path.rename(done / f"{time.strftime('%Y%m%d%H%M%S')}-{path.name}")
                moved.add(path)
            detail = f"{len(rows)} righe dai file CSV"
            mark_run(pipeline_id, "ok", detail)
            return {"rows": len(rows), "results": len(results)}
        if link["kind"] == "http":
            result = pull(pipeline_id)
            url = str(config.get("url") or "").strip() or f"http://127.0.0.1:{PORT}/inbox/{link['id']}/{link['token']}"
            sent = 0
            for record in result["records"]:
                post_json(url, record)
                remember_delivery(pipeline_id, link["id"], record, "inviato", url)
                sent += 1
            detail = f"{sent} record inviati a {url}"
            mark_run(pipeline_id, "ok", detail)
            return {"sent": sent, "url": url}
        raise RuntimeError("tipo di collegamento non gestito")
    except Exception as error:
        mark_run(pipeline_id, "errore", str(error))
        raise
    finally:
        RUN_LOCK.release()


def scheduler() -> None:
    while True:
        time.sleep(30)
        try:
            now = time.time()
            with connect() as conn:
                rows = conn.execute(
                    """
                    SELECT id, schedule_minutes, last_run FROM pipeline
                    WHERE schedule_minutes > 0 AND connection_id IS NOT NULL
                    """
                ).fetchall()
            for row in rows:
                if row["last_run"]:
                    previous = time.mktime(time.strptime(row["last_run"], "%Y-%m-%d %H:%M:%S"))
                    if now - previous < row["schedule_minutes"] * 60:
                        continue
                try:
                    run_pipeline(row["id"])
                except Exception as error:
                    print("[motore] pianificazione", row["id"], error)
        except Exception as error:
            print("[motore] pianificazione", error)


PAGE_PATH = Path(__file__).with_name("index.html")
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print("[motore]", self.address_string(), fmt % args)

    def send_json(self, code: int, payload: dict) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode())

    def do_GET(self) -> None:
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
        except Exception as error:
            self.send_json(400, {"error": str(error)})
            return
        self.send_json(404, {"error": "non trovato"})

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        parts = [part for part in path.split("/") if part]
        try:
            if path == "/api/connections":
                self.send_json(200, save_connection(self.read_json()))
                return
            if path == "/api/pipelines":
                self.send_json(200, save_pipeline(self.read_json()))
                return
            if len(parts) == 4 and parts[:2] == ["api", "pipelines"] and parts[3] == "run":
                self.send_json(200, run_pipeline(parts[2]))
                return
            if len(parts) == 3 and parts[0] == "hook":
                self.send_json(200, accept_hook(parts[1], parts[2], self.read_json()))
                return
            if len(parts) == 3 and parts[0] == "inbox":
                self.send_json(200, accept_inbox(parts[1], parts[2], self.read_json()))
                return
            if path.startswith("/api/ingest/"):
                self.send_json(200, ingest(path.removeprefix("/api/ingest/"), self.read_json()))
                return
            if path.startswith("/api/pull/"):
                self.send_json(200, pull(path.removeprefix("/api/pull/")))
                return
        except PermissionError as error:
            self.send_json(401, {"error": str(error)})
            return
        except KeyError:
            self.send_json(404, {"error": "non trovato"})
            return
        except Exception as error:
            self.send_json(400, {"error": str(error)})
            return
        self.send_json(404, {"error": "non trovato"})

    def do_DELETE(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        try:
            if path.startswith("/api/pipelines/"):
                self.send_json(200, delete_pipeline(path.removeprefix("/api/pipelines/")))
                return
            if path.startswith("/api/connections/"):
                connection_id = path.removeprefix("/api/connections/")
                with connect() as conn:
                    conn.execute("UPDATE pipeline SET connection_id = NULL WHERE connection_id = ?", (connection_id,))
                    deleted = conn.execute("DELETE FROM connection WHERE id = ?", (connection_id,)).rowcount
                if not deleted:
                    self.send_json(404, {"error": "collegamento non trovato"})
                    return
                self.send_json(200, {"deleted": connection_id})
                return
        except Exception as error:
            self.send_json(400, {"error": str(error)})
            return
        self.send_json(404, {"error": "non trovato"})


def main() -> None:
    init_db()
    threading.Thread(target=prepare_espo, daemon=True).start()
    threading.Thread(target=scheduler, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"motore in ascolto su {PORT}, Espo interno {ESPO_BASE}")
    server.serve_forever()


if __name__ == "__main__":
    main()
