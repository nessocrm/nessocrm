"""Demo Gruppo Meridia: i processi di un'impresa industriale, dati inventati."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

DEMO_DIR = Path(os.environ.get("DEMO_DIR", "/demo"))
MARKER = "anagrafiche-clienti-erp"


def seed_demo(connect, save_connection, save_pipeline, run_pipeline, ingest, scambio: Path, espo_request) -> None:
    if os.environ.get("DEMO_SEED", "1") != "1":
        return
    sql_path = DEMO_DIR / "meridia.sql"
    if not sql_path.is_file():
        print("[motore] demo Meridia assente, cartella", DEMO_DIR)
        return
    with connect() as conn:
        already = conn.execute("SELECT 1 FROM connection WHERE id = ?", (MARKER,)).fetchone()
        finished = conn.execute(
            "SELECT 1 FROM pipeline WHERE id = 'offerte-verso-il-portale' AND last_run IS NOT NULL"
        ).fetchone()
    if already and finished:
        print("[motore] demo Meridia già presente")
        return
    if already:
        print("[motore] demo Meridia da completare")
        resume_demo(connect, save_pipeline, run_pipeline, ingest, scambio, espo_request)
        return
    load_sql(sql_path)
    ids = create_links(save_connection)
    entities = create_rules(save_pipeline, ids)
    ensure_meeting_owner(connect, espo_request)
    run_in_order(run_pipeline, ingest, scambio, entities)
    with connect() as conn:
        for pipeline_id in (
            MARKER,
            "fornitori-e-partner-erp",
            "rubrica-commerciale",
            "sedi-dei-clienti",
            "offerte-commerciali",
            "contratti-quadro",
            "commesse-di-lavoro",
            "interventi-in-campo",
            "fatture-clienti",
            "ticket-di-assistenza",
            "offerte-verso-il-portale",
        ):
            conn.execute(
                "UPDATE pipeline SET schedule_minutes = 15 WHERE id = ?",
                (pipeline_id,),
            )
    print("[motore] demo Gruppo Meridia pronta")


def ensure_meeting_owner(connect, espo_request) -> None:
    code, data = espo_request("GET", "/api/v1/App/user")
    if code != 200 or not isinstance(data, dict):
        raise RuntimeError("utente Espo non disponibile")
    user_id = (data.get("user") or {}).get("id")
    if not user_id:
        raise RuntimeError("utente Espo senza id")
    with connect() as conn:
        row = conn.execute(
            "SELECT mapping_json FROM pipeline WHERE id = 'visite-commerciali'"
        ).fetchone()
        if row is None:
            return
        rules = json.loads(row["mapping_json"] if hasattr(row, "keys") else row[0])
        if any(rule.get("to") == "assignedUserId" for rule in rules):
            return
        rules.append({"from": "titolo", "to": "assignedUserId", "transform": f"const:{user_id}"})
        conn.execute(
            "UPDATE pipeline SET mapping_json = ? WHERE id = 'visite-commerciali'",
            (json.dumps(rules, ensure_ascii=False),),
        )


def resume_demo(connect, save_pipeline, run_pipeline, ingest, scambio: Path, espo_request) -> None:
    with connect() as conn:
        ids = {row["name"]: row["id"] for row in conn.execute("SELECT id, name FROM connection")}
        have = {row["id"] for row in conn.execute("SELECT id FROM pipeline")}
    if "visite-commerciali" not in have:
        save_pipeline({
            "name": "Visite commerciali",
            "direction": "in",
            "espoEntity": "Meeting",
            "externalIdField": "codice",
            "connectionId": ids["Visite commerciali"],
            "scheduleMinutes": 0,
            "mapping": [
                {"from": "titolo", "to": "name"},
                {"from": "inizio", "to": "dateStart"},
                {"from": "fine", "to": "dateEnd"},
                {"from": "stato", "to": "status"},
                {"from": "luogo", "to": "description"},
                link("chiave_account", "Account", "cExternalKey"),
            ],
        })
    if "richieste-dal-sito" not in have:
        save_pipeline({
            "name": "Richieste dal sito",
            "direction": "in",
            "espoEntity": "Lead",
            "externalIdField": "codice",
            "connectionId": ids["Richieste dal sito"],
            "scheduleMinutes": 0,
            "mapping": [
                {"from": "nome", "to": "firstName"},
                {"from": "cognome", "to": "lastName"},
                {"from": "email", "to": "emailAddress"},
                {"from": "stato", "to": "status"},
                {"from": "origine", "to": "source"},
                {"from": "azienda", "to": "accountName"},
                {"from": "nota", "to": "description"},
            ],
        })
    if "offerte-verso-il-portale" not in have:
        save_pipeline({
            "name": "Offerte verso il portale",
            "direction": "out",
            "espoEntity": "Opportunity",
            "externalIdField": "id",
            "connectionId": ids["Portale partner"],
            "scheduleMinutes": 0,
            "mapping": [
                {"from": "name", "to": "titolo"},
                {"from": "stage", "to": "fase"},
                {"from": "amount", "to": "importo"},
                {"from": "cExternalKey", "to": "chiave"},
            ],
        })
    ensure_meeting_owner(connect, espo_request)
    run_in_order(run_pipeline, ingest, scambio, {"ids": ids})
    with connect() as conn:
        for pipeline_id in (
            MARKER, "fornitori-e-partner-erp", "rubrica-commerciale", "sedi-dei-clienti",
            "offerte-commerciali", "contratti-quadro", "commesse-di-lavoro",
            "interventi-in-campo", "fatture-clienti", "ticket-di-assistenza",
            "offerte-verso-il-portale",
        ):
            conn.execute("UPDATE pipeline SET schedule_minutes = 15 WHERE id = ?", (pipeline_id,))
    print("[motore] demo Gruppo Meridia pronta")


def load_sql(path: Path) -> None:
    import pymysql

    script = path.read_text(encoding="utf-8")
    connection = pymysql.connect(
        host=os.environ.get("DEMO_DB_HOST", "db"),
        port=int(os.environ.get("DEMO_DB_PORT", "3306")),
        user=os.environ.get("DEMO_DB_ROOT_USER", "root"),
        password=os.environ.get("DEMO_DB_ROOT_PASSWORD", "locale-root"),
        connect_timeout=8,
        client_flag=pymysql.constants.CLIENT.MULTI_STATEMENTS,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(script)
            while cursor.nextset():
                pass
        connection.commit()
    finally:
        connection.close()


def db_config(query: str) -> dict:
    return {
        "host": os.environ.get("DEMO_DB_HOST", "db"),
        "port": int(os.environ.get("DEMO_DB_PORT", "3306")),
        "database": "meridia_erp",
        "user": os.environ.get("DEMO_DB_USER", "espocrm"),
        "password": os.environ.get("DEMO_DB_PASSWORD", "locale-db"),
        "query": query,
    }


def create_links(save_connection) -> dict:
    specs = [
        ("Anagrafiche clienti ERP", "database", db_config("SELECT codice, ragione_sociale, email, telefono, citta, sito, tipo, settore, nazione, nota FROM clienti")),
        ("Fornitori e partner ERP", "database", db_config("SELECT codice, ragione_sociale, email, telefono, citta, sito, tipo, settore, nazione, nota FROM partner")),
        ("Rubrica commerciale", "database", db_config("SELECT codice, nome, cognome, email, telefono, ruolo, chiave_account FROM contatti")),
        ("Sedi dei clienti", "database", db_config("SELECT codice, nome, indirizzo, chiave_account FROM sedi")),
        ("Offerte commerciali", "database", db_config("SELECT codice, titolo, fase, chiusura, importo, probabilita, chiave_account, chiave_contatto FROM offerte")),
        ("Contratti quadro", "database", db_config("SELECT codice, nome, stato, valore, decorrenza, scadenza, chiave_account, chiave_offerta FROM contratti")),
        ("Commesse di lavoro", "database", db_config("SELECT codice, nome, stato, valore, apertura, chiave_account, chiave_contratto FROM commesse")),
        ("Interventi in campo", "database", db_config("SELECT codice, nome, stato, data_prevista, tecnico, chiave_commessa, chiave_contatto FROM interventi")),
        ("Fatture clienti", "database", db_config("SELECT codice, nome, stato, importo, data_fattura, chiave_account, chiave_commessa FROM fatture")),
        ("Ticket di assistenza", "database", db_config("SELECT codice, nome, stato, priorita, tipo, nota, chiave_account, chiave_contatto FROM ticket")),
        ("Richieste commerciali", "csv", {}),
        ("Visite commerciali", "csv", {}),
        ("Richieste dal sito", "webhook", {}),
        ("Portale partner", "http", {"url": ""}),
    ]
    ids = {}
    for name, kind, config in specs:
        saved = save_connection({"name": name, "kind": kind, "config": config})
        ids[name] = saved["id"]
        print("[motore] demo collegamento", saved["id"])
    return ids


def link(source: str, foreign: str, lookup_by: str) -> dict:
    return {
        "from": source,
        "to": foreign[:1].lower() + foreign[1:],
        "role": "link",
        "lookupEntity": foreign,
        "lookupBy": lookup_by,
    }


def create_rules(save_pipeline, ids: dict) -> dict:
    account_fields = [
        {"from": "ragione_sociale", "to": "name"},
        {"from": "email", "to": "emailAddress"},
        {"from": "citta", "to": "billingAddressCity"},
        {"from": "nazione", "to": "billingAddressCountry"},
        {"from": "sito", "to": "website"},
        {"from": "tipo", "to": "type"},
        {"from": "settore", "to": "industry"},
        {"from": "nota", "to": "description"},
    ]
    steps = []

    def add(name, entity, external, mapping, connection, **extra):
        steps.append((name, {
            "name": name,
            "direction": "in",
            "espoEntity": entity,
            "externalIdField": external,
            "connectionId": ids[connection],
            "scheduleMinutes": 0,
            "mapping": mapping,
            **extra,
        }))

    add("Anagrafiche clienti ERP", "Account", "codice", account_fields, "Anagrafiche clienti ERP")
    add("Fornitori e partner ERP", "Account", "codice", account_fields, "Fornitori e partner ERP")
    add("Rubrica commerciale", "Contact", "codice", [
        {"from": "nome", "to": "firstName"},
        {"from": "cognome", "to": "lastName"},
        {"from": "email", "to": "emailAddress"},
        {"from": "ruolo", "to": "title"},
        link("chiave_account", "Account", "cExternalKey"),
    ], "Rubrica commerciale")
    add("Sedi dei clienti", "__new__", "codice", [
        {"from": "nome", "to": "name"},
        {"from": "indirizzo", "to": "Indirizzo"},
        link("chiave_account", "Account", "cExternalKey"),
    ], "Sedi dei clienti", newSingular="Sede", newPlural="Sedi")
    add("Offerte commerciali", "Opportunity", "codice", [
        {"from": "titolo", "to": "name"},
        {"from": "fase", "to": "stage"},
        {"from": "chiusura", "to": "closeDate"},
        {"from": "importo", "to": "amount"},
        {"from": "probabilita", "to": "probability"},
        link("chiave_account", "Account", "cExternalKey"),
        link("chiave_contatto", "Contact", "cExternalKey"),
    ], "Offerte commerciali")

    entities = {}
    for name, body in steps:
        saved = save_pipeline(body)
        entities[name] = saved["espoEntity"]
        print("[motore] demo integrazione", saved["id"], saved["espoEntity"])

    sede = entities["Sedi dei clienti"]
    following = [
        ("Contratti quadro", "__new__", "codice", [
            {"from": "nome", "to": "name"},
            {"from": "stato", "to": "Stato"},
            {"from": "valore", "to": "Valore"},
            {"from": "decorrenza", "to": "Decorrenza"},
            {"from": "scadenza", "to": "Scadenza"},
            link("chiave_account", "Account", "cExternalKey"),
            link("chiave_offerta", "Opportunity", "cExternalKey"),
        ], "Contratti quadro", {"newSingular": "Contratto", "newPlural": "Contratti"}),
    ]
    saved = save_pipeline({
        "name": following[0][0],
        "direction": "in",
        "espoEntity": following[0][1],
        "externalIdField": following[0][2],
        "connectionId": ids[following[0][4]],
        "scheduleMinutes": 0,
        "mapping": following[0][3],
        **following[0][5],
    })
    entities[saved["name"]] = saved["espoEntity"]
    contratto = saved["espoEntity"]
    print("[motore] demo integrazione", saved["id"], contratto)

    saved = save_pipeline({
        "name": "Commesse di lavoro",
        "direction": "in",
        "espoEntity": "__new__",
        "newSingular": "Commessa",
        "newPlural": "Commesse",
        "externalIdField": "codice",
        "connectionId": ids["Commesse di lavoro"],
        "scheduleMinutes": 0,
        "mapping": [
            {"from": "nome", "to": "name"},
            {"from": "stato", "to": "Stato"},
            {"from": "valore", "to": "Valore"},
            {"from": "apertura", "to": "Apertura"},
            link("chiave_account", "Account", "cExternalKey"),
            link("chiave_contratto", contratto, "externalKey"),
        ],
    })
    entities[saved["name"]] = saved["espoEntity"]
    commessa = saved["espoEntity"]
    print("[motore] demo integrazione", saved["id"], commessa)

    rest = [
        ("Interventi in campo", "__new__", "codice", [
            {"from": "nome", "to": "name"},
            {"from": "stato", "to": "Stato"},
            {"from": "data_prevista", "to": "Data prevista"},
            {"from": "tecnico", "to": "Tecnico"},
            link("chiave_commessa", commessa, "externalKey"),
            link("chiave_contatto", "Contact", "cExternalKey"),
        ], "Interventi in campo", {"newSingular": "Intervento", "newPlural": "Interventi"}),
        ("Fatture clienti", "__new__", "codice", [
            {"from": "nome", "to": "name"},
            {"from": "stato", "to": "Stato"},
            {"from": "importo", "to": "Importo"},
            {"from": "data_fattura", "to": "Data"},
            link("chiave_account", "Account", "cExternalKey"),
            link("chiave_commessa", commessa, "externalKey"),
        ], "Fatture clienti", {"newSingular": "Fattura", "newPlural": "Fatture"}),
        ("Ticket di assistenza", "Case", "codice", [
            {"from": "nome", "to": "name"},
            {"from": "stato", "to": "status"},
            {"from": "priorita", "to": "priority"},
            {"from": "tipo", "to": "type"},
            {"from": "nota", "to": "description"},
            link("chiave_account", "Account", "cExternalKey"),
            link("chiave_contatto", "Contact", "cExternalKey"),
        ], "Ticket di assistenza", {}),
        ("Richieste commerciali", "Lead", "codice", [
            {"from": "nome", "to": "firstName"},
            {"from": "cognome", "to": "lastName"},
            {"from": "email", "to": "emailAddress"},
            {"from": "stato", "to": "status"},
            {"from": "origine", "to": "source"},
            {"from": "azienda", "to": "accountName"},
            {"from": "nota", "to": "description"},
        ], "Richieste commerciali", {}),
        ("Visite commerciali", "Meeting", "codice", [
            {"from": "titolo", "to": "name"},
            {"from": "inizio", "to": "dateStart"},
            {"from": "fine", "to": "dateEnd"},
            {"from": "stato", "to": "status"},
            {"from": "luogo", "to": "description"},
            link("chiave_account", "Account", "cExternalKey"),
        ], "Visite commerciali", {}),
        ("Richieste dal sito", "Lead", "codice", [
            {"from": "nome", "to": "firstName"},
            {"from": "cognome", "to": "lastName"},
            {"from": "email", "to": "emailAddress"},
            {"from": "stato", "to": "status"},
            {"from": "origine", "to": "source"},
            {"from": "azienda", "to": "accountName"},
            {"from": "nota", "to": "description"},
        ], "Richieste dal sito", {}),
    ]
    for name, entity, external, mapping, connection, extra in rest:
        saved = save_pipeline({
            "name": name,
            "direction": "in",
            "espoEntity": entity,
            "externalIdField": external,
            "connectionId": ids[connection],
            "scheduleMinutes": 0,
            "mapping": mapping,
            **extra,
        })
        entities[name] = saved["espoEntity"]
        print("[motore] demo integrazione", saved["id"], saved["espoEntity"])

    saved = save_pipeline({
        "name": "Offerte verso il portale",
        "direction": "out",
        "espoEntity": "Opportunity",
        "externalIdField": "id",
        "connectionId": ids["Portale partner"],
        "scheduleMinutes": 0,
        "mapping": [
            {"from": "name", "to": "titolo"},
            {"from": "stage", "to": "fase"},
            {"from": "amount", "to": "importo"},
            {"from": "cExternalKey", "to": "chiave"},
        ],
    })
    entities[saved["name"]] = saved["espoEntity"]
    print("[motore] demo integrazione", saved["id"], "uscita")
    return {"ids": ids, "entities": entities, "sede": sede}


def copy_csv(scambio: Path, connection_id: str, filename: str) -> None:
    source = DEMO_DIR / "csv" / filename
    folder = scambio / connection_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "elaborati").mkdir(exist_ok=True)
    shutil.copy(source, folder / filename)


def run_in_order(run_pipeline, ingest, scambio: Path, created: dict) -> None:
    ids = created["ids"]
    order = [
        "anagrafiche-clienti-erp",
        "fornitori-e-partner-erp",
        "rubrica-commerciale",
        "sedi-dei-clienti",
        "offerte-commerciali",
        "contratti-quadro",
        "commesse-di-lavoro",
        "interventi-in-campo",
        "fatture-clienti",
        "ticket-di-assistenza",
    ]
    for pipeline_id in order:
        try:
            result = run_pipeline(pipeline_id)
            print("[motore] demo giro", pipeline_id, result)
        except Exception as error:
            print("[motore] demo giro", pipeline_id, error)
    copy_csv(scambio, ids["Richieste commerciali"], "richieste-commerciali.csv")
    copy_csv(scambio, ids["Visite commerciali"], "visite-commerciali.csv")
    for pipeline_id in ("richieste-commerciali", "visite-commerciali"):
        try:
            result = run_pipeline(pipeline_id)
            print("[motore] demo giro", pipeline_id, result)
        except Exception as error:
            print("[motore] demo giro", pipeline_id, error)
    payload = json.loads((DEMO_DIR / "webhook" / "richieste-sito.json").read_text(encoding="utf-8"))
    for record in payload:
        try:
            result = ingest("richieste-dal-sito", record)
            print("[motore] demo sito", result.get("status"), record.get("codice"))
        except Exception as error:
            print("[motore] demo sito", error)
    try:
        result = run_pipeline("offerte-verso-il-portale")
        print("[motore] demo uscita", result)
    except Exception as error:
        print("[motore] demo uscita", error)
