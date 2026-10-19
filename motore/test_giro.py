import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(tempfile.mkdtemp())
os.environ["DB_PATH"] = str(ROOT / "motore.sqlite")
os.environ["SCAMBIO_DIR"] = str(ROOT / "scambio")

import app


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
            conn.execute("UPDATE setting SET value = '1' WHERE key = 'writes'")

    def test_orario_fisso_sul_giro(self):
        row = Row(enabled=1, schedule_at="02:10", schedule_minutes=0, last_run="2026-10-18 02:12:00")
        moment = datetime(2026, 10, 19, 2, 15, 0).timestamp()
        self.assertTrue(app.pipeline_due(row, moment))
        row["last_run"] = "2026-10-19 02:12:00"
        self.assertFalse(app.pipeline_due(row, moment))

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


if __name__ == "__main__":
    unittest.main()
