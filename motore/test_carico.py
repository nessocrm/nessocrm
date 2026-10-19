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


class ChiaveComposta(unittest.TestCase):
    def test_una_colonna_resta_la_cella(self):
        self.assertEqual(carico.compose_identity({"codice": "C001"}, ["codice"]), "C001")
        self.assertEqual(carico.compose_identity({"codice": "C0|01"}, ["codice"]), "C0|01")

    def test_due_societa_non_si_mescolano(self):
        columns = ["societa", "codice"]
        nord = carico.compose_identity({"societa": "MI", "codice": "C001"}, columns)
        sud = carico.compose_identity({"societa": "TO", "codice": "C001"}, columns)
        self.assertEqual(nord, "MI|C001")
        self.assertEqual(sud, "TO|C001")
        self.assertNotEqual(nord, sud)
        again = carico.compose_identity({"societa": "MI", "codice": "C001"}, columns)
        self.assertEqual(again, nord)

    def test_manca_una_parte(self):
        with self.assertRaises(RuntimeError):
            carico.compose_identity({"societa": "MI", "codice": ""}, ["societa", "codice"])

    def test_le_tre_righe_vere(self):
        rows = [
            {"societa": "MI", "codice": "C001"},
            {"societa": "MI", "codice": "C002"},
            {"societa": "TO", "codice": "C001"},
            {"societa": "TO", "codice": "C009"},
        ]
        self.assertEqual(carico.identity_preview(rows, ["societa", "codice"]), ["MI|C001", "MI|C002", "TO|C001"])

    def test_le_colonne_obbligatorie_restano_una(self):
        required = carico.required_columns("codice", [{"from": "piva", "required": True}])
        self.assertEqual(required, ["codice", "piva"])


class FinestraEPiano(unittest.TestCase):
    def test_senza_finestre_si_scrive(self):
        decision = carico.silence_decision("2026-10-19", [], False)
        self.assertEqual(decision["action"], "scrivi")

    def test_dentro_la_finestra_il_file_aspetta(self):
        windows = [{"start": "2026-10-18", "end": "2026-10-20", "reason": "inventario"}]
        decision = carico.silence_decision("2026-10-19", windows, False)
        self.assertEqual(decision["action"], "attesa")
        self.assertEqual(decision["reason"], "inventario")

    def test_dopo_la_finestra_il_file_non_parte(self):
        decision = carico.silence_decision("2026-10-21", [{"start": "2026-10-18", "end": "2026-10-20", "reason": "fiera"}], True)
        self.assertEqual(decision["action"], "fermo")

    def test_il_gradino_senza_piano_si_accende(self):
        allowed, reason = carico.step_may_enable(False, 2, False)
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_il_gradino_seguente_aspetta_la_conferma(self):
        allowed, reason = carico.step_may_enable(True, 2, False)
        self.assertFalse(allowed)
        self.assertIn("precedente", reason)
        later, _reason = carico.step_may_enable(True, 2, True)
        self.assertTrue(later)

    def test_la_conferma_vuole_l_anteprima(self):
        allowed, reason = carico.step_may_confirm(True, False)
        self.assertFalse(allowed)
        self.assertIn("anteprima", reason)
        seen, _reason = carico.step_may_confirm(True, True)
        self.assertTrue(seen)


CAMPI_ACCOUNT = [
    {"name": "name", "label": "Nome"},
    {"name": "emailAddress", "label": "Email"},
    {"name": "phoneNumber", "label": "Telefono"},
    {"name": "billingAddressCity", "label": "Città"},
    {"name": "cPartitaIva", "label": "Partita IVA"},
    {"name": "shippingAddressStreet", "label": "Indirizzo di spedizione"},
    {"name": "shippingAddressCity", "label": "Città di spedizione"},
    {"name": "shippingAddressPostalCode", "label": "CAP"},
    {"name": "shippingAddressState", "label": "Provincia"},
    {"name": "shippingAddressCountry", "label": "Nazione"},
]
CAMPI_CONTATTO = [
    {"name": "firstName", "label": "Nome"},
    {"name": "lastName", "label": "Cognome"},
    {"name": "emailAddress", "label": "Email"},
    {"name": "phoneNumber", "label": "Telefono"},
]


class RicetteSediEContatti(unittest.TestCase):
    def test_i_contatti_sono_contact_e_l_azienda_e_un_legame(self):
        recipe = carico.recipe_contatti(CAMPI_CONTATTO)
        self.assertEqual(recipe["entity"], "Contact")
        self.assertEqual(recipe["externalIdField"], "codice")
        self.assertIn("non è un connettore", recipe["noteKey"].lower())
        by_name = {row["from"]: row for row in recipe["rows"]}
        self.assertEqual(by_name["nome"]["to"], "firstName")
        self.assertEqual(by_name["cognome"]["to"], "lastName")
        self.assertEqual(by_name["azienda"]["role"], "link")
        self.assertEqual(by_name["azienda"]["lookupEntity"], "Account")
        self.assertEqual(by_name["azienda"]["lookupBy"], "name")

    def test_le_sedi_scrivono_l_indirizzo_di_spedizione(self):
        recipe = carico.recipe_sedi(CAMPI_ACCOUNT)
        self.assertEqual(recipe["entity"], "Account")
        self.assertEqual(recipe["externalIdField"], "codice")
        by_name = {row["from"]: row for row in recipe["rows"]}
        self.assertEqual(by_name["indirizzo"]["to"], "shippingAddressStreet")
        self.assertEqual(by_name["cap"]["to"], "shippingAddressPostalCode")
        self.assertEqual(by_name["città"]["to"], "shippingAddressCity")
        senza = {row["from"]: row["to"] for row in carico.recipe_sedi([{"name": "name"}])["rows"]}
        self.assertEqual(senza["indirizzo"], "")

    def test_l_anagrafica_resta_account(self):
        recipe = carico.recipe_anagrafiche(CAMPI_ACCOUNT)
        self.assertEqual(recipe["entity"], "Account")
        self.assertEqual(recipe["rows"][0]["to"], "name")
        self.assertEqual(recipe["rows"][1]["to"], "cPartitaIva")


class FoglioAbbinamento(unittest.TestCase):
    def test_il_foglio_tiene_il_padrone_e_non_il_legame(self):
        pipelines = [
            {
                "id": "clienti",
                "direction": "in",
                "mapping": [
                    {"from": "nome", "to": "name", "transform": "copy", "owner": "espo", "required": True},
                    {"from": "azienda", "to": "accountId", "transform": "lookup", "lookupEntity": "Account", "lookupBy": "name"},
                ],
            },
            {"id": "uscita", "direction": "out", "mapping": [{"from": "name", "to": "nome", "transform": "copy"}]},
        ]
        text = carico.sheet_csv(pipelines, "it")
        self.assertNotIn("uscita", text)
        self.assertNotIn("azienda", text)
        parsed = carico.parse_sheet(text)
        self.assertEqual(parsed[0]["owner"], "espo")
        self.assertTrue(parsed[0]["required"])
        revised = carico.apply_sheet(pipelines[0]["mapping"], parsed)
        by_from = {row["from"]: row for row in revised}
        self.assertEqual(by_from["nome"]["owner"], "espo")
        self.assertEqual(by_from["azienda"]["transform"], "lookup")
        english = carico.parse_sheet(carico.sheet_csv(pipelines, "en"))
        self.assertEqual(english[0]["pipeline"], "clienti")
        self.assertTrue(english[0]["required"])

    def test_una_colonna_ripetuta_e_un_foglio_vuoto_si_rifiutano(self):
        with self.assertRaises(RuntimeError):
            carico.apply_sheet(
                [{"from": "nome", "to": "name", "transform": "copy"}],
                [{"from": "nome", "to": "name"}, {"from": "nome", "to": "emailAddress"}],
            )
        with self.assertRaises(RuntimeError):
            carico.parse_sheet("")
        with self.assertRaises(RuntimeError):
            carico.apply_sheet(
                [{"from": "nome", "to": "name", "transform": "copy"}],
                [{"from": "", "to": ""}],
            )


class PaginaConsegna(unittest.TestCase):
    def test_gli_indirizzi_e_il_padrone_senza_segreti(self):
        page = carico.consegna(
            "http://localhost:8091",
            "http://localhost:8088",
            False,
            [{
                "id": "clienti",
                "name": "Clienti",
                "direction": "in",
                "espo_entity": "Account",
                "enabled": 1,
                "schedule_at": "02:10",
                "schedule_minutes": 0,
                "connection_id": "file",
                "read_only": 0,
                "mapping": [{"from": "nome", "to": "name", "owner": "espo", "transform": "copy"}],
            }],
            [{
                "id": "file",
                "name": "File notte",
                "kind": "csv",
                "config": {"password": "segreto-demo", "token": "tok-segreto"},
                "url": "http://localhost:8091/hook/file/tok-segreto",
            }],
            [{"start_on": "2026-12-01", "end_on": "2026-12-31", "reason": "chiusura", "pipeline_id": ""}],
        )
        blob = str(page)
        self.assertNotIn("segreto", blob)
        self.assertNotIn("hook", blob)
        self.assertNotIn("password", blob)
        self.assertEqual(page["nesso"], "http://localhost:8091")
        self.assertEqual(page["espo"], "http://localhost:8088")
        self.assertFalse(page["writesEnabled"])
        self.assertEqual(page["integrations"][0]["scheduleAt"], "02:10")
        self.assertEqual(page["integrations"][0]["connection"], "File notte")
        self.assertEqual(page["integrations"][0]["owners"][0]["owner"], "espo")
        self.assertEqual(page["silence"][0]["reason"], "chiusura")


class ListinoPdfFasePrivacy(unittest.TestCase):
    def test_il_listino_e_product_e_non_inventa_una_scheda(self):
        fields = [
            {"name": "name"},
            {"name": "partNumber"},
            {"name": "unitPrice"},
            {"name": "unitPriceCurrency"},
        ]
        recipe = carico.recipe_listino(fields)
        self.assertEqual(recipe["entity"], "Product")
        self.assertNotIn("CListino", str(recipe))
        payload = carico.listino_payload({"codice": "P1", "descrizione": "Vite", "prezzo": 2.5, "valuta": "EUR"})
        self.assertEqual(payload["entity"], "Product")
        self.assertEqual(payload["name"], "Vite")
        self.assertEqual(payload["partNumber"], "P1")
        self.assertEqual(payload["unitPrice"], 2.5)
        self.assertEqual(payload["unitPriceCurrency"], "EUR")
        vuoto = {row["from"]: row["to"] for row in carico.recipe_listino([{"name": "name"}])["rows"]}
        self.assertEqual(vuoto["prezzo"], "")

    def test_il_pdf_vuole_la_chiave_intera(self):
        keys = ["C001", "C0012", "ord"]
        self.assertEqual(carico.match_pdf("fattura-C0012.pdf", keys), "C0012")
        self.assertEqual(carico.match_pdf("fattura-C001.pdf", keys), "C001")
        self.assertEqual(carico.match_pdf("ordine.pdf", keys), "")
        self.assertEqual(carico.match_pdf("senza.pdf", ["C001"]), "")

    def test_la_fase_non_scatta_se_e_gia_quella(self):
        self.assertEqual(carico.stage_proposal("Prospecting", "Closed Won"), "Closed Won")
        self.assertEqual(carico.stage_proposal("Closed Won", "Closed Won"), "")
        self.assertEqual(carico.stage_proposal("Prospecting", ""), "")

    def test_l_export_non_cancella_e_salta_la_password(self):
        rows = [
            {"at": "2026-10-19", "entity": "Contact", "external_key": "CNT-1", "espo_id": "c1", "field": "emailAddress", "value": "a@b.c"},
            {"at": "2026-10-19", "entity": "Contact", "external_key": "CNT-1", "espo_id": "c1", "field": "password", "value": "segreto"},
            {"at": "2026-10-19", "entity": "Account", "external_key": "C001", "espo_id": "a1", "field": "name", "value": "Nord"},
        ]
        exported = carico.privacy_export(rows, "CNT-1", "C001")
        self.assertEqual(len(rows), 3)
        self.assertEqual([item["field"] for item in exported], ["emailAddress", "name"])
        self.assertEqual(carico.privacy_export(rows, "", ""), [])


class IngressoRuoloAvviso(unittest.TestCase):
    def test_chi_lancia_non_cambia_labbinamento(self):
        self.assertFalse(carico.gesture_can("lancia", "POST", "/api/pipelines"))
        self.assertFalse(carico.gesture_can("lancia", "DELETE", "/api/pipelines/clienti"))
        self.assertTrue(carico.gesture_can("lancia", "POST", "/api/pipelines/clienti/run"))
        self.assertTrue(carico.gesture_can("lancia", "GET", "/api/state"))
        self.assertTrue(carico.gesture_can("cambia", "POST", "/api/pipelines"))
        self.assertFalse(carico.gesture_can("", "GET", "/api/state"))

    def test_il_ruolo_lascia_fuori_la_scheda_spenta(self):
        entities = carico.role_scope([
            {"enabled": 1, "espo_entity": "Account", "mapping": [{"lookupEntity": "Contact"}], "kind": "csv"},
            {"enabled": 0, "espo_entity": "Lead", "mapping": [], "kind": "csv"},
            {"enabled": 1, "espo_entity": "Document", "mapping": [], "kind": "pdf"},
        ])
        self.assertEqual(entities, ["Account", "Contact", "Document", "Attachment"])
        data = carico.role_data(entities)
        self.assertNotIn("Lead", data)
        self.assertEqual(data["Account"]["edit"], "all")
        self.assertEqual(carico.role_data(["User"])["User"]["create"], "no")

    def test_lavviso_e_uno_e_il_silenzio_ha_una_soglia(self):
        self.assertFalse(carico.notice_needed({"fallito"}, "fallito"))
        self.assertTrue(carico.notice_needed({"fallito"}, "silenzio"))
        moment = datetime(2026, 10, 20, 12, 0, 0)
        self.assertFalse(carico.silence_elapsed(None, 60, moment))
        self.assertFalse(carico.silence_elapsed("2026-10-20 11:30:00", 60, moment))
        self.assertTrue(carico.silence_elapsed("2026-10-20 10:00:00", 60, moment))

    def test_la_password_non_si_legge_dal_registro(self):
        record = carico.password_record("segreto-lungo")
        self.assertNotIn("segreto-lungo", record)
        self.assertTrue(carico.password_matches("segreto-lungo", record))
        self.assertFalse(carico.password_matches("altra-password", record))


if __name__ == "__main__":
    unittest.main()
