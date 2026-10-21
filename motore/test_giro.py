import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(tempfile.mkdtemp())
os.environ["DB_PATH"] = str(ROOT / "motore.sqlite")
os.environ["SCAMBIO_DIR"] = str(ROOT / "scambio")

import app

REAL_REQUEST = app.espo_request


class Row(dict):
    pass


class Giro(unittest.TestCase):
    def setUp(self):
        app.DB_PATH = Path(os.environ["DB_PATH"])
        app.SCAMBIO = Path(os.environ["SCAMBIO_DIR"])
        app.init_db()
        with app.connect() as conn:
            conn.execute("DELETE FROM pipeline")
            conn.execute("DELETE FROM connection")
            conn.execute("DELETE FROM chiave")
            conn.execute("DELETE FROM run_log")
            conn.execute("DELETE FROM badge_state")
            conn.execute("DELETE FROM scarto")
            conn.execute("DELETE FROM queue_item")
            conn.execute("DELETE FROM presenza")
            conn.execute("DELETE FROM field_history")
            conn.execute("DELETE FROM watch_item")
            conn.execute("DELETE FROM silence_window")
            conn.execute("DELETE FROM silence_payload")
            conn.execute("DELETE FROM plan_step")
            conn.execute("DELETE FROM stage_proposal")
            conn.execute("DELETE FROM actor")
            conn.execute("DELETE FROM session")
            conn.execute("DELETE FROM notice")
            conn.execute(
                "DELETE FROM setting WHERE key IN ('espo_service_user', 'espo_service_secret', 'espo_service_label', 'espo_role_id', 'espo_role_entities')"
            )
            conn.execute("UPDATE setting SET value = '1' WHERE key = 'writes'")

    def test_orario_fisso_sul_giro(self):
        row = Row(enabled=1, schedule_at="02:10", schedule_minutes=0, last_run="2026-10-18 02:12:00")
        moment = datetime(2026, 10, 19, 2, 15, 0).timestamp()
        self.assertTrue(app.pipeline_due(row, moment))
        row["last_run"] = "2026-10-19 02:12:00"
        self.assertFalse(app.pipeline_due(row, moment))

    def test_quindici_minuti_partono_una_volta(self):
        row = Row(enabled=1, schedule_minutes=15, last_run="2026-10-21 08:00:00")
        almost = datetime(2026, 10, 21, 8, 14, 59).timestamp()
        due = datetime(2026, 10, 21, 8, 15, 0).timestamp()
        self.assertFalse(app.pipeline_due(row, almost))
        self.assertTrue(app.pipeline_due(row, due))
        row["last_run"] = "2026-10-21 08:15:00"
        self.assertFalse(app.pipeline_due(row, due))
        five = Row(enabled=1, schedule_minutes=5, last_run="2026-10-21 08:00:00")
        self.assertTrue(app.pipeline_due(five, datetime(2026, 10, 21, 8, 5, 0).timestamp()))
        hour = Row(enabled=1, schedule_minutes=60, last_run="2026-10-21 08:00:00")
        self.assertFalse(app.pipeline_due(hour, due))

    def test_il_file_senza_colonna_non_si_sposta(self):
        folder = app.SCAMBIO / "anagrafiche"
        folder.mkdir(parents=True)
        (folder / "clienti.csv").write_text("nome;citta\nNord;Treviso\n", encoding="utf-8")
        with app.connect() as conn:
            conn.execute(
                """
                INSERT INTO connection (id, name, kind, config_json, token)
                VALUES ('anagrafiche', 'File', 'csv', '{}', 'tok')
                """
            )
            conn.execute(
                """
                INSERT INTO pipeline
                (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field, connection_id)
                VALUES ('clienti', 'Clienti', 'in', 'Account', 'codice', 'clienti:{codice}', ?, 'cExternalKey', 'anagrafiche')
                """,
                ('[{"from":"codice","to":"name","transform":"copy","owner":"sorgente"}]',),
            )
        result = app.execute_pipeline("clienti")
        self.assertEqual(result["failed"], 1)
        self.assertTrue((folder / "clienti.csv").is_file())
        self.assertEqual(list((folder / "elaborati").glob("*.csv")), [])
        with app.connect() as conn:
            detail = conn.execute("SELECT detail FROM scarto").fetchone()["detail"]
        self.assertIn("manca la colonna codice", detail)

    def test_interruttore_non_scrive(self):
        calls = []

        def fake(method, path, body=None, query=None):
            calls.append(method)
            return 201, {"id": "esp-1"}

        app.espo_request = fake
        app.set_setting("writes", "0")
        with app.connect() as conn:
            conn.execute(
                """
                INSERT INTO pipeline
                (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field)
                VALUES ('clienti', 'Clienti', 'in', 'Account', 'codice', 'clienti:{codice}', ?, 'cExternalKey')
                """,
                ('[{"from":"nome","to":"name","transform":"copy","owner":"sorgente"}]',),
            )
        item = app.ingest("clienti", {"codice": "1", "nome": "Nord"})
        self.assertEqual(item["status"], "lettura")
        self.assertEqual(item["would"], "creato")
        self.assertNotIn("POST", calls)
        self.assertNotIn("PUT", calls)

    def test_la_mattina_non_mostra_il_successo_di_ieri(self):
        morning = app.registry_morning(
            [{
                "direction": "in",
                "espo_entity": "Account",
                "name": "Clienti",
                "counts": {"created": 0, "updated": 0, "unchanged": 2, "failed": 1, "queued": 0},
                "last_success": "2026-10-18 02:12:00",
                "last_run": "2026-10-19 02:15:00",
                "last_status": "errore",
            }],
            datetime(2026, 10, 19, 8, 0, 0),
        )
        self.assertIsNone(morning["percent"])
        self.assertIn("non è riuscito", morning["text"])
        self.assertNotIn("75%", morning["text"])

    def test_quadratura_non_scrive(self):
        calls = []
        app.espo_request = lambda *args, **kwargs: calls.append(args) or (201, {"id": "x"})
        folder = app.SCAMBIO / "anagrafiche"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "clienti.csv").write_text("codice;nome\n1;Nord\n2;Sud\n", encoding="utf-8")
        with app.connect() as conn:
            conn.execute(
                "INSERT INTO connection (id, name, kind, config_json, token) VALUES ('anagrafiche', 'File', 'csv', '{}', 'tok')"
            )
            conn.execute(
                """
                INSERT INTO pipeline
                (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field, connection_id)
                VALUES ('clienti', 'Clienti', 'in', 'Account', 'codice', 'clienti:{codice}', ?, 'cExternalKey', 'anagrafiche')
                """,
                ('[{"from":"codice","to":"name","transform":"copy","owner":"sorgente"}]',),
            )
            conn.execute(
                "INSERT INTO chiave (entity, external_key, espo_id) VALUES ('Account', 'clienti:1', 'esp-1')"
            )
        result = app.measure_balance("clienti")
        self.assertEqual(result["sourceCount"], 2)
        self.assertEqual(result["espoCount"], 1)
        self.assertFalse(result["ok"])
        self.assertEqual(calls, [])
        self.assertTrue((folder / "clienti.csv").is_file())

    def test_file_di_ieri_non_si_rilancia_e_il_rosso_aspetta_un_giro(self):
        folder = app.SCAMBIO / "notte"
        done = folder / "elaborati"
        done.mkdir(parents=True)
        (done / "20261018-clienti.csv").write_text("codice;nome\n1;Nord\n", encoding="utf-8")
        with app.connect() as conn:
            conn.execute(
                "INSERT INTO connection (id, name, kind, config_json, token) VALUES ('notte', 'Notte', 'csv', '{}', 'tok')"
            )
            conn.execute(
                """
                INSERT INTO pipeline
                (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field, connection_id, expect_at, last_success)
                VALUES ('clienti', 'Clienti', 'in', 'Account', 'codice', 'clienti:{codice}', ?, 'cExternalKey', 'notte', '07:00', '2026-10-18 02:12:00')
                """,
                ('[{"from":"nome","to":"name","transform":"copy","owner":"sorgente"}]',),
            )
        noted = app.notice_absent(datetime(2026, 10, 19, 7, 1, 0))
        self.assertEqual(noted, ["clienti"])
        app.execute_pipeline("clienti")
        self.assertTrue((done / "20261018-clienti.csv").is_file())
        with app.connect() as conn:
            alert = conn.execute("SELECT file_alert FROM pipeline WHERE id = 'clienti'").fetchone()["file_alert"]
            detail = conn.execute("SELECT detail FROM run_log WHERE status = 'mancante'").fetchone()["detail"]
        self.assertEqual(alert, 1)
        self.assertIn("non arrivato", detail)
        calls = []

        def fake(method, path, body=None, query=None):
            calls.append((method, body))
            if method == "GET":
                return 200, {"list": []}
            return 201, {"id": "esp-9"}

        app.espo_request = fake
        (folder / "clienti.csv").write_text("codice;nome\n9;Sud\n", encoding="utf-8")
        app.execute_pipeline("clienti")
        bodies = [body for method, body in calls if method in ("POST", "PUT") and isinstance(body, dict)]
        self.assertTrue(any("aggiornato dal gestionale" in str(body.get("cNessoBadge", "")) for body in bodies))
        with app.connect() as conn:
            success = conn.execute("SELECT last_success, file_alert FROM pipeline WHERE id = 'clienti'").fetchone()
        self.assertTrue(success["last_success"])
        self.assertEqual(success["file_alert"], 0)

    def test_il_ritocco_di_chiara_non_viene_dalla_sorgente(self):
        mapped = app.map_payload(
            [
                {"from": "origine", "to": "cNessoBadge", "transform": "copy"},
                {"from": "nome", "to": "name", "transform": "copy"},
            ],
            {"origine": "dal file", "nome": "Nord"},
            "clienti:1",
            "cExternalKey",
            dry=True,
        )
        self.assertNotIn("cNessoBadge", mapped)
        calls = []

        def fake(method, path, body=None, query=None):
            calls.append(body)
            return 200, {"id": "esp-1"}

        app.espo_request = fake
        app.remember_badge("esp-1", "2026-10-19 02:12:00", "gestionale", "aggiornato dal gestionale")
        changed = app.apply_person_badges("Account", [{
            "id": "esp-1",
            "modifiedAt": "2026-10-19 09:40:00",
            "modifiedByName": "Chiara Fabbri",
        }])
        self.assertEqual(changed, 1)
        bodies = [body for body in calls if isinstance(body, dict)]
        self.assertEqual(set(bodies[0]), {"cNessoBadge"})
        self.assertIn("Chiara Fabbri", bodies[0]["cNessoBadge"])
        again = app.apply_person_badges("Account", [{
            "id": "esp-1",
            "modifiedAt": "2026-10-19 09:41:00",
            "modifiedByName": "Admin",
        }])
        self.assertEqual(again, 0)

    def _clienti_csv(self, text):
        folder = app.SCAMBIO / "coda"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "clienti.csv").write_text(text, encoding="utf-8")
        with app.connect() as conn:
            conn.execute(
                "INSERT INTO connection (id, name, kind, config_json, token) VALUES ('coda', 'File', 'csv', '{}', 'tok')"
            )
            conn.execute(
                """
                INSERT INTO pipeline
                (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field, connection_id, enabled)
                VALUES ('clienti', 'Clienti', 'in', 'Account', 'codice', 'clienti:{codice}', ?, 'cExternalKey', 'coda', 1)
                """,
                ('[{"from":"codice","to":"name","transform":"copy","owner":"sorgente"}]',),
            )
        return folder

    def test_la_finestra_non_tocca_il_file_e_non_chiama_espo(self):
        calls = []
        app.espo_request = lambda *args, **kwargs: calls.append(args) or (201, {"id": "x"})
        folder = self._clienti_csv("codice;nome\n1;Nord\n")
        app.save_silence({"start": "2026-10-01", "end": "2026-12-31", "reason": "inventario", "pipelineId": "clienti"})
        result = app.run_pipeline("clienti")
        self.assertEqual(result["silence"], "attesa")
        self.assertTrue((folder / "clienti.csv").is_file())
        self.assertEqual(list((folder / "elaborati").glob("*.csv")), [])
        self.assertEqual(calls, [])
        with app.connect() as conn:
            held = conn.execute("SELECT silence_held FROM pipeline WHERE id = 'clienti'").fetchone()["silence_held"]
        self.assertEqual(held, 1)

    def test_dopo_la_finestra_il_file_resta_fermo(self):
        calls = []
        app.espo_request = lambda *args, **kwargs: calls.append(args) or (201, {"id": "x"})
        folder = self._clienti_csv("codice;nome\n1;Nord\n")
        with app.connect() as conn:
            conn.execute("UPDATE pipeline SET silence_held = 1 WHERE id = 'clienti'")
        result = app.run_pipeline("clienti")
        self.assertEqual(result["silence"], "fermo")
        self.assertTrue((folder / "clienti.csv").is_file())
        self.assertEqual(calls, [])

    def test_scartare_il_file_non_scrive(self):
        calls = []
        app.espo_request = lambda *args, **kwargs: calls.append(args) or (201, {"id": "x"})
        folder = self._clienti_csv("codice;nome\n1;Nord\n")
        with app.connect() as conn:
            conn.execute("UPDATE pipeline SET silence_held = 1 WHERE id = 'clienti'")
        result = app.discard_silence("clienti")
        self.assertEqual(result["discarded"], 1)
        self.assertFalse((folder / "clienti.csv").is_file())
        self.assertEqual(len(list((folder / "scartati").glob("*.csv"))), 1)
        self.assertEqual(calls, [])
        with app.connect() as conn:
            held = conn.execute("SELECT silence_held FROM pipeline WHERE id = 'clienti'").fetchone()["silence_held"]
        self.assertEqual(held, 0)

    def test_il_piano_non_accende_il_gradino_dopo(self):
        with app.connect() as conn:
            for pipeline_id, name, enabled in (("anagrafiche", "Anagrafiche", 0), ("contatti", "Contatti", 0)):
                conn.execute(
                    """
                    INSERT INTO pipeline
                    (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field, enabled)
                    VALUES (?, ?, 'in', 'Account', 'codice', ?, '[]', 'cExternalKey', ?)
                    """,
                    (pipeline_id, name, pipeline_id + ":{codice}", enabled),
                )
        app.save_plan({"steps": ["anagrafiche", "contatti"]})
        with self.assertRaises(RuntimeError):
            app.set_enabled("contatti", True)
        with app.connect() as conn:
            enabled = conn.execute("SELECT enabled FROM pipeline WHERE id = 'contatti'").fetchone()["enabled"]
        self.assertEqual(enabled, 0)
        app.anteprima("anagrafiche")
        confirmed = app.confirm_step("anagrafiche")
        self.assertTrue(confirmed["confirmed"])
        self.assertFalse(confirmed["nextEnabled"])
        app.set_enabled("contatti", True)
        with app.connect() as conn:
            enabled = conn.execute("SELECT enabled FROM pipeline WHERE id = 'contatti'").fetchone()["enabled"]
            first = conn.execute("SELECT enabled FROM pipeline WHERE id = 'anagrafiche'").fetchone()["enabled"]
        self.assertEqual(enabled, 1)
        self.assertEqual(first, 0)

    def test_il_webhook_in_finestra_non_scrive(self):
        calls = []
        app.espo_request = lambda *args, **kwargs: calls.append(args) or (201, {"id": "x"})
        with app.connect() as conn:
            conn.execute(
                "INSERT INTO connection (id, name, kind, config_json, token) VALUES ('gancio', 'Gancio', 'webhook', '{}', 'tok')"
            )
            conn.execute(
                """
                INSERT INTO pipeline
                (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field, connection_id, enabled)
                VALUES ('gancio', 'Gancio', 'in', 'Account', 'codice', 'gancio:{codice}', ?, 'cExternalKey', 'gancio', 1)
                """,
                ('[{"from":"codice","to":"name","transform":"copy","owner":"sorgente"}]',),
            )
        app.save_silence({"start": "2026-10-01", "end": "2026-12-31", "reason": "fiera"})
        result = app.accept_hook("gancio", "tok", {"codice": "1", "nome": "Nord"})
        self.assertEqual(result["results"][0]["status"], "attesa")
        self.assertEqual(calls, [])

    def test_senza_finestra_il_giro_arriva_al_file(self):
        folder = self._clienti_csv("nome;citta\nNord;Treviso\n")
        result = app.run_pipeline("clienti")
        self.assertEqual(result["failed"], 1)
        self.assertNotIn("silence", result)
        self.assertTrue((folder / "clienti.csv").is_file())

    def test_due_societa_aggiornano_e_non_duplicano(self):
        saved = (app.espo_request, app.scope_customizable, app.scope_is_custom, app.publish_field_name)
        calls = []

        def fake(method, path, body=None, query=None):
            calls.append(method)
            if method == "POST":
                return 201, {"id": "esp-" + str(len(calls))}
            name = path.rstrip("/").rsplit("/", 1)[-1]
            return 200, {"id": name}

        app.espo_request = fake
        app.scope_customizable = lambda entity: False
        app.scope_is_custom = lambda entity: False
        app.publish_field_name = lambda entity, name: "cNessoBadge"
        try:
            with app.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO pipeline
                    (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field, key_columns, enabled)
                    VALUES ('gruppo', 'Gruppo', 'in', 'Account', 'societa', 'gruppo:{societa}|{codice}', ?, 'cExternalKey', ?, 1)
                    """,
                    (
                        '[{"from":"ragione","to":"name","transform":"copy","owner":"sorgente"}]',
                        '["societa","codice"]',
                    ),
                )
            nord = app.ingest("gruppo", {"societa": "MI", "codice": "C001", "ragione": "Nord"})
            sud = app.ingest("gruppo", {"societa": "TO", "codice": "C001", "ragione": "Sud"})
            again = app.ingest("gruppo", {"societa": "MI", "codice": "C001", "ragione": "Nord due"})
            self.assertEqual(nord["status"], "creato")
            self.assertEqual(sud["status"], "creato")
            self.assertNotEqual(nord["espoId"], sud["espoId"])
            self.assertEqual(again["status"], "aggiornato")
            self.assertEqual(again["espoId"], nord["espoId"])
            with app.connect() as conn:
                stored = [row["external_id"] for row in conn.execute("SELECT external_id FROM queue_item WHERE pipeline_id = 'gruppo' ORDER BY external_id")]
            self.assertEqual(stored, ["MI|C001", "TO|C001"])
        finally:
            app.espo_request, app.scope_customizable, app.scope_is_custom, app.publish_field_name = saved

    def test_una_colonna_non_cambia_la_chiave(self):
        saved = (app.espo_request, app.scope_customizable, app.scope_is_custom, app.publish_field_name)
        app.espo_request = lambda method, path, body=None, query=None: (201, {"id": "esp-1"}) if method == "POST" else (200, {"id": "esp-1"})
        app.scope_customizable = lambda entity: False
        app.scope_is_custom = lambda entity: False
        app.publish_field_name = lambda entity, name: "cNessoBadge"
        try:
            with app.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO pipeline
                    (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field, enabled)
                    VALUES ('solo', 'Solo', 'in', 'Account', 'codice', 'solo:{codice}', ?, 'cExternalKey', 1)
                    """,
                    ('[{"from":"nome","to":"name","transform":"copy","owner":"sorgente"}]',),
                )
            item = app.ingest("solo", {"codice": "C001", "nome": "Nord"})
            self.assertEqual(item["externalKey"], "solo:C001")
            with app.connect() as conn:
                stored = conn.execute("SELECT external_id FROM queue_item WHERE pipeline_id = 'solo'").fetchone()["external_id"]
            self.assertEqual(stored, "C001")
        finally:
            app.espo_request, app.scope_customizable, app.scope_is_custom, app.publish_field_name = saved

    def test_il_foglio_cambia_il_padrone_e_lascia_il_legame(self):
        mapping = [
            {"from": "nome", "to": "name", "transform": "copy", "owner": "sorgente"},
            {"from": "azienda", "to": "accountId", "transform": "lookup", "lookupEntity": "Account", "lookupBy": "name", "onMiss": "fail"},
            {"from": "tipo", "to": "type", "transform": "map", "owner": "sorgente", "valueMap": {"A": "Cliente"}},
        ]
        other = [{"from": "nome", "to": "name", "transform": "copy", "owner": "sorgente"}]
        with app.connect() as conn:
            conn.execute(
                """
                INSERT INTO pipeline
                (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field)
                VALUES ('clienti', 'Clienti', 'in', 'Account', 'codice', 'clienti:{codice}', ?, 'cExternalKey')
                """,
                (json.dumps(mapping),),
            )
            conn.execute(
                """
                INSERT INTO pipeline
                (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field)
                VALUES ('altra', 'Altra', 'in', 'Account', 'codice', 'altra:{codice}', ?, 'cExternalKey')
                """,
                (json.dumps(other),),
            )
        text = (
            "Integrazione;Colonna;Campo;Trasformazione;Padrone;Obbligatorio\n"
            "clienti;nome;name;copy;espo;si\n"
            "clienti;tipo;type;map;sorgente;no\n"
        )
        result = app.import_sheet(text)
        self.assertEqual(result["pipelines"], 1)
        with app.connect() as conn:
            stored = json.loads(conn.execute("SELECT mapping_json FROM pipeline WHERE id = 'clienti'").fetchone()["mapping_json"])
            untouched = json.loads(conn.execute("SELECT mapping_json FROM pipeline WHERE id = 'altra'").fetchone()["mapping_json"])
        by_from = {row["from"]: row for row in stored}
        self.assertEqual(by_from["nome"]["owner"], "espo")
        self.assertTrue(by_from["nome"]["required"])
        self.assertEqual(by_from["azienda"]["transform"], "lookup")
        self.assertEqual(by_from["tipo"]["valueMap"]["A"], "Cliente")
        self.assertEqual(untouched[0]["owner"], "sorgente")

    def test_fuori_dal_piano_la_pausa_si_toglie(self):
        with app.connect() as conn:
            conn.execute(
                """
                INSERT INTO pipeline
                (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field, enabled)
                VALUES ('libera', 'Libera', 'in', 'Account', 'codice', 'libera:{codice}', '[]', 'cExternalKey', 0)
                """
            )
        result = app.set_enabled("libera", True)
        self.assertTrue(result["enabled"])

    def test_il_pdf_senza_chiave_resta_e_quello_giusto_si_attacca(self):
        folder = app.SCAMBIO / "pdfs"
        folder.mkdir(parents=True)
        (folder / "fattura-C001.pdf").write_bytes(b"%PDF-1.4")
        (folder / "senza.pdf").write_bytes(b"%PDF-1.4")
        calls = []

        def fake(method, path, body=None, query=None):
            calls.append((method, path, body))
            if str(path).endswith("Attachment"):
                return 201, {"id": "att"}
            if str(path).endswith("Document"):
                return 201, {"id": "doc"}
            return 200, {}

        saved = app.espo_request
        app.espo_request = fake
        try:
            with app.connect() as conn:
                conn.execute(
                    "INSERT INTO connection (id, name, kind, config_json, token) VALUES ('pdfs', 'PDF', 'pdf', '{}', 'tok')"
                )
                conn.execute(
                    """
                    INSERT INTO pipeline
                    (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field, connection_id)
                    VALUES ('documenti', 'Documenti', 'in', 'Document', 'nome', 'documenti:{nome}', '[]', 'cExternalKey', 'pdfs')
                    """
                )
                conn.execute(
                    "INSERT INTO chiave (entity, external_key, espo_id) VALUES ('Account', 'anagrafiche:C001', 'acc-1')"
                )
            result = app.execute_pipeline("documenti")
            self.assertEqual(result["attached"], 1)
            self.assertEqual(result["waiting"], 1)
            self.assertTrue((folder / "senza.pdf").is_file())
            self.assertEqual(len(list((folder / "elaborati").glob("*.pdf"))), 1)
            posted = [body for method, path, body in calls if method == "POST" and str(path).endswith("Document")]
            self.assertEqual(posted[0]["accountsIds"], ["acc-1"])
        finally:
            app.espo_request = saved

    def test_l_ordine_propone_la_fase_e_non_la_scrive(self):
        calls = []

        def fake(method, path, body=None, query=None):
            calls.append((method, path, body))
            if method == "GET":
                return 200, {"id": "off-1", "stage": "Prospecting"}
            if method == "PUT":
                return 200, {"id": "off-1"}
            return 201, {"id": "esp-1"}

        saved = (app.espo_request, app.scope_customizable, app.scope_is_custom, app.publish_field_name)
        app.espo_request = fake
        app.scope_customizable = lambda entity: False
        app.scope_is_custom = lambda entity: False
        app.publish_field_name = lambda entity, name: "cNessoBadge"
        try:
            with app.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO pipeline
                    (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field, enabled, propose_from, propose_entity, propose_field, propose_value)
                    VALUES ('ordini', 'Ordini', 'in', 'Account', 'codice', 'ordini:{codice}', ?, 'cExternalKey', 1, 'offerta', 'COfferta', 'stage', 'Closed Won')
                    """,
                    ('[{"from":"nome","to":"name","transform":"copy","owner":"sorgente"}]',),
                )
                conn.execute(
                    "INSERT INTO chiave (entity, external_key, espo_id) VALUES ('COfferta', 'OFF-1', 'off-1')"
                )
            app.ingest("ordini", {"codice": "O-1", "nome": "Ordine", "offerta": "OFF-1"})
            self.assertFalse(any(method == "PUT" for method, _path, _body in calls))
            with app.connect() as conn:
                proposal = conn.execute("SELECT id, proposed FROM stage_proposal").fetchone()
            self.assertEqual(proposal["proposed"], "Closed Won")
            app.confirm_proposal(proposal["id"])
            puts = [body for method, path, body in calls if method == "PUT" and path.endswith("off-1")]
            self.assertEqual(puts[0]["stage"], "Closed Won")
            with app.connect() as conn:
                left = conn.execute("SELECT COUNT(*) AS n FROM stage_proposal").fetchone()["n"]
                offer = conn.execute("SELECT espo_id FROM chiave WHERE entity = 'COfferta'").fetchone()["espo_id"]
            self.assertEqual(left, 0)
            self.assertEqual(offer, "off-1")
        finally:
            app.espo_request, app.scope_customizable, app.scope_is_custom, app.publish_field_name = saved

    def test_l_export_lascia_lo_storico(self):
        with app.connect() as conn:
            conn.execute(
                """
                INSERT INTO pipeline
                (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field)
                VALUES ('rubrica', 'Rubrica', 'in', 'Contact', 'codice', 'rubrica:{codice}', '[]', 'cExternalKey')
                """
            )
            conn.execute(
                "INSERT INTO presenza (pipeline_id, external_key, espo_id) VALUES ('rubrica', 'CNT-1', 'c1')"
            )
            conn.execute(
                """
                INSERT INTO field_history (pipeline_id, run_at, espo_id, field_name, previous_value, written_value)
                VALUES ('rubrica', '2026-10-19 10:00:00', 'c1', 'emailAddress', '', 'a@b.c')
                """
            )
            conn.execute(
                """
                INSERT INTO field_history (pipeline_id, run_at, espo_id, field_name, previous_value, written_value)
                VALUES ('rubrica', '2026-10-19 10:00:00', 'c1', 'password', '', 'segreto')
                """
            )
            before = conn.execute("SELECT COUNT(*) AS n FROM field_history").fetchone()["n"]
        result = app.privacy_for("CNT-1", "")
        with app.connect() as conn:
            after = conn.execute("SELECT COUNT(*) AS n FROM field_history").fetchone()["n"]
        self.assertEqual(after, before)
        self.assertEqual(result["kept"], before)
        self.assertEqual([row["field"] for row in result["rows"]], ["emailAddress"])

    def test_senza_ingresso_non_si_lancia_e_chi_lancia_non_salva(self):
        server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            denied = self._post(port, "/api/pipelines/clienti/run", {})
            self.assertEqual(denied["code"], 401)
            self.assertNotIn("segreto-lungo", json.dumps(denied))
            primo = self._post(port, "/api/ingresso/primo", {"name": "chi-cambia", "password": "segreto-lungo"})
            self.assertEqual(primo["code"], 200)
            self.assertEqual(primo["body"]["gesture"], "cambia")
            cookie = primo["cookie"]
            added = self._post(port, "/api/attori", {"name": "chi-lancia", "password": "altra-password", "gesture": "lancia"}, cookie)
            self.assertEqual(added["code"], 200)
            entra = self._post(port, "/api/ingresso", {"name": "chi-lancia", "password": "altra-password"})
            self.assertEqual(entra["code"], 200)
            blocked = self._post(port, "/api/pipelines", {"name": "x"}, entra["cookie"])
            self.assertEqual(blocked["code"], 403)
            allowed = self._post(port, "/api/pipelines/manca/run", {}, entra["cookie"])
            self.assertNotIn(allowed["code"], (401, 403))
            blob = json.dumps(app.export_config(), ensure_ascii=False) + json.dumps(app.snapshot(), ensure_ascii=False, default=str)
            with app.connect() as conn:
                journal = " ".join(row[0] or "" for row in conn.execute("SELECT detail FROM run_log").fetchall())
            self.assertNotIn("segreto-lungo", blob)
            self.assertNotIn("segreto-lungo", journal)
            self.assertNotIn("altra-password", blob)
        finally:
            server.shutdown()

    def test_il_giro_fallito_accende_un_avviso_solo(self):
        with app.connect() as conn:
            conn.execute(
                """
                INSERT INTO pipeline
                (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field, alert_minutes, enabled, last_success)
                VALUES ('ordini', 'Ordini', 'in', 'Opportunity', 'codice', 'ordini:{codice}', '[]', 'cExternalKey', 60, 1, '2026-10-19 08:00:00')
                """
            )
        sent = []
        original = app.deliver_notice
        app.deliver_notice = lambda notice: sent.append(notice)
        try:
            app.mark_run("ordini", "errore", "connessione rifiutata")
            app.mark_run("ordini", "errore", "connessione rifiutata")
            app.remember_reject("ordini", "O-1", {"codice": "O-1"}, "riga scartata")
            with app.connect() as conn:
                kinds = [row["kind"] for row in conn.execute("SELECT kind FROM notice WHERE open = 1")]
            self.assertEqual(kinds, ["fallito"])
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0]["name"], "Ordini")
            quiet = app.notice_quiet(datetime(2026, 10, 20, 12, 0, 0))
            self.assertEqual(quiet, ["ordini"])
            self.assertEqual(app.notice_quiet(datetime(2026, 10, 20, 12, 0, 0)), [])
            home = app.snapshot()
            texts = [item["text"] for item in home["alerts"]]
            self.assertIn("Ordini: il giro non è riuscito.", texts)
            self.assertIn("Ordini: tace da più di 60 minuti.", texts)
            app.mark_run("ordini", "ok", "1 create", {"created": 1, "updated": 0, "closed": 0, "failed": 0})
            with app.connect() as conn:
                left = conn.execute("SELECT COUNT(*) AS n FROM notice WHERE open = 1").fetchone()["n"]
            self.assertEqual(left, 0)
        finally:
            app.deliver_notice = original

    def test_la_scrittura_non_e_dell_admin(self):
        app.set_setting("espo_service_user", "nesso")
        app.set_setting("espo_service_secret", "segreto-servizio")
        app.set_setting("espo_role_entities", json.dumps(["Account"]))
        seen = {}
        original = app.espo_call

        def fake(method, path, body=None, query=None, *, user, password):
            seen["user"] = user
            seen["password"] = password
            return 201, {"id": "a1", "userName": user}

        app.espo_call = fake
        try:
            REAL_REQUEST("POST", "/api/v1/Account", {"name": "Nord"})
            self.assertEqual(seen["user"], "nesso")
            self.assertEqual(seen["password"], "segreto-servizio")
            app.espo_admin("GET", "/api/v1/Metadata")
            self.assertEqual(seen["user"], app.ESPO_USER)
            with self.assertRaises(RuntimeError):
                REAL_REQUEST("POST", "/api/v1/Contact", {"name": "X"})
        finally:
            app.espo_call = original

    def _post(self, port, path, body, cookie=""):
        data = json.dumps(body).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=data,
            method="POST",
            headers={"Content-Type": "application/json", "Cookie": cookie},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                raw = response.read().decode()
                header = response.headers.get("Set-Cookie") or ""
                token = ""
                if "nesso_sessione=" in header:
                    token = header.split("nesso_sessione=", 1)[1].split(";", 1)[0]
                return {"code": response.status, "body": json.loads(raw or "{}"), "cookie": f"nesso_sessione={token}" if token else cookie}
        except urllib.error.HTTPError as error:
            raw = error.read().decode()
            try:
                parsed = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed = {"error": raw}
            return {"code": error.code, "body": parsed, "cookie": cookie}


class StatoCanaliCursore(unittest.TestCase):
    def setUp(self):
        app.DB_PATH = Path(os.environ["DB_PATH"])
        app.SCAMBIO = Path(os.environ["SCAMBIO_DIR"])
        app.init_db()
        with app.connect() as conn:
            conn.execute("DELETE FROM pipeline")
            conn.execute("DELETE FROM connection")
            conn.execute("DELETE FROM run_log")
            conn.execute("DELETE FROM scarto")
            conn.execute("DELETE FROM queue_item")
            conn.execute("DELETE FROM presenza")
            conn.execute("DELETE FROM cursor_state")
            conn.execute("DELETE FROM sink_item")
            conn.execute("UPDATE setting SET value = '1' WHERE key = 'writes'")
        self._page = app.espo_page
        self._remote = app.open_remote
        self._request = app.espo_request

    def tearDown(self):
        app.espo_page = self._page
        app.open_remote = self._remote
        app.espo_request = self._request

    def test_xlsx_si_sposta_e_sftp_deposita_senza_rinviare(self):
        import io
        import zipfile

        sheet = """<?xml version="1.0" encoding="UTF-8"?>
        <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
          <sheetData>
            <row r="1"><c r="A1" t="inlineStr"><is><t>codice</t></is></c><c r="B1" t="inlineStr"><is><t>nome</t></is></c></row>
            <row r="2"><c r="A2" t="inlineStr"><is><t>9</t></is></c><c r="B2" t="inlineStr"><is><t>Nord</t></is></c></row>
          </sheetData>
        </worksheet>"""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as book:
            book.writestr("xl/worksheets/sheet1.xml", sheet)
        data = buffer.getvalue()
        folder = app.SCAMBIO / "fogli"
        folder.mkdir(parents=True)
        (folder / "clienti.xlsx").write_bytes(data)
        with app.connect() as conn:
            conn.execute(
                "INSERT INTO connection (id, name, kind, config_json, token) VALUES ('fogli', 'Fogli', 'csv', '{}', 'tok')"
            )
            conn.execute(
                """
                INSERT INTO pipeline
                (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field, connection_id)
                VALUES ('clienti', 'Clienti', 'in', 'Account', 'codice', 'clienti:{codice}', ?, 'cExternalKey', 'fogli')
                """,
                ('[{"from":"codice","to":"name","transform":"copy","owner":"sorgente"}]',),
            )

        def fake(method, path, body=None, query=None):
            if method == "GET":
                return 200, {"list": []}
            return 201, {"id": "esp-9"}

        app.espo_request = fake
        app.execute_pipeline("clienti")
        self.assertFalse((folder / "clienti.xlsx").exists())
        self.assertEqual(len(list((folder / "elaborati").glob("*.xlsx"))), 1)

        class Finto:
            def __init__(self):
                self.files = {"ordini.xlsx": data}
                self.moved = []
                self.sent = []

            def names(self):
                return list(self.files)

            def read(self, name):
                return self.files[name]

            def rename(self, name, dest):
                self.moved.append(dest)
                self.files.pop(name, None)

            def put(self, name, payload):
                self.sent.append((name, payload))

            def close(self):
                return None

        remote = Finto()
        app.open_remote = lambda kind, config: remote
        with app.connect() as conn:
            conn.execute(
                """
                INSERT INTO connection (id, name, kind, config_json, token)
                VALUES ('scambio-remoto', 'Remoto', 'sftp', ?, 'tok')
                """,
                (json.dumps({"host": "files", "user": "scambio", "password": "non-in-chiaro", "path": "/in"}),),
            )
            conn.execute(
                """
                INSERT INTO pipeline
                (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field, connection_id)
                VALUES ('ordini', 'Ordini', 'in', 'Account', 'codice', 'ordini:{codice}', ?, 'cExternalKey', 'scambio-remoto')
                """,
                ('[{"from":"codice","to":"name","transform":"copy","owner":"sorgente"}]',),
            )
        app.execute_pipeline("ordini")
        self.assertEqual(len(remote.moved), 1)
        self.assertTrue(remote.moved[0].startswith("elaborati/"))
        self.assertNotIn("ordini.xlsx", remote.files)
        shown = app.public_connection({
            "id": "scambio-remoto",
            "name": "Remoto",
            "kind": "sftp",
            "token": "tok",
            "config_json": json.dumps({"host": "files", "password": "non-in-chiaro", "tunnelPassword": "tunnel-segreto"}),
        })
        self.assertEqual(shown["config"]["password"], "")
        self.assertEqual(shown["config"]["tunnelPassword"], "")
        self.assertNotIn("non-in-chiaro", json.dumps(shown))

    def test_senza_modified_at_il_secondo_giro_non_rimanda(self):
        rows = [
            {"id": "a1", "modifiedAt": "", "name": "Uno"},
            {"id": "a2", "modifiedAt": "", "name": "Due"},
        ]
        app.espo_page = lambda *args, **kwargs: rows
        first = app.collect_changes("Lead", "id,modifiedAt,name", "1970-01-01 00:00:00", 100)
        self.assertEqual([item["id"] for item in first], ["a1", "a2"])
        with app.connect() as conn:
            conn.execute(
                """
                INSERT INTO pipeline
                (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field)
                VALUES ('uscita', 'Uscita', 'out', 'Lead', 'id', '', ?, 'cExternalKey')
                """,
                ('[{"from":"name","to":"nome","transform":"copy"}]',),
            )
        pulled = app.pull("uscita")
        self.assertEqual(pulled["exported"], 2)
        self.assertTrue(pulled["missingDate"])
        with app.connect() as conn:
            cursor = conn.execute("SELECT cursor_value FROM cursor_state WHERE pipeline_id = 'uscita'").fetchone()["cursor_value"]
            detail_row = None
        self.assertEqual(cursor, "\ta2")
        second = app.collect_changes("Lead", "id,modifiedAt,name", cursor, 100)
        self.assertEqual(second, [])
        again = app.pull("uscita")
        self.assertEqual(again["exported"], 0)
        self.assertIsNone(detail_row)

    def test_mysql_senza_tls_non_aggiunge_ssl(self):
        import sys
        import types

        calls = []
        fake = types.ModuleType("pymysql")
        fake.cursors = types.SimpleNamespace(DictCursor=object())

        def connect(**kwargs):
            calls.append(kwargs)
            raise RuntimeError("fermo")

        fake.connect = connect
        saved = sys.modules.get("pymysql")
        sys.modules["pymysql"] = fake
        try:
            for tls in (False, True):
                with self.assertRaises(RuntimeError):
                    app.open_sql({
                        "engine": "mysql",
                        "host": "db",
                        "user": "espocrm",
                        "password": "locale-db",
                        "database": "gestionale",
                        "tls": tls,
                    })
        finally:
            if saved is None:
                sys.modules.pop("pymysql", None)
            else:
                sys.modules["pymysql"] = saved
        self.assertNotIn("ssl", calls[0])
        self.assertEqual(calls[0]["port"], 3306)
        self.assertEqual(calls[0]["host"], "db")
        self.assertIn("ssl", calls[1])


class FirmaEOauth(unittest.TestCase):
    def setUp(self):
        app.DB_PATH = Path(os.environ["DB_PATH"])
        app.SCAMBIO = Path(os.environ["SCAMBIO_DIR"])
        app.init_db()
        with app.connect() as conn:
            conn.execute("DELETE FROM pipeline")
            conn.execute("DELETE FROM connection")
            conn.execute("DELETE FROM queue_item")
            conn.execute("DELETE FROM silence_window")
            conn.execute("DELETE FROM delivery")
            conn.execute("DELETE FROM run_log")
            conn.execute("DELETE FROM cursor_state")
            conn.execute("DELETE FROM sink_item")
        self.saved = (app.espo_request, app.espo_page, app.post_json, app.request_oauth)

    def tearDown(self):
        app.espo_request, app.espo_page, app.post_json, app.request_oauth = self.saved

    def test_senza_firma_valida_non_scrive_e_con_firma_si(self):
        calls = []

        def fake(method, path, body=None, query=None):
            calls.append(method)
            if method == "POST":
                return 201, {"id": "esp-firma"}
            name = path.rstrip("/").rsplit("/", 1)[-1]
            return 200, {"id": name}

        app.espo_request = fake
        with app.connect() as conn:
            conn.execute("DELETE FROM silence_window")
            conn.execute(
                """
                INSERT INTO connection (id, name, kind, config_json, token)
                VALUES ('firmato', 'Firmato', 'webhook', ?, 'tok')
                """,
                (json.dumps({"signSecret": "segretissimo"}),),
            )
            conn.execute(
                """
                INSERT INTO pipeline
                (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field, connection_id, enabled)
                VALUES ('firmato', 'Firmato', 'in', 'Account', 'codice', 'firmato:{codice}', ?, 'cExternalKey', 'firmato', 1)
                """,
                ('[{"from":"codice","to":"name","transform":"copy","owner":"sorgente"}]',),
            )
        raw = b'{"codice":"1","nome":"Nord"}'
        with self.assertRaises(PermissionError):
            app.accept_hook("firmato", "tok", json.loads(raw), raw, "")
        with app.connect() as conn:
            parked = conn.execute("SELECT COUNT(*) AS n FROM queue_item WHERE pipeline_id = 'firmato'").fetchone()["n"]
        self.assertEqual(parked, 0)
        self.assertEqual(calls, [])
        signed = app.carico.sign_body("segretissimo", raw)
        result = app.accept_hook("firmato", "tok", json.loads(raw), raw, signed)
        self.assertEqual(result["results"][0]["status"], "creato")
        self.assertIn("POST", calls)
        plain = app.save_connection({"id": "firmato", "name": "Firmato", "kind": "webhook", "config": {}})
        self.assertIn("/hook/firmato/", plain["url"])
        with app.connect() as conn:
            kept = json.loads(conn.execute("SELECT config_json FROM connection WHERE id = 'firmato'").fetchone()["config_json"])
        self.assertEqual(kept["signSecret"], "segretissimo")

    def test_oauth_scaduto_rinnova_e_completa_il_post(self):
        grants = []
        sent = []

        def fetch(config, grant):
            grants.append(grant)
            self.assertEqual(config["clientSecret"], "segreto")
            return {"access_token": "nuovo", "expires_in": 3600, "refresh_token": "r2"}

        seen = {"n": 0}

        def page(entity, select, where, order_by):
            seen["n"] += 1
            if seen["n"] <= 2:
                return [{"id": "a1", "name": "Nord", "modifiedAt": "2026-10-21 09:00:00"}]
            return []

        def post(url, payload, headers=None):
            sent.append((url, payload, headers or {}))

        app.request_oauth = fetch
        app.espo_page = page
        app.post_json = post
        app.save_connection({
            "name": "Portale",
            "kind": "http",
            "config": {
                "url": "https://example.test/in",
                "auth": "oauth",
                "tokenUrl": "https://example.test/token",
                "clientId": "client",
                "clientSecret": "segreto",
                "refreshToken": "rinfresca",
                "accessToken": "vecchio",
                "tokenObtained": "2020-01-01 00:00:00",
                "expiresIn": 60,
            },
        })
        with app.connect() as conn:
            conn.execute(
                """
                INSERT INTO pipeline
                (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field, connection_id)
                VALUES ('portale', 'Portale', 'out', 'Account', 'codice', 'portale:{codice}', ?, 'cExternalKey', 'portale')
                """,
                ('[{"from":"name","to":"nome","transform":"copy","owner":"sorgente"}]',),
            )
        result = app.execute_pipeline("portale")
        self.assertEqual(result["sent"], 1)
        self.assertEqual(grants, ["refresh_token"])
        self.assertEqual(sent[0][0], "https://example.test/in")
        self.assertEqual(sent[0][1], {"nome": "Nord"})
        self.assertEqual(sent[0][2]["Authorization"], "Bearer nuovo")
        with app.connect() as conn:
            stored = json.loads(conn.execute("SELECT config_json FROM connection WHERE id = 'portale'").fetchone()["config_json"])
            shown = app.public_connection(conn.execute("SELECT * FROM connection WHERE id = 'portale'").fetchone())
        again = app.fresh_oauth_token("portale", stored)
        self.assertEqual(again, "nuovo")
        self.assertEqual(grants, ["refresh_token"])
        dumped = json.dumps(shown)
        self.assertNotIn("segreto", dumped)
        self.assertNotIn("nuovo", dumped)
        self.assertNotIn("vecchio", dumped)
        self.assertEqual(shown["config"]["clientSecret"], "")
        self.assertTrue(shown["config"]["hasClientSecret"])
        bearer = app.destination_headers({"auth": "bearer", "token": "abc"})
        self.assertEqual(bearer, {"Authorization": "Bearer abc"})
        self.assertEqual(app.destination_headers({"auth": "none"}), {})
        with app.connect() as conn:
            detail = conn.execute("SELECT detail FROM delivery WHERE pipeline_id = 'portale'").fetchone()["detail"]
        self.assertNotIn("segreto", detail)
        self.assertNotIn("nuovo", detail)


class Evolutive(unittest.TestCase):
    def setUp(self):
        app.DB_PATH = Path(os.environ["DB_PATH"])
        app.SCAMBIO = Path(os.environ["SCAMBIO_DIR"])
        app.init_db()
        with app.connect() as conn:
            for table in ("pipeline", "connection", "queue_item", "scarto", "delivery", "run_log", "cursor_state", "sink_item", "chiave", "mapping_version", "mail_queue", "sheet_field"):
                conn.execute(f"DELETE FROM {table}")
        self.saved = (app.espo_request, app.espo_page, app.post_json, app.read_database, app.write_source, app.send_smtp, app.ask_model)
        with app.connect() as conn:
            conn.execute("DELETE FROM setting WHERE key = 'model_url'")

    def tearDown(self):
        app.espo_request, app.espo_page, app.post_json, app.read_database, app.write_source, app.send_smtp, app.ask_model = self.saved
        app.CATALOG["data"] = None
        app.CATALOG["at"] = 0

    def _account(self, pipeline_id, mapping, **extra):
        with app.connect() as conn:
            conn.execute(
                f"""
                INSERT INTO pipeline
                (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field, enabled)
                VALUES (?, ?, 'in', 'Account', 'codice', ?, ?, 'cExternalKey', 1)
                """,
                (pipeline_id, pipeline_id, pipeline_id + ":{codice}", mapping),
            )
            for key, value in extra.items():
                conn.execute(f"UPDATE pipeline SET {key} = ? WHERE id = ?", (value, pipeline_id))

    def test_obbligatorio_e_errore_col_nome_del_campo(self):
        calls = []

        def fake(method, path, body=None, query=None):
            calls.append(method)
            if "Note" in str(path):
                return 200, {"id": "nota"}
            return 400, {"field": "name", "message": "non ammesso"}

        app.espo_request = fake
        self._account("obbligatori", '[{"from":"nome","to":"name","transform":"copy","required":true}]')
        empty = app.ingest_row("obbligatori", {"codice": "1", "nome": ""})
        self.assertEqual(empty["status"], "scartato")
        self.assertIn("name", empty["detail"])
        self.assertEqual(calls, [])
        app.espo_request = lambda method, path, body=None, query=None: (400, "")
        named = app.ingest_row("obbligatori", {"codice": "1", "nome": "Nord"})
        self.assertIn("risposta vuota", named["detail"])

    def test_il_webhook_incollato_non_scrive(self):
        calls = []
        app.espo_request = lambda *args, **kwargs: calls.append(args) or (200, {"list": []})
        with app.connect() as conn:
            conn.execute("INSERT INTO connection (id, name, kind, config_json, token) VALUES ('gancio2', 'Gancio', 'webhook', '{}', 'tok')")
            conn.execute(
                """
                INSERT INTO pipeline
                (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field, connection_id)
                VALUES ('gancio2', 'Gancio', 'in', 'Account', 'codice', 'gancio2:{codice}', ?, 'cExternalKey', 'gancio2')
                """,
                ('[{"from":"codice","to":"name","transform":"copy"}]',),
            )
        plain = app.dry_run("gancio2")
        self.assertIn("non ha righe", plain["detail"])
        shown = app.dry_run("gancio2", {"codice": "1"})
        self.assertEqual(shown["rows"][0]["mapped"]["name"], "1")
        self.assertTrue(all(call[0] != "POST" for call in calls))
        broken = app.dry_run("gancio2", "no")
        self.assertIn("oggetto", broken["detail"])

    def test_una_riga_scartata_si_rilancia_da_sola(self):
        calls = []

        def fake(method, path, body=None, query=None):
            calls.append(str(path))
            if method == "GET":
                return 200, {"list": []}
            return 201, {"id": "esp-1"}

        app.espo_request = fake
        self._account("solo", '[{"from":"nome","to":"name","transform":"copy"}]')
        with app.connect() as conn:
            conn.execute(
                "INSERT INTO scarto (pipeline_id, external_id, payload_json, detail, created_at) VALUES ('solo', '1', ?, 'vecchio', '2026-10-21 10:00:00')",
                ('{"codice":"1","nome":"Nord"}',),
            )
            scarto_id = conn.execute("SELECT id FROM scarto").fetchone()["id"]
        result = app.replay_reject(scarto_id)
        self.assertEqual(result["status"], "creato")
        with app.connect() as conn:
            row = conn.execute("SELECT resolved, detail FROM scarto WHERE id = ?", (scarto_id,)).fetchone()
        self.assertEqual(row["resolved"], 1)
        self.assertTrue(any(path.endswith("/Note") for path in calls))

    def test_due_padri_e_la_chiave_esterna_in_uscita(self):
        with app.connect() as conn:
            conn.execute("INSERT INTO pipeline (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field, enabled, last_status) VALUES ('aziende', 'Aziende', 'in', 'Account', 'codice', 'aziende:{codice}', '[]', 'cExternalKey', 1, 'errore')")
            conn.execute("INSERT INTO pipeline (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field, enabled, last_status) VALUES ('sedi', 'Sedi', 'in', 'Account', 'codice', 'sedi:{codice}', '[]', 'cExternalKey', 1, 'ok')")
            conn.execute("INSERT INTO pipeline (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field, enabled, depends_json) VALUES ('contatti', 'Contatti', 'in', 'Contact', 'codice', 'contatti:{codice}', '[]', 'cExternalKey', 1, ?)", ('["aziende","sedi"]',))
        result = app.execute_chain("contatti", set(), False)
        self.assertEqual(result["missing"], ["Aziende"])
        calls = []
        app.espo_page = lambda *args, **kwargs: [{"id": "acc-1", "accountId": "acc-1", "modifiedAt": "2026-10-21 09:00:00"}] if calls.append(1) or len(calls) <= 2 else []
        app.post_json = lambda *args, **kwargs: calls.append(args)
        with app.connect() as conn:
            conn.execute("INSERT INTO chiave (entity, external_key, espo_id) VALUES ('Account', 'anagrafiche:C001', 'acc-1')")
            conn.execute(
                "INSERT INTO connection (id, name, kind, config_json, token) VALUES ('uscita', 'Uscita', 'http', ?, 'tok')",
                ('{"url":"https://example.test/in","auth":"none"}',),
            )
            conn.execute(
                """
                INSERT INTO pipeline
                (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field, connection_id)
                VALUES ('offerte', 'Offerte', 'out', 'Opportunity', 'id', '', ?, 'cExternalKey', 'uscita')
                """,
                ('[{"from":"accountId","to":"cliente","transform":"copy","as":"chiave","lookupEntity":"Account"}]',),
            )
        sent = app.execute_pipeline("offerte")
        self.assertEqual(sent["sent"], 1)
        self.assertEqual(calls[-1][1]["cliente"], "anagrafiche:C001")

    def test_casella_documento_e_ritorno_spento(self):
        calls = []

        def fake(method, path, body=None, query=None):
            calls.append((method, path, body))
            if str(path).endswith("Attachment"):
                return 201, {"id": "att"}
            if str(path).endswith("Document"):
                return 201, {"id": "doc"}
            if method == "GET":
                return 200, {"list": []}
            return 201, {"id": "esp-2"}

        app.espo_request = fake
        self._account("dentro", '[{"from":"nome","to":"name","transform":"copy"}]')
        with app.connect() as conn:
            conn.execute("INSERT INTO connection (id, name, kind, config_json, token) VALUES ('casella', 'Casella', 'http', ?, 'tok')", ('{"deliverTo":"dentro"}',))
            conn.execute("UPDATE pipeline SET enabled = 0 WHERE id = 'dentro'")
        held = app.accept_inbox("casella", "tok", {"codice": "1", "nome": "Nord"})
        self.assertFalse(held["delivered"])
        with app.connect() as conn:
            conn.execute("UPDATE pipeline SET enabled = 1 WHERE id = 'dentro'")
        once = app.accept_inbox("casella", "tok", {"codice": "9", "nome": "Sud"})
        self.assertTrue(once["delivered"])
        again = app.deliver_inbox("casella", {"codice": "9", "nome": "Sud"})
        self.assertFalse(again)
        folder = Path(os.environ["SCAMBIO_DIR"]) / "atti"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "contratto.txt").write_text("ciao", encoding="utf-8")
        with app.connect() as conn:
            conn.execute("INSERT INTO connection (id, name, kind, config_json, token) VALUES ('atti', 'Atti', 'documento', ?, 'tok')", ('{"documentFolder":"Contratti","team":"Vendite"}',))
            conn.execute("INSERT INTO pipeline (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field, connection_id) VALUES ('atti', 'Atti', 'in', 'Document', 'nome', 'atti:{nome}', '[]', 'cExternalKey', 'atti')")
        done = app.execute_pipeline("atti")
        self.assertEqual(done["taken"], 1)
        self.assertTrue((folder / "elaborati").is_dir())
        self.assertFalse((folder / "contratto.txt").exists())
        writes = []
        app.read_database = lambda *args, **kwargs: [{"codice": "1"}]
        app.write_source = lambda *args, **kwargs: writes.append(args) or 0
        with app.connect() as conn:
            conn.execute("INSERT INTO connection (id, name, kind, config_json, token) VALUES ('db1', 'Db', 'database', ?, 'tok')", ('{"host":"db","database":"gestionale","user":"espocrm","query":"SELECT codice FROM clienti","engine":"mysql"}',))
            conn.execute("INSERT INTO pipeline (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field, connection_id, write_back) VALUES ('lettura', 'Lettura', 'in', 'Account', 'codice', 'lettura:{codice}', ?, 'cExternalKey', 'db1', 0)", ('[{"from":"codice","to":"name","transform":"copy"}]',))
        app.execute_pipeline("lettura")
        self.assertEqual(writes, [])
        with app.connect() as conn:
            conn.execute("UPDATE pipeline SET write_back = 1, write_fields = ? WHERE id = 'lettura'", ('["note"]',))
        app.execute_pipeline("lettura")
        self.assertEqual(len(writes), 1)

    def test_posta_passaggio_e_versione(self):
        app.set_setting("smtp_host", "")
        app.deliver_notice({"pipelineId": "x", "kind": "fallito", "name": "Clienti"})
        with app.connect() as conn:
            queued = conn.execute("SELECT COUNT(*) AS n FROM mail_queue").fetchone()["n"]
        self.assertEqual(queued, 0)
        app.set_setting("smtp_host", "smtp.test")
        sent = []

        def sender(subject, body):
            sent.append(subject)
            if len(sent) == 1:
                raise RuntimeError("rifiutato")

        app.send_smtp = sender
        app.queue_mail("prova", "Nesso: prova", "ciao")
        with app.connect() as conn:
            row = conn.execute("SELECT status, attempts, last_error FROM mail_queue").fetchone()
            conn.execute("UPDATE mail_queue SET next_at = '2000-01-01 00:00:00'")
        self.assertEqual(row["status"], "attesa")
        self.assertNotIn("password", row["last_error"] or "")
        app.retry_mail()
        self.assertEqual(sent, ["Nesso: prova", "Nesso: prova"])
        with app.connect() as conn:
            conn.execute(
                "INSERT INTO connection (id, name, kind, config_json, token) VALUES ('segreto', 'Segreto', 'database', ?, 'tok')",
                ('{"host":"db","password":"locale-db","query":"SELECT 1"}',),
            )
        exported = app.passaggio_config()
        self.assertTrue(exported["passaggio"])
        self.assertNotIn("locale-db", json.dumps(exported))
        before = app.connect().execute("SELECT COUNT(*) AS n FROM connection").fetchone()["n"]
        loaded = app.import_config(exported)
        self.assertEqual(loaded["salvate"], 0)
        after = app.connect().execute("SELECT COUNT(*) AS n FROM connection").fetchone()["n"]
        self.assertEqual(before, after)
        self._account("storia", '[{"from":"nome","to":"name","transform":"copy"}]')
        app.remember_version("storia", [{"from": "nome", "to": "name"}], "chiara")
        app.remember_version("storia", [{"from": "citta", "to": "billingAddressCity"}], "chiara")
        versions = app.mapping_versions("storia")
        self.assertEqual(len(versions), 2)
        captured = []
        original = app.save_pipeline
        app.save_pipeline = lambda body: captured.append(body["mapping"]) or {"id": "storia"}
        try:
            app.restore_version("storia", versions[-1]["id"], "chiara")
        finally:
            app.save_pipeline = original
        self.assertEqual(captured[0][0]["from"], "nome")
        with self.assertRaises(RuntimeError):
            app.rename_field("Account", "cCodice", "Codice gestionale")
        with app.connect() as conn:
            conn.execute("INSERT INTO sheet_field (entity, name, label) VALUES ('Account', 'cCodice', 'Codice cliente')")
        app.espo_request = lambda method, path, body=None, query=None: (200, {"label": body.get("label"), "name": "cCodice"})
        renamed = app.rename_field("Account", "cCodice", "Codice gestionale")
        self.assertEqual(renamed["name"], "cCodice")
        self.assertEqual(renamed["label"], "Codice gestionale")
        app.espo_request = lambda method, path, body=None, query=None: (201, {"id": "mail-1"}) if method != "GET" else (200, {"list": []})
        self.assertEqual(app.take_mail([{"id": "m1", "codice": "1", "nome": "Nord"}], "storia"), 1)

    def test_l_attivita_nasce_solo_alla_creazione(self):
        posts = []

        def fake(method, path, body=None, query=None):
            if method in ("POST", "PUT"):
                posts.append(path)
                return 200 if method == "PUT" else 201, {"id": "esp-att"}
            return 200, {"list": []}

        app.espo_request = fake
        self._account(
            "nuovo",
            '[{"from":"nome","to":"name","transform":"copy"}]',
            activity_json='{"type":"Task","date":"2026-10-22","assignee":"user-1"}',
        )
        first = app.ingest("nuovo", {"codice": "1", "nome": "Nord"})
        second = app.ingest("nuovo", {"codice": "1", "nome": "Nord due"})
        self.assertEqual(first["status"], "creato")
        self.assertEqual(second["status"], "aggiornato")
        self.assertEqual(sum(1 for path in posts if str(path).endswith("/Task")), 1)

    def test_il_pull_si_ferma_sulla_chiave_mancante(self):
        rows = [
            {"id": "a1", "modifiedAt": "2026-10-21 09:00:00", "accountId": "known"},
            {"id": "a2", "modifiedAt": "2026-10-21 09:05:00", "accountId": "missing"},
            {"id": "a3", "modifiedAt": "2026-10-21 09:06:00", "accountId": "known"},
        ]
        app.espo_page = lambda *args, **kwargs: rows
        with app.connect() as conn:
            conn.execute("INSERT INTO chiave (entity, external_key, espo_id) VALUES ('Account', 'anagrafiche:C001', 'known')")
            conn.execute(
                """
                INSERT INTO pipeline
                (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field)
                VALUES ('uscita-chiave', 'Uscita', 'out', 'Account', 'id', '', ?, 'cExternalKey')
                """,
                ('[{"from":"accountId","to":"cliente","transform":"copy","as":"chiave","lookupEntity":"Account"}]',),
            )
        pulled = app.pull("uscita-chiave")
        self.assertEqual(pulled["exported"], 1)
        self.assertEqual(pulled["records"], [{"cliente": "anagrafiche:C001"}])
        self.assertEqual(pulled["stopped"], "cliente")
        self.assertTrue(pulled["cursor"].endswith("a1"))
        self.assertNotIn("a3", pulled["cursor"])
        with app.connect() as conn:
            sinks = conn.execute("SELECT espo_id FROM sink_item WHERE pipeline_id = 'uscita-chiave'").fetchall()
        self.assertEqual([row["espo_id"] for row in sinks], ["a1"])

    def test_un_post_fallito_non_supera_il_record(self):
        rows = [
            {"id": "a1", "modifiedAt": "2026-10-21 09:00:00", "name": "Uno"},
            {"id": "a2", "modifiedAt": "2026-10-21 09:01:00", "name": "Due"},
        ]
        app.espo_page = lambda *args, **kwargs: rows
        sent = []

        def post(url, payload, headers=None):
            sent.append(payload)
            if len(sent) == 2:
                raise RuntimeError("muto")

        app.post_json = post
        with app.connect() as conn:
            conn.execute("INSERT INTO connection (id, name, kind, config_json, token) VALUES ('dest', 'Dest', 'http', ?, 'tok')", ('{"url":"https://example.test/in"}',))
            conn.execute(
                """
                INSERT INTO pipeline
                (id, name, direction, espo_entity, external_id_field, key_template, mapping_json, key_field, connection_id)
                VALUES ('uscita-http', 'Uscita', 'out', 'Lead', 'id', '', ?, 'cExternalKey', 'dest')
                """,
                ('[{"from":"name","to":"nome","transform":"copy"}]',),
            )
        app.execute_pipeline("uscita-http")
        self.assertEqual(len(sent), 2)
        with app.connect() as conn:
            cursor = conn.execute("SELECT cursor_value FROM cursor_state WHERE pipeline_id = 'uscita-http'").fetchone()["cursor_value"]
        self.assertTrue(cursor.endswith("a1"))
        self.assertNotIn("a2", cursor)

    def test_il_campo_nuovo_prende_il_tipo_scelto(self):
        posts = []

        def fake(method, path, body=None, query=None):
            if method == "POST" and "fieldManager" in str(path):
                posts.append(body)
                return 201, {"name": body["name"]}
            if method == "PUT":
                return 200, {}
            return 200, []

        app.espo_request = fake
        app.CATALOG["at"] = datetime.now().timestamp()
        app.CATALOG["data"] = [{
            "name": "Account",
            "label": "Azienda",
            "keyField": "cExternalKey",
            "fields": [{"name": "name", "type": "varchar", "label": "Nome"}],
        }]
        app.compile_rules("Account", [
            {"from": "ragione", "to": "name", "role": "field"},
            {"from": "inizio", "to": "Inizio", "role": "field", "fieldType": "date"},
        ], True)
        app.ensure_field("Account", "externalKey", "Chiave esterna", 180)
        kinds = {item["name"]: item["type"] for item in posts}
        self.assertEqual(kinds["inizio"], "date")
        self.assertEqual(kinds["externalKey"], "varchar")
        self.assertNotIn("name", kinds)
        with self.assertRaises(RuntimeError):
            app.ensure_field("Account", "fase", "Fase", 180, "enum", [])

    def test_senza_modello_non_parte_nessuna_chiamata(self):
        def boom(url, payload):
            raise AssertionError(url)

        app.ask_model = boom
        result = app.complete_with_model({
            "columns": ["codice_strano"],
            "fields": [{"name": "name", "label": "Nome"}],
            "samples": [{"codice_strano": "C001", "password": "segreto"}],
        })
        self.assertFalse(result["model"])
        self.assertEqual(result["rows"][0]["to"], "")
        app.set_setting("model_url", "https://modello.test/segreto-modello")
        seen = {}

        def fake(url, payload):
            seen["payload"] = payload
            return [
                {"from": "codice_strano", "to": "name"},
                {"from": "nome", "to": "inventato"},
            ]

        app.ask_model = fake
        filled = app.complete_with_model({
            "columns": ["nome", "codice_strano"],
            "fields": [{"name": "name", "label": "Nome"}],
            "samples": [{"nome": "Nord", "codice_strano": "C9", "password": "segreto"}],
        })
        self.assertTrue(filled["model"])
        by_from = {row["from"]: row["to"] for row in filled["rows"]}
        self.assertEqual(by_from["codice_strano"], "name")
        self.assertNotEqual(by_from.get("nome"), "inventato")
        self.assertNotIn("segreto", json.dumps(seen["payload"]))
        self.assertNotIn("segreto-modello", json.dumps(app.export_config()))


if __name__ == "__main__":
    unittest.main()
