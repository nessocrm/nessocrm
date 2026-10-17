"""Sposta le offerte dalla scheda standard a una scheda Base Plus e prepara la home."""

from __future__ import annotations

import json
import os
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager

ENTITY = "COfferta"
STAGES = ["Prospecting", "Qualification", "Proposal", "Negotiation", "Closed Won", "Closed Lost"]
CLOSED = ["Closed Won", "Closed Lost"]


def espo_request(method: str, path: str, body: dict | None = None, query: dict | None = None):
    base = os.environ.get("ESPO_BASE_URL", "http://espocrm").rstrip("/")
    user = os.environ.get("ESPO_USER", "admin")
    password = os.environ.get("ESPO_PASSWORD", "locale-admin")
    url = base + path
    if query:
        url += "?" + urllib.parse.urlencode(query, doseq=True)
    token = __import__("base64").b64encode(f"{user}:{password}".encode()).decode()
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Espo-Authorization", token)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            raw = response.read().decode()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raw = error.read().decode()
        try:
            parsed = json.loads(raw) if raw else {"message": error.reason}
        except json.JSONDecodeError:
            parsed = {"message": raw or error.reason}
        return error.code, parsed


@contextmanager
def sqlite_connect():
    path = os.environ.get("DB_PATH", "/data/motore.sqlite")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def ok(status: int) -> bool:
    return status in (200, 201)


def already(status: int, result) -> bool:
    message = ""
    if isinstance(result, dict):
        message = str(result.get("message") or result.get("messageTranslation") or "")
    return status == 409 or "exist" in message.lower()


def metadata(espo, key: str):
    status, result = espo("GET", "/api/v1/Metadata", query={"key": key})
    if not ok(status):
        return None
    return result


def ensure_entity(espo) -> None:
    scope = metadata(espo, f"scopes.{ENTITY}")
    if not isinstance(scope, dict) or scope.get("type") != "BasePlus":
        status, result = espo(
            "POST",
            "/api/v1/EntityManager/action/createEntity",
            {
                "name": "Offerta",
                "type": "BasePlus",
                "labelSingular": "Opportunità",
                "labelPlural": "Opportunità",
                "stream": True,
                "color": "#2f6fad",
                "iconClass": "fas fa-chart-line",
                "kanbanViewMode": True,
            },
        )
        if not ok(status) and not already(status, result):
            raise RuntimeError(f"creazione scheda plus HTTP {status}: {result}")
    ensure_field(espo, "stage", {
        "name": "stage",
        "type": "enum",
        "label": "Fase",
        "options": STAGES,
        "default": "Prospecting",
        "style": {
            "Prospecting": None,
            "Qualification": "primary",
            "Proposal": "info",
            "Negotiation": "warning",
            "Closed Won": "success",
            "Closed Lost": "danger",
        },
    })
    ensure_field(espo, "amount", {"name": "amount", "type": "currency", "label": "Importo"})
    ensure_field(espo, "probability", {"name": "probability", "type": "int", "label": "Probabilità", "min": 0, "max": 100})
    ensure_field(espo, "closeDate", {"name": "closeDate", "type": "date", "label": "Chiusura"})
    ensure_field(espo, "externalKey", {"name": "externalKey", "type": "varchar", "label": "Chiave esterna", "maxLength": 180})
    ensure_link(espo, "account", "Account", "cOfferte", "Azienda", "Opportunità")
    ensure_link(espo, "contact", "Contact", "cOfferte", "Contatto", "Opportunità")
    ensure_link(espo, "documents", "Document", "cOfferte", "Documenti", "Opportunità", "manyToMany")
    espo(
        "POST",
        "/api/v1/EntityManager/action/updateEntity",
        {"name": ENTITY, "kanbanViewMode": True, "statusField": "stage"},
    )
    put_layouts(espo)


def ensure_field(espo, name: str, body: dict) -> None:
    fields = metadata(espo, f"entityDefs.{ENTITY}.fields") or {}
    if isinstance(fields, dict) and name in fields:
        return
    status, result = espo("POST", f"/api/v1/Admin/fieldManager/{ENTITY}", body)
    if not ok(status) and not already(status, result):
        raise RuntimeError(f"campo {name} HTTP {status}: {result}")


def ensure_link(espo, link: str, foreign: str, back: str, label: str, back_label: str, kind: str = "manyToOne") -> None:
    links = metadata(espo, f"entityDefs.{ENTITY}.links") or {}
    if isinstance(links, dict) and link in links and links[link].get("entity") == foreign:
        return
    status, result = espo(
        "POST",
        "/api/v1/EntityManager/action/createLink",
        {
            "entity": ENTITY,
            "link": link,
            "entityForeign": foreign,
            "linkForeign": back,
            "label": label,
            "labelForeign": back_label,
            "linkType": kind,
        },
    )
    if not ok(status) and not already(status, result):
        raise RuntimeError(f"collegamento {link} HTTP {status}: {result}")


def put_layouts(espo) -> None:
    detail = [
        {
            "label": "Opportunità",
            "rows": [
                [{"name": "name", "fullWidth": True}],
                [{"name": "account"}, {"name": "contact"}],
                [{"name": "stage"}, {"name": "probability"}],
                [{"name": "amount"}, {"name": "closeDate"}],
                [{"name": "description", "fullWidth": True}],
            ],
        }
    ]
    listing = [
        {"name": "name", "link": True},
        {"name": "account"},
        {"name": "stage"},
        {"name": "amount"},
        {"name": "closeDate"},
    ]
    for kind, payload in (("detail", detail), ("list", listing)):
        status, result = espo("PUT", f"/api/v1/{ENTITY}/layout/{kind}", payload)
        if not ok(status):
            raise RuntimeError(f"layout {kind} HTTP {status}: {result}")


def list_all(espo, entity: str, select: str) -> list[dict]:
    rows = []
    offset = 0
    while True:
        status, result = espo(
            "GET",
            f"/api/v1/{entity}",
            query={"select": select, "maxSize": "100", "offset": str(offset)},
        )
        if not ok(status) or not isinstance(result, dict):
            raise RuntimeError(f"lettura {entity} HTTP {status}: {result}")
        batch = result.get("list") or []
        rows.extend(batch)
        if len(rows) >= int(result.get("total") or 0) or not batch:
            return rows
        offset += len(batch)


def finish(connect, espo) -> None:
    ensure_entity(espo)
    copied = copy_records(espo)
    rewire_contracts(espo, copied)
    rewrite_pipelines(connect, copied)
    drop_old_link(espo)
    delete_old_records(espo, copied)
    hide_standard_tab(espo)
    build_home(espo)
    print("[motore] opportunità Base Plus pronta", len(copied))


def copy_records(espo) -> dict[str, str]:
    old = list_all(
        espo,
        "Opportunity",
        "id,name,stage,amount,amountCurrency,probability,closeDate,description,cExternalKey,accountId,contactId",
    )
    current = {
        row.get("externalKey"): row.get("id")
        for row in list_all(espo, ENTITY, "id,externalKey")
        if row.get("externalKey")
    }
    copied = dict(current)
    for row in old:
        key = row.get("cExternalKey")
        if not key or key in copied:
            if key:
                copied[key] = copied.get(key) or current.get(key)
            continue
        body = {
            "name": row.get("name"),
            "stage": row.get("stage"),
            "amount": row.get("amount"),
            "amountCurrency": row.get("amountCurrency") or "EUR",
            "probability": row.get("probability"),
            "closeDate": row.get("closeDate"),
            "description": row.get("description"),
            "externalKey": key,
            "accountId": row.get("accountId"),
            "contactId": row.get("contactId"),
        }
        body = {name: value for name, value in body.items() if value not in (None, "")}
        status, result = espo("POST", f"/api/v1/{ENTITY}", body)
        if not ok(status) or not isinstance(result, dict):
            raise RuntimeError(f"copia offerta HTTP {status}: {result}")
        copied[key] = result["id"]
    return copied


def rewire_contracts(espo, copied: dict[str, str]) -> None:
    links = metadata(espo, "entityDefs.CContratto.links") or {}
    if not isinstance(links, dict) or links.get("offerta", {}).get("entity") != ENTITY:
        status, result = espo(
            "POST",
            "/api/v1/EntityManager/action/createLink",
            {
                "entity": "CContratto",
                "link": "offerta",
                "entityForeign": ENTITY,
                "linkForeign": "cContratti",
                "label": "Opportunità",
                "labelForeign": "Contratti",
                "linkType": "manyToOne",
            },
        )
        if not ok(status) and not already(status, result):
            raise RuntimeError(f"collegamento contratto HTTP {status}: {result}")
    if "opportunity" not in (links or {}):
        return
    contracts = list_all(espo, "CContratto", "id,opportunityId,externalKey")
    opportunities = {
        row["id"]: row.get("cExternalKey")
        for row in list_all(espo, "Opportunity", "id,cExternalKey")
    }
    for contract in contracts:
        old_id = contract.get("opportunityId")
        key = opportunities.get(old_id)
        new_id = copied.get(key) if key else None
        if not new_id:
            continue
        status, result = espo("PUT", f"/api/v1/CContratto/{contract['id']}", {"offertaId": new_id})
        if not ok(status):
            raise RuntimeError(f"contratto {contract['id']} HTTP {status}: {result}")


def rewrite_pipelines(connect, copied: dict[str, str]) -> None:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, espo_entity, mapping_json FROM pipeline "
            "WHERE espo_entity = 'Opportunity' OR mapping_json LIKE '%Opportunity%'"
        ).fetchall()
        for row in rows:
            mapping = json.loads(row["mapping_json"])
            for rule in mapping:
                if rule.get("lookupEntity") == "Opportunity":
                    rule["lookupEntity"] = ENTITY
                    rule["lookupBy"] = "externalKey"
                    if rule.get("to") == "opportunityId":
                        rule["to"] = "offertaId"
                if rule.get("from") == "cExternalKey" and row["espo_entity"] == "Opportunity":
                    rule["from"] = "externalKey"
            if row["espo_entity"] == "Opportunity":
                conn.execute(
                    "UPDATE pipeline SET espo_entity = ?, key_field = ?, mapping_json = ? WHERE id = ?",
                    (ENTITY, "externalKey", json.dumps(mapping, ensure_ascii=False), row["id"]),
                )
            else:
                conn.execute(
                    "UPDATE pipeline SET mapping_json = ? WHERE id = ?",
                    (json.dumps(mapping, ensure_ascii=False), row["id"]),
                )
        queued = conn.execute(
            "SELECT external_id FROM queue_item WHERE pipeline_id = 'offerte-commerciali'"
        ).fetchall()
        for item in queued:
            new_id = copied.get(f"offerte-commerciali:{item['external_id']}")
            if new_id:
                conn.execute(
                    "UPDATE queue_item SET espo_id = ? WHERE pipeline_id = 'offerte-commerciali' AND external_id = ?",
                    (new_id, item["external_id"]),
                )


def drop_old_link(espo) -> None:
    links = metadata(espo, "entityDefs.CContratto.links") or {}
    if not isinstance(links, dict) or "opportunity" not in links:
        return
    status, result = espo(
        "POST",
        "/api/v1/EntityManager/action/removeLink",
        {"entity": "CContratto", "link": "opportunity"},
    )
    if not ok(status):
        raise RuntimeError(f"rimozione collegamento vecchio HTTP {status}: {result}")


def delete_old_records(espo, copied: dict[str, str]) -> None:
    old = list_all(espo, "Opportunity", "id,cExternalKey")
    for row in old:
        if row.get("cExternalKey") not in copied:
            continue
        espo("DELETE", f"/api/v1/Opportunity/{row['id']}")


def hide_standard_tab(espo) -> None:
    status, settings = espo("GET", "/api/v1/Settings")
    if not ok(status) or not isinstance(settings, dict):
        return
    tabs = list(settings.get("tabList") or [])
    changed = False
    if "Opportunity" in tabs:
        tabs = [tab for tab in tabs if tab != "Opportunity"]
        changed = True
    if ENTITY not in tabs:
        tabs.append(ENTITY)
        changed = True
    if changed:
        espo("PUT", "/api/v1/Settings", {"tabList": tabs})


def not_in(field: str, values: list[str]) -> dict:
    return {"name": field, "params": {"type": "notIn", "value": values}}


def equals(field: str, value: str) -> dict:
    return {"name": field, "params": {"type": "equals", "value": value}}


def find_report(espo, name: str):
    status, result = espo(
        "GET",
        "/api/v1/Report",
        query={
            "maxSize": "1",
            "where[0][type]": "equals",
            "where[0][attribute]": "name",
            "where[0][value]": name,
        },
    )
    if ok(status) and isinstance(result, dict) and result.get("list"):
        return result["list"][0]
    return None


def ensure_report(espo, body: dict) -> dict:
    found = find_report(espo, body["name"])
    if found:
        status, result = espo("PUT", f"/api/v1/Report/{found['id']}", body)
    else:
        status, result = espo("POST", "/api/v1/Report", body)
    if not ok(status) or not isinstance(result, dict):
        raise RuntimeError(f"report {body['name']} HTTP {status}: {result}")
    return result


def build_home(espo) -> None:
    pipeline = ensure_report(espo, {
        "name": "Pipeline aperto per fase",
        "entityType": ENTITY,
        "type": "Grid",
        "columns": ["SUM:amount", "COUNT:id"],
        "groupBy": ["stage"],
        "orderBy": ["SUM:amount"],
        "chartType": "BarHorizontal",
        "columnsData": {
            "SUM:amount": {"label": "Valore"},
            "COUNT:id": {"label": "Numero"},
        },
        "filtersData": None,
        "filtersDataList": [not_in("stage", CLOSED)],
    })
    tickets = ensure_report(espo, {
        "name": "Ticket aperti per priorità",
        "entityType": "Case",
        "type": "Grid",
        "columns": ["COUNT:id"],
        "groupBy": ["priority"],
        "chartType": "Pie",
        "columnsData": {"COUNT:id": {"label": "Ticket"}},
        "filtersData": None,
        "filtersDataList": [not_in("status", ["Closed", "Rejected", "Duplicate"])],
    })
    offers = ensure_report(espo, {
        "name": "Offerte da chiudere",
        "entityType": ENTITY,
        "type": "List",
        "columns": ["name", "account", "stage", "amount", "closeDate"],
        "orderBy": ["closeDate"],
        "filtersData": None,
        "filtersDataList": [not_in("stage", CLOSED)],
    })
    visits = ensure_report(espo, {
        "name": "Visite in agenda",
        "entityType": "Meeting",
        "type": "List",
        "columns": ["name", "account", "status", "dateStart"],
        "orderBy": ["dateStart"],
        "filtersData": None,
        "filtersDataList": [equals("status", "Planned")],
    })
    check_report(espo, pipeline, "run")
    check_report(espo, tickets, "run")
    check_report(espo, offers, "runList")
    check_report(espo, visits, "runList")
    place_dashboard(espo, [
        ("pipeline", "Pipeline aperto", pipeline, "Chart-Total", "SUM:amount", 0, 0),
        ("ticket", "Ticket aperti", tickets, "Chart", "COUNT:id", 2, 0),
        ("offerte", "Offerte da chiudere", offers, "List", None, 0, 4),
        ("visite", "Visite in agenda", visits, "List", None, 2, 4),
    ])


def check_report(espo, report: dict, action: str) -> None:
    status, result = espo("GET", f"/api/v1/Report/action/{action}", query={"id": report["id"]})
    if not ok(status):
        raise RuntimeError(f"report {report.get('name')} non gira HTTP {status}: {result}")


def place_dashboard(espo, items: list) -> None:
    status, user = espo("GET", "/api/v1/App/user")
    if not ok(status):
        raise RuntimeError(f"utente HTTP {status}")
    user_id = (user.get("user") or {}).get("id")
    layout = []
    options = {}
    for key, title, report, display, column, x, y in items:
        dashlet_id = f"meridia-{key}"
        cell = {"id": dashlet_id, "name": "Report", "x": x, "y": y, "width": 2, "height": 4}
        layout.append(cell)
        option = {
            "title": title,
            "reportId": report["id"],
            "reportName": report["name"],
            "entityType": report.get("entityType"),
            "type": report.get("type"),
            "displayType": display,
            "useSiMultiplier": False,
        }
        if column:
            option["column"] = column
        options[dashlet_id] = option
    status, result = espo(
        "PUT",
        f"/api/v1/Preferences/{user_id}",
        {"dashboardLayout": [{"name": "Direzione", "layout": layout}], "dashletsOptions": options},
    )
    if not ok(status):
        raise RuntimeError(f"home HTTP {status}: {result}")


def main() -> None:
    finish(sqlite_connect, espo_request)


if __name__ == "__main__":
    main()
