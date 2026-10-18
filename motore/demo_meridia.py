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
    promuovi = load_promuovi()
    try:
        promuovi.ensure_entity(espo_request)
    except Exception as error:
        print("[motore] scheda plus", error)
    with connect() as conn:
        already = conn.execute("SELECT 1 FROM connection WHERE id = ?", (MARKER,)).fetchone()
        finished = conn.execute(
            "SELECT 1 FROM pipeline WHERE id = 'offerte-verso-il-portale' AND last_run IS NOT NULL"
        ).fetchone()
    if already and finished:
        print("[motore] demo Meridia già presente")
    elif already:
        print("[motore] demo Meridia da completare")
        resume_demo(connect, save_pipeline, run_pipeline, ingest, scambio, espo_request)
    else:
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
    try:
        promuovi.finish(connect, espo_request)
    except Exception as error:
        print("[motore] scheda plus", error)
    try:
        complete_legacy(connect, save_connection, save_pipeline, run_pipeline, espo_request)
    finally:
        ensure_order(connect)
        ensure_euro(connect, espo_request)


DEMO_ORDER = {
    "fornitori-e-partner-erp": "anagrafiche-clienti-erp",
    "rubrica-commerciale": "fornitori-e-partner-erp",
    "sedi-dei-clienti": "rubrica-commerciale",
    "offerte-commerciali": "sedi-dei-clienti",
    "contratti-quadro": "offerte-commerciali",
    "commesse-di-lavoro": "contratti-quadro",
    "interventi-in-campo": "commesse-di-lavoro",
    "fatture-clienti": "commesse-di-lavoro",
    "ticket-di-assistenza": "rubrica-commerciale",
}


def ensure_euro(connect, espo_request) -> None:
    status, result = espo_request(
        "PUT",
        "/api/v1/Settings",
        {"defaultCurrency": "EUR", "baseCurrency": "EUR", "currencyList": ["EUR", "USD"]},
    )
    if status not in (200, 201):
        print("[motore] valuta", status, result)
    code, offers = espo_request(
        "GET",
        "/api/v1/COfferta",
        query={"select": "id,amountCurrency", "maxSize": "50"},
    )
    if code == 200 and isinstance(offers, dict):
        for row in offers.get("list") or []:
            if row.get("amountCurrency") == "EUR" or not row.get("id"):
                continue
            put, body = espo_request("PUT", f"/api/v1/COfferta/{row['id']}", {"amountCurrency": "EUR"})
            if put not in (200, 201):
                print("[motore] valuta offerta", row["id"], put, body)
    with connect() as conn:
        found = conn.execute(
            "SELECT mapping_json FROM pipeline WHERE id = 'offerte-commerciali'"
        ).fetchone()
        if found is None:
            return
        rules = json.loads(found["mapping_json"])
        if any(item.get("to") == "amountCurrency" for item in rules):
            return
        rules.append({"from": "_const", "to": "amountCurrency", "transform": "const:EUR"})
        conn.execute(
            "UPDATE pipeline SET mapping_json = ? WHERE id = 'offerte-commerciali'",
            (json.dumps(rules, ensure_ascii=False),),
        )


def ensure_order(connect) -> None:
    with connect() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(pipeline)")}
        if "depends_on" not in columns:
            return
        for pipeline_id, parent in DEMO_ORDER.items():
            conn.execute(
                """
                UPDATE pipeline SET depends_on = ?
                WHERE id = ? AND (depends_on IS NULL OR depends_on = '')
                """,
                (parent, pipeline_id),
            )


def load_promuovi():
    import importlib.util

    path = DEMO_DIR / "promuovi_offerta.py"
    spec = importlib.util.spec_from_file_location("promuovi_offerta", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
            "espoEntity": "COfferta",
            "externalIdField": "id",
            "connectionId": ids["Portale partner"],
            "scheduleMinutes": 0,
            "mapping": [
                {"from": "name", "to": "titolo"},
                {"from": "stage", "to": "fase"},
                {"from": "amount", "to": "importo"},
                {"from": "externalKey", "to": "chiave"},
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


def links(source: str, foreign: str, lookup_by: str, link_name: str) -> dict:
    return {
        "from": source,
        "to": link_name,
        "role": "links",
        "lookupEntity": foreign,
        "lookupBy": lookup_by,
    }


def parent(source: str, foreign: str, lookup_by: str) -> dict:
    return {
        "from": source,
        "to": "parent",
        "role": "parent",
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
    add("Offerte commerciali", "COfferta", "codice", [
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
            link("chiave_offerta", "COfferta", "externalKey"),
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
        "espoEntity": "COfferta",
        "externalIdField": "id",
        "connectionId": ids["Portale partner"],
        "scheduleMinutes": 0,
        "mapping": [
            {"from": "name", "to": "titolo"},
            {"from": "stage", "to": "fase"},
            {"from": "amount", "to": "importo"},
            {"from": "externalKey", "to": "chiave"},
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


LEGACY_MARK = "visibilita ok"
NE = "team-di-visibilita:TEAM-VNE"
LOM = "team-di-visibilita:TEAM-LOM"
ASS = "team-di-visibilita:TEAM-ASS"
AMM = "team-di-visibilita:TEAM-AMM"
DIR = "team-di-visibilita:TEAM-DIR"
CHIARA = "utenti-meridia:USR-chiara"
MARCO = "utenti-meridia:USR-marco"
ELENA = "utenti-meridia:USR-elena"
DAVIDE = "utenti-meridia:USR-davide"


def complete_legacy(connect, save_connection, save_pipeline, run_pipeline, espo_request) -> None:
    sql_path = DEMO_DIR / "meridia-organizzazione.sql"
    if not sql_path.is_file():
        print("[motore] organizzazione Meridia assente")
        return
    with connect() as conn:
        row = conn.execute("SELECT last_detail FROM pipeline WHERE id = 'modelli-email'").fetchone()
    if row and row["last_detail"] and LEGACY_MARK in row["last_detail"]:
        print("[motore] organizzazione Meridia già presente")
        return
    load_sql(sql_path)
    ensure_roles(espo_request)
    relax_target_list(connect)
    ids = ensure_org_links(connect, save_connection)
    ensure_org_rules(connect, save_pipeline, ids)
    for pipeline_id in (
        "team-di-visibilita",
        "cartelle-documenti",
        "categorie-conoscenza",
        "utenti-meridia",
        "documenti-cliente",
        "compiti-sulle-offerte",
        "compiti-sui-ticket",
        "chiamate-commerciali",
        "articoli-assistenza",
        "liste-fiera",
        "campagna-fiera",
        "modelli-email",
    ):
        try:
            result = run_pipeline(pipeline_id)
            print("[motore] demo organizzazione", pipeline_id, result)
        except Exception as error:
            print("[motore] demo organizzazione", pipeline_id, error)
            return
    link_fair_contacts(connect, espo_request)
    stamp_visibility(espo_request, connect)
    with connect() as conn:
        conn.execute(
            "UPDATE pipeline SET last_detail = TRIM(COALESCE(last_detail, '') || ' ' || ?) WHERE id = 'modelli-email'",
            (LEGACY_MARK,),
        )
    print("[motore] organizzazione Meridia pronta")


def ensure_org_links(connect, save_connection) -> dict:
    specs = [
        ("Team di visibilita", "SELECT codice, nome, descrizione FROM team"),
        ("Cartelle documenti", "SELECT codice, nome, descrizione FROM cartelle"),
        ("Categorie conoscenza", "SELECT codice, nome, descrizione FROM categorie"),
        ("Utenti Meridia", "SELECT codice, username, nome, cognome, email, titolo, tipo, password, attivo, avviso, chiave_team, chiave_ruolo FROM utenti"),
        ("Documenti cliente", "SELECT codice, nome, file, stato, tipo, pubblicazione, descrizione, chiave_cartella, chiave_account, chiave_offerta, chiave_team FROM documenti"),
        ("Compiti sulle offerte", "SELECT codice, nome, stato, priorita, scadenza, nota, chiave_padre, chiave_utente, chiave_team FROM compiti WHERE tipo_padre = 'COfferta'"),
        ("Compiti sui ticket", "SELECT codice, nome, stato, priorita, scadenza, nota, chiave_padre, chiave_utente, chiave_team FROM compiti WHERE tipo_padre = 'Case'"),
        ("Chiamate commerciali", "SELECT codice, nome, stato, inizio, fine, direzione, nota, chiave_account, chiave_contatto, chiave_utente, chiave_team FROM chiamate"),
        ("Articoli assistenza", "SELECT codice, nome, stato, corpo, chiave_categoria, chiave_team FROM articoli"),
        ("Liste fiera", "SELECT codice, nome, descrizione, chiave_contatti, chiave_team FROM liste"),
        ("Campagna fiera", "SELECT codice, nome, stato, tipo, inizio, fine, nota, chiave_lista, chiave_team FROM campagne"),
        ("Modelli email", "SELECT codice, nome, oggetto, corpo, html, stato FROM modelli"),
    ]
    with connect() as conn:
        ids = {row["name"]: row["id"] for row in conn.execute("SELECT id, name FROM connection")}
    for name, query in specs:
        if name in ids:
            continue
        saved = save_connection({"name": name, "kind": "database", "config": db_config(query)})
        ids[name] = saved["id"]
        print("[motore] demo collegamento", saved["id"])
    return ids


def ensure_org_rules(connect, save_pipeline, ids: dict) -> None:
    specs = [
        ("Team di visibilita", "Team", [
            {"from": "nome", "to": "name"},
            {"from": "descrizione", "to": "description"},
        ]),
        ("Cartelle documenti", "DocumentFolder", [
            {"from": "nome", "to": "name"},
            {"from": "descrizione", "to": "description"},
        ]),
        ("Categorie conoscenza", "KnowledgeBaseCategory", [
            {"from": "nome", "to": "name"},
            {"from": "descrizione", "to": "description"},
        ]),
        ("Utenti Meridia", "User", [
            {"from": "username", "to": "userName"},
            {"from": "nome", "to": "firstName"},
            {"from": "cognome", "to": "lastName"},
            {"from": "email", "to": "emailAddress"},
            {"from": "titolo", "to": "title"},
            {"from": "tipo", "to": "type"},
            {"from": "password", "to": "password"},
            {"from": "password", "to": "passwordConfirm"},
            {"from": "attivo", "to": "isActive"},
            {"from": "avviso", "to": "sendAccessInfo"},
            link("chiave_team", "Team", "cExternalKey"),
            links("chiave_team", "Team", "cExternalKey", "teams"),
            links("chiave_ruolo", "Role", "name", "roles"),
        ]),
        ("Documenti cliente", "Document", [
            {"from": "nome", "to": "name"},
            {"from": "file", "to": "file"},
            {"from": "stato", "to": "status"},
            {"from": "tipo", "to": "type"},
            {"from": "pubblicazione", "to": "publishDate"},
            {"from": "descrizione", "to": "description"},
            link("chiave_cartella", "DocumentFolder", "cExternalKey"),
            links("chiave_account", "Account", "cExternalKey", "accounts"),
            links("chiave_offerta", "COfferta", "externalKey", "cOfferte"),
            links("chiave_team", "Team", "cExternalKey", "teams"),
        ]),
        ("Compiti sulle offerte", "Task", [
            {"from": "nome", "to": "name"},
            {"from": "stato", "to": "status"},
            {"from": "priorita", "to": "priority"},
            {"from": "scadenza", "to": "dateEnd"},
            {"from": "nota", "to": "description"},
            parent("chiave_padre", "COfferta", "externalKey"),
            link("chiave_utente", "User", "cExternalKey"),
            links("chiave_team", "Team", "cExternalKey", "teams"),
        ]),
        ("Compiti sui ticket", "Task", [
            {"from": "nome", "to": "name"},
            {"from": "stato", "to": "status"},
            {"from": "priorita", "to": "priority"},
            {"from": "scadenza", "to": "dateEnd"},
            {"from": "nota", "to": "description"},
            parent("chiave_padre", "Case", "cExternalKey"),
            link("chiave_utente", "User", "cExternalKey"),
            links("chiave_team", "Team", "cExternalKey", "teams"),
        ]),
        ("Chiamate commerciali", "Call", [
            {"from": "nome", "to": "name"},
            {"from": "stato", "to": "status"},
            {"from": "inizio", "to": "dateStart"},
            {"from": "fine", "to": "dateEnd"},
            {"from": "direzione", "to": "direction"},
            {"from": "nota", "to": "description"},
            link("chiave_account", "Account", "cExternalKey"),
            links("chiave_contatto", "Contact", "cExternalKey", "contacts"),
            link("chiave_utente", "User", "cExternalKey"),
            links("chiave_team", "Team", "cExternalKey", "teams"),
        ]),
        ("Articoli assistenza", "KnowledgeBaseArticle", [
            {"from": "nome", "to": "name"},
            {"from": "stato", "to": "status"},
            {"from": "corpo", "to": "body"},
            links("chiave_categoria", "KnowledgeBaseCategory", "cExternalKey", "categories"),
            links("chiave_team", "Team", "cExternalKey", "teams"),
        ]),
        ("Liste fiera", "TargetList", [
            {"from": "nome", "to": "name"},
            {"from": "descrizione", "to": "description"},
            links("chiave_team", "Team", "cExternalKey", "teams"),
        ]),
        ("Campagna fiera", "Campaign", [
            {"from": "nome", "to": "name"},
            {"from": "stato", "to": "status"},
            {"from": "tipo", "to": "type"},
            {"from": "inizio", "to": "startDate"},
            {"from": "fine", "to": "endDate"},
            {"from": "nota", "to": "description"},
            links("chiave_lista", "TargetList", "cExternalKey", "targetLists"),
            links("chiave_team", "Team", "cExternalKey", "teams"),
        ]),
        ("Modelli email", "EmailTemplate", [
            {"from": "nome", "to": "name"},
            {"from": "oggetto", "to": "subject"},
            {"from": "corpo", "to": "body"},
            {"from": "html", "to": "isHtml"},
            {"from": "stato", "to": "status"},
        ]),
    ]
    with connect() as conn:
        have = {row["id"] for row in conn.execute("SELECT id FROM pipeline")}
    for name, entity, mapping in specs:
        pipeline_id = name.lower().replace(" ", "-")
        if pipeline_id in have:
            continue
        save_pipeline({
            "name": name,
            "direction": "in",
            "espoEntity": entity,
            "externalIdField": "codice",
            "connectionId": ids[name],
            "scheduleMinutes": 0,
            "mapping": mapping,
        })


def access(read: str, edit: str, delete: str = "no", create: str = "yes") -> dict:
    return {"create": create, "read": read, "edit": edit, "delete": delete, "stream": read}


def relax_target_list(connect) -> None:
    # Espo rifiuta contactsIds nel corpo della lista: il legame si fa dopo, un contatto alla volta.
    with connect() as conn:
        row = conn.execute("SELECT mapping_json FROM pipeline WHERE id = 'liste-fiera'").fetchone()
        if row is None:
            return
        rules = json.loads(row["mapping_json"])
        kept = [item for item in rules if item.get("to") != "contactsIds"]
        if len(kept) == len(rules):
            return
        conn.execute(
            "UPDATE pipeline SET mapping_json = ? WHERE id = 'liste-fiera'",
            (json.dumps(kept, ensure_ascii=False),),
        )


def link_fair_contacts(connect, espo_request) -> None:
    with connect() as conn:
        row = conn.execute(
            "SELECT espo_id FROM chiave WHERE entity = 'TargetList' AND external_key = 'liste-fiera:LST-1'"
        ).fetchone()
    if row is None:
        print("[motore] lista fiera assente")
        return
    for code in ("CNT-4101", "CNT-4102", "CNT-4107", "CNT-4110", "CNT-221"):
        contact = espo_find(espo_request, "Contact", "cExternalKey", f"rubrica-commerciale:{code}")
        if not contact:
            print("[motore] lista fiera, contatto assente", code)
            continue
        status, result = espo_request(
            "POST",
            f"/api/v1/TargetList/{row['espo_id']}/contacts",
            {"id": contact},
        )
        if status not in (200, 201):
            print("[motore] lista fiera", code, status, result)


def ensure_roles(espo_request) -> None:
    commercial = ["Account", "Contact", "Lead", "COfferta", "Meeting", "Call", "Task", "Document", "DocumentFolder", "Campaign", "TargetList", "CSede", "CContratto"]
    read_only = ["Case", "CCommessa", "CIntervento", "CFattura", "KnowledgeBaseArticle"]
    vendite = {name: access("team", "team") for name in commercial}
    vendite.update({name: access("team", "no", create="no") for name in read_only})
    vendite["User"] = access("team", "no", create="no")
    vendite["EmailTemplate"] = access("all", "no", create="no")
    assistenza = {
        "Account": access("team", "no", create="no"),
        "Contact": access("team", "no", create="no"),
        "CSede": access("team", "no", create="no"),
        "Case": access("team", "team"),
        "Meeting": access("team", "team"),
        "Call": access("team", "team"),
        "Task": access("team", "team"),
        "Document": access("team", "team"),
        "DocumentFolder": access("team", "no", create="no"),
        "CIntervento": access("team", "team"),
        "CCommessa": access("team", "team"),
        "KnowledgeBaseArticle": access("all", "team"),
        "KnowledgeBaseCategory": access("all", "no", create="no"),
        "User": access("team", "no", create="no"),
    }
    amministrazione = {
        "Account": access("team", "no", create="no"),
        "Contact": access("team", "no", create="no"),
        "CFattura": access("team", "team"),
        "CContratto": access("team", "team"),
        "CCommessa": access("team", "no", create="no"),
        "Document": access("team", "team"),
        "DocumentFolder": access("team", "no", create="no"),
        "Task": access("team", "team"),
        "KnowledgeBaseArticle": access("all", "no", create="no"),
        "User": access("team", "no", create="no"),
    }
    direzione = {
        name: access("all", "all")
        for name in [
            "Account", "Contact", "Lead", "COfferta", "Case", "Meeting", "Call", "Task",
            "Document", "DocumentFolder", "Campaign", "TargetList", "KnowledgeBaseArticle",
            "KnowledgeBaseCategory", "EmailTemplate", "Team",
            "CSede", "CContratto", "CCommessa", "CIntervento", "CFattura",
        ]
    }
    # Espo non ammette «modifica tutti» sugli utenti: al massimo il proprio.
    direzione["User"] = access("all", "own")
    specs = [
        ("Vendite", "team", vendite),
        ("Assistenza", "team", assistenza),
        ("Amministrazione", "team", amministrazione),
        ("Direzione", "team", direzione),
    ]
    for name, assignment, data in specs:
        code, found = espo_request(
            "GET",
            "/api/v1/Role",
            query={
                "maxSize": "1",
                "where[0][type]": "equals",
                "where[0][attribute]": "name",
                "where[0][value]": name,
            },
        )
        if code == 200 and isinstance(found, dict) and found.get("list"):
            continue
        status, result = espo_request(
            "POST",
            "/api/v1/Role",
            {
                "name": name,
                "assignmentPermission": assignment,
                "userPermission": "team",
                "messagePermission": "team",
                "portalPermission": "not-set",
                "exportPermission": "yes",
                "data": data,
                "fieldData": {},
            },
        )
        if status not in (200, 201):
            raise RuntimeError(f"ruolo {name} HTTP {status}: {result}")


def espo_find(espo_request, entity: str, field: str, value: str):
    code, result = espo_request(
        "GET",
        f"/api/v1/{entity}",
        query={
            "select": "id",
            "maxSize": "1",
            "where[0][type]": "equals",
            "where[0][attribute]": field,
            "where[0][value]": value,
        },
    )
    if code != 200 or not isinstance(result, dict):
        raise RuntimeError(f"ricerca {entity} HTTP {code}: {result}")
    rows = result.get("list") or []
    return rows[0]["id"] if rows else None


def stamp_visibility(espo_request, connect) -> None:
    def locate(entity: str, field: str, value: str):
        with connect() as conn:
            row = conn.execute(
                "SELECT espo_id FROM chiave WHERE entity = ? AND external_key = ?",
                (entity, value),
            ).fetchone()
        if row:
            return row["espo_id"]
        return espo_find(espo_request, entity, field, value)

    teams = {key: locate("Team", "cExternalKey", key) for key in (NE, LOM, ASS, AMM, DIR)}
    users = {key: locate("User", "cExternalKey", key) for key in (CHIARA, MARCO, ELENA, DAVIDE)}
    missing = [key for key, value in {**teams, **users}.items() if not value]
    if missing:
        raise RuntimeError("visibilità senza record: " + ", ".join(missing))

    def put(entity: str, key_field: str, key: str, team_keys: list[str], user_key: str | None = None) -> None:
        record = locate(entity, key_field, key)
        if not record:
            print("[motore] visibilità, record assente", entity, key)
            return
        body = {"teamsIds": [teams[item] for item in team_keys]}
        if user_key:
            body["assignedUserId"] = users[user_key]
        status, result = espo_request("PUT", f"/api/v1/{entity}/{record}", body)
        if status not in (200, 201):
            raise RuntimeError(f"visibilità {entity} {key} HTTP {status}: {result}")

    ne_accounts = ["CLI-4100", "CLI-4101", "CLI-4102", "CLI-4105", "CLI-4106"]
    lom_accounts = ["CLI-4103", "CLI-4104", "CLI-4107"]
    ne_partners = ["FOR-220", "FOR-223"]
    lom_partners = ["FOR-221", "FOR-222"]
    for code in ne_accounts:
        put("Account", "cExternalKey", f"anagrafiche-clienti-erp:{code}", [NE, ASS, AMM, DIR], CHIARA)
    for code in lom_accounts:
        put("Account", "cExternalKey", f"anagrafiche-clienti-erp:{code}", [LOM, ASS, AMM, DIR], MARCO)
    for code in ne_partners:
        put("Account", "cExternalKey", f"fornitori-e-partner-erp:{code}", [NE, DIR], CHIARA)
    for code in lom_partners:
        put("Account", "cExternalKey", f"fornitori-e-partner-erp:{code}", [LOM, DIR], MARCO)

    contact_owner = {
        "CNT-4100": (NE, CHIARA), "CNT-4101": (NE, CHIARA), "CNT-4102": (NE, CHIARA), "CNT-4103": (NE, CHIARA),
        "CNT-4104": (NE, CHIARA), "CNT-4105": (NE, CHIARA), "CNT-4108": (NE, CHIARA), "CNT-4109": (NE, CHIARA),
        "CNT-220": (NE, CHIARA), "CNT-223": (NE, CHIARA),
        "CNT-4106": (LOM, MARCO), "CNT-4107": (LOM, MARCO), "CNT-4110": (LOM, MARCO), "CNT-221": (LOM, MARCO),
    }
    for code, (team, user) in contact_owner.items():
        put("Contact", "cExternalKey", f"rubrica-commerciale:{code}", [team, ASS, DIR], user)

    for code in ("OFF-700", "OFF-701", "OFF-702", "OFF-705", "OFF-706"):
        put("COfferta", "externalKey", f"offerte-commerciali:{code}", [NE, DIR], CHIARA)
    for code in ("OFF-703", "OFF-704", "OFF-707"):
        put("COfferta", "externalKey", f"offerte-commerciali:{code}", [LOM, DIR], MARCO)
    for code in ("TCK-90", "TCK-91", "TCK-92", "TCK-93", "TCK-94", "TCK-95"):
        team = NE if code in ("TCK-90", "TCK-91", "TCK-92", "TCK-93", "TCK-94") else LOM
        put("Case", "cExternalKey", f"ticket-di-assistenza:{code}", [team, ASS, DIR], ELENA)
    for code, team, user in (
        ("VIS-1", NE, CHIARA), ("VIS-2", NE, CHIARA), ("VIS-3", NE, CHIARA),
        ("VIS-4", LOM, MARCO), ("VIS-5", LOM, MARCO),
    ):
        put("Meeting", "cExternalKey", f"visite-commerciali:{code}", [team, DIR], user)
    for code in ("LEAD-50", "LEAD-51", "LEAD-52", "LEAD-53", "LEAD-54", "LEAD-55", "LEAD-56", "LEAD-57"):
        put("Lead", "cExternalKey", f"richieste-commerciali:{code}", [NE, LOM, DIR], CHIARA)
    for code in ("WEB-77", "WEB-78"):
        put("Lead", "cExternalKey", f"richieste-dal-sito:{code}", [NE, LOM, DIR], CHIARA)
    for code in ("SED-1", "SED-2", "SED-3", "SED-4", "SED-5"):
        put("CSede", "externalKey", f"sedi-dei-clienti:{code}", [NE, ASS, DIR])
    for code in ("SED-6", "SED-7", "SED-8"):
        put("CSede", "externalKey", f"sedi-dei-clienti:{code}", [LOM, ASS, DIR])
    for code, team in (("CON-300", NE), ("CON-301", NE), ("CON-302", NE), ("CON-303", LOM), ("CON-304", LOM)):
        put("CContratto", "externalKey", f"contratti-quadro:{code}", [team, AMM, DIR], DAVIDE)
    for code, team in (("COM-800", NE), ("COM-801", NE), ("COM-802", NE), ("COM-803", NE), ("COM-804", LOM), ("COM-805", LOM)):
        put("CCommessa", "externalKey", f"commesse-di-lavoro:{code}", [team, ASS, DIR], ELENA)
    for code, team in (("INT-1", NE), ("INT-2", NE), ("INT-3", NE), ("INT-4", NE), ("INT-5", LOM), ("INT-6", LOM)):
        put("CIntervento", "externalKey", f"interventi-in-campo:{code}", [team, ASS, DIR], ELENA)
    for code, team in (
        ("FAT-2026-118", NE), ("FAT-2026-104", NE), ("FAT-2026-097", NE),
        ("FAT-2026-088", NE), ("FAT-2026-110", NE), ("FAT-2026-121", LOM),
    ):
        put("CFattura", "externalKey", f"fatture-clienti:{code}", [team, AMM, DIR], DAVIDE)

    admin = espo_find(espo_request, "User", "userName", "admin")
    if admin and teams[DIR]:
        code, current = espo_request("GET", f"/api/v1/User/{admin}")
        owned = list((current or {}).get("teamsIds") or []) if code == 200 else []
        if teams[DIR] not in owned:
            owned.append(teams[DIR])
            espo_request("PUT", f"/api/v1/User/{admin}", {"teamsIds": owned})
