import unittest
from datetime import datetime

import carico


class PadroneDelCampo(unittest.TestCase):
    def test_la_sorgente_svuota_solo_i_suoi_campi(self):
        write, watch = carico.plan_fields(
            [
                {"to": "description", "owner": "sorgente", "present": True, "value": ""},
                {"to": "note", "owner": "espo", "present": True, "value": ""},
            ],
            {"description": "vecchia", "note": "di Chiara"},
            creating=False,
        )
        self.assertEqual(write["description"], "")
        self.assertNotIn("note", write)
        self.assertEqual(watch, [])

    def test_un_campo_di_espo_diverso_finisce_in_coda(self):
        write, watch = carico.plan_fields(
            [{"to": "note", "owner": "espo", "present": True, "value": "dal gestionale"}],
            {"note": "di Chiara"},
            creating=False,
        )
        self.assertNotIn("note", write)
        self.assertEqual(watch[0]["today"], "di Chiara")
        self.assertEqual(watch[0]["incoming"], "dal gestionale")

    def test_in_creazione_si_scrive_anche_il_campo_di_espo(self):
        write, watch = carico.plan_fields(
            [{"to": "note", "owner": "espo", "present": True, "value": "prima nota"}],
            {},
            creating=True,
        )
        self.assertEqual(write["note"], "prima nota")
        self.assertEqual(watch, [])


class Anteprima(unittest.TestCase):
    def test_la_riga_pericolosa_e_il_conteggio(self):
        diffs = carico.dangerous_diffs([{"field": "note", "today": "a", "incoming": "b"}])
        self.assertEqual(diffs[0]["field"], "note")
        self.assertEqual(carico.classify_row(True, {"name": "Nord"}, None, diffs), "aggiornato")
        self.assertEqual(carico.classify_row(False, {"name": "Nord"}, None, []), "creato")
        self.assertEqual(carico.classify_row(True, {}, {"name": "Nord"}, [{"field": "note"}]), "in coda")


class Chiusura(unittest.TestCase):
    def test_la_prima_volta_chiede_conferma(self):
        decision = carico.close_decision(["acme:1"], confirmed=False, has_status=True, cursor_active=False)
        self.assertEqual(decision["action"], "conferma")
        self.assertEqual(decision["keys"], ["acme:1"])

    def test_dopo_la_conferma_chiude(self):
        decision = carico.close_decision(["acme:1"], confirmed=True, has_status=True, cursor_active=False)
        self.assertEqual(decision["action"], "chiudi")

    def test_senza_stato_non_inventa_un_campo(self):
        decision = carico.close_decision(["acme:1"], confirmed=True, has_status=False, cursor_active=False)
        self.assertEqual(decision["action"], "salta")

    def test_il_cursore_non_chiude(self):
        decision = carico.close_decision(["acme:1"], confirmed=True, has_status=True, cursor_active=True)
        self.assertEqual(decision["action"], "salta")

    def test_spariti(self):
        self.assertEqual(carico.disappeared({"a", "b"}, {"b", "c"}), ["a"])


class InterruttoreELettura(unittest.TestCase):
    def test_interruttore_spento(self):
        held, reason = carico.reading(False, False)
        self.assertTrue(held)
        self.assertIn("ferme", reason)

    def test_modalita_lettura_resta_accesa(self):
        held, reason = carico.reading(True, True)
        self.assertTrue(held)
        self.assertIn("lettura", reason)
        until = carico.read_deadline(48, datetime(2026, 10, 19, 10, 0, 0))
        self.assertEqual(until, "2026-10-21 10:00:00")

    def test_scrittura_libera(self):
        self.assertFalse(carico.reading(False, True)[0])


class Annulla(unittest.TestCase):
    def test_non_tocca_un_campo_cambiato_dopo(self):
        self.assertTrue(carico.restorable("vecchia", "nuova", "nuova"))
        self.assertFalse(carico.restorable("vecchia", "nuova", "di Chiara"))
        self.assertFalse(carico.restorable("vecchia", "nuova", None))


class Fiscale(unittest.TestCase):
    def test_forma_e_duplicato(self):
        self.assertEqual(carico.normalize_fiscal("IT 12345678901"), ("piva", "12345678901"))
        self.assertEqual(carico.normalize_fiscal("rssmra80a01h501u"), ("cf", "RSSMRA80A01H501U"))
        with self.assertRaises(RuntimeError):
            carico.normalize_fiscal("123")
        self.assertTrue(carico.fiscal_blocks_create("altro", None))
        self.assertFalse(carico.fiscal_blocks_create("stesso", "stesso"))
        self.assertTrue(carico.is_fiscal_field("cPartitaIva", "Partita IVA"))


class Pagine(unittest.TestCase):
    def test_legge_oltre_il_vecchio_tetto(self):
        def fetch(size, offset):
            start = offset
            end = min(offset + size, 650)
            return list(range(start, end))

        rows = carico.collect_pages(fetch, 200)
        self.assertEqual(len(rows), 650)
        self.assertEqual(rows[0], 0)
        self.assertEqual(rows[-1], 649)


class Orario(unittest.TestCase):
    def test_parte_una_volta_dopo_le_0210(self):
        now = datetime(2026, 10, 19, 2, 15, 0)
        self.assertTrue(carico.fixed_due("02:10", None, now))
        self.assertFalse(carico.fixed_due("02:10", "2026-10-19 02:12:00", now))
        self.assertFalse(carico.fixed_due("02:10", None, datetime(2026, 10, 19, 1, 0, 0)))
        self.assertTrue(carico.fixed_due("02:10", "2026-10-18 02:12:00", now))


class Qualita(unittest.TestCase):
    def test_date_elenco_e_nome_campo(self):
        self.assertEqual(carico.parse_date("18/10/2026"), "2026-10-18")
        self.assertEqual(carico.parse_date("2026-10-18"), "2026-10-18")
        self.assertEqual(carico.parse_date("18-10-2026"), "2026-10-18")
        self.assertEqual(carico.check_quality("Aperta", "enum", ["Aperta", "Chiusa"], "stato"), "Aperta")
        with self.assertRaises(RuntimeError) as raised:
            carico.check_quality("Boh", "enum", ["Aperta"], "stato")
        self.assertIn("campo stato", str(raised.exception))


class ColonnaObbligatoria(unittest.TestCase):
    def test_manca_la_colonna_non_la_cella(self):
        required = carico.required_columns("codice", [{"from": "piva", "required": True}, {"from": "citta"}])
        self.assertEqual(carico.missing_headers(["nome", "citta"], required), ["codice", "piva"])
        self.assertEqual(carico.missing_headers(["codice", "piva"], required), [])


class TreRighe(unittest.TestCase):
    def test_tre_valori_e_la_data_letta(self):
        rows = [{"quando": "18/10/2026"}, {"quando": "2026-11-01"}, {"quando": "no"}, {"quando": "01/01/2020"}]
        sample = carico.column_samples(rows, "quando", carico.parse_date)
        self.assertEqual(sample["values"], ["18/10/2026", "2026-11-01", "no"])
        self.assertEqual(sample["interpreted"][0], "2026-10-18")
        self.assertIn("non riconosciuta", sample["interpreted"][2])


class Riepilogo(unittest.TestCase):
    def test_la_riga_ha_i_conteggi(self):
        text = carico.summary_line(
            {"created": 2, "updated": 1, "closed": 3, "unchanged": 4, "failed": 5, "held": True, "first": ""},
            "10 righe",
        )
        self.assertIn("2 create", text)
        self.assertIn("3 chiuse", text)
        self.assertIn("5 scartate", text)
        self.assertIn("senza scrivere", text)


class Visibilita(unittest.TestCase):
    def test_team_e_persona_senza_creare_utenti(self):
        rules = carico.compile_visibility({"teamFrom": "area", "assignFrom": "agente", "onMiss": "skip"})
        self.assertEqual(rules[0]["lookupEntity"], "Team")
        self.assertEqual(rules[1]["lookupEntity"], "User")
        self.assertTrue(rules[1]["neverCreate"])
        with self.assertRaises(RuntimeError):
            carico.compile_visibility({"assignFrom": "agente", "onMiss": "create"})

    def test_scheda_senza_stato(self):
        self.assertIsNone(carico.close_field_of(["name", "description"]))
        self.assertEqual(carico.close_field_of(["status"], {"status": ["Closed"]}), ("status", "Closed"))


class Mattina(unittest.TestCase):
    def test_percentuale_solo_se_il_giro_di_oggi_e_riuscito(self):
        now = datetime(2026, 10, 19, 8, 0, 0)
        mai = carico.morning_alignment(0, 0, None, None, now)
        self.assertIsNone(mai["percent"])
        self.assertIn("Nessun giro", mai["text"])
        ok = carico.morning_alignment(4, 3, "2026-10-19 02:12:00", "ok", now)
        self.assertEqual(ok["percent"], 75)
        self.assertIn("02:12", ok["text"])
        fallito = carico.morning_alignment(4, 3, "2026-10-18 02:12:00", "errore", now)
        self.assertIsNone(fallito["percent"])
        self.assertEqual(fallito["tone"], "rosso")
        self.assertIn("non è riuscito", fallito["text"])
        self.assertIn("2026-10-18 02:12:00", fallito["text"])
        counts = {"created": 0, "updated": 0, "unchanged": 8, "failed": 0, "queued": 0}
        self.assertEqual(
            carico.success_stamp(None, "2026-10-19 09:49:40", "ok", counts),
            "2026-10-19 09:49:40",
        )
        self.assertIsNone(carico.success_stamp(None, "2026-10-19 09:49:40", "errore", counts))


class QuadraturaNumeri(unittest.TestCase):
    def test_un_cliente_in_piu_e_lo_scarto_importi(self):
        result = carico.quadratura({"A", "B"}, {"A"}, 30.5, 10.5)
        self.assertFalse(result["ok"])
        self.assertEqual(result["sourceCount"], 2)
        self.assertEqual(result["espoCount"], 1)
        self.assertEqual(result["onlySource"], 1)
        self.assertEqual(result["amountGap"], 20.0)
        self.assertIn("solo in sorgente", result["text"])
        pari = carico.quadratura({"A"}, {"A"}, None, None)
        self.assertTrue(pari["ok"])


class FileAtteso(unittest.TestCase):
    def test_rosso_solo_dopo_l_ora_e_finche_non_riesce(self):
        atteso = "07:00"
        self.assertEqual(
            carico.file_wait(datetime(2026, 10, 19, 6, 0), atteso, "2026-10-18 02:12:00", False),
            "presto",
        )
        self.assertEqual(
            carico.file_wait(datetime(2026, 10, 19, 7, 0), atteso, "2026-10-18 02:12:00", False),
            "mancante",
        )
        self.assertEqual(
            carico.file_wait(datetime(2026, 10, 19, 7, 30), atteso, "2026-10-18 02:12:00", True),
            "in_attesa",
        )
        self.assertEqual(
            carico.file_wait(datetime(2026, 10, 19, 8, 0), atteso, "2026-10-19 07:40:00", False),
            "ok",
        )


class Badge(unittest.TestCase):
    def test_gestionale_o_persona_non_il_motore(self):
        when = datetime(2026, 10, 19, 2, 12)
        self.assertEqual(carico.badge_gestionale(when), "aggiornato dal gestionale il 19/10/2026 alle 02:12")
        self.assertIn("Chiara", carico.badge_persona("Chiara Fabbri", when))
        self.assertEqual(
            carico.badge_decision("2026-10-19 02:12:00", "2026-10-19 09:40:00", "Chiara Fabbri", {"admin", "Admin"}),
            "persona",
        )
        self.assertEqual(
            carico.badge_decision("2026-10-19 02:12:00", "2026-10-19 09:41:00", "Admin", {"admin", "Admin"}),
            "niente",
        )


if __name__ == "__main__":
    unittest.main()
