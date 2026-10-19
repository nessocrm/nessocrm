import unittest
from datetime import datetime

import carico
import frasi


CAMPI = [
    {"name": "name", "label": "Nome"},
    {"name": "emailAddress", "label": "Email"},
    {"name": "phoneNumber", "label": "Telefono"},
    {"name": "billingAddressCity", "label": "Città"},
    {"name": "cPartitaIva", "label": "Partita IVA"},
]


class Lingua(unittest.TestCase):
    def test_italiano_resta_la_frase_di_partenza(self):
        self.assertEqual(frasi.traduci("Espo risponde.", "it"), "Espo risponde.")
        self.assertEqual(frasi.traduci("frase mai vista", "en"), "frase mai vista")

    def test_inglese_e_i_modelli(self):
        self.assertEqual(frasi.traduci("Inizio", "en"), "Home")
        self.assertEqual(frasi.traduci("manca la colonna codice", "en"), "Missing column codice.")
        self.assertEqual(
            frasi.traduci("aggiornato dal gestionale il {data} alle {ora}", "en", data="19/10/2026", ora="09:50"),
            "updated from the ERP on 19/10/2026 at 09:50",
        )

    def test_il_badge_di_default_resta_italiano(self):
        when = datetime(2026, 10, 19, 9, 50)
        self.assertEqual(carico.badge_gestionale(when), "aggiornato dal gestionale il 19/10/2026 alle 09:50")
        self.assertIn("updated from the ERP", carico.badge_gestionale(when, "en"))


class Proposta(unittest.TestCase):
    def test_nomi_italiani_propongono_account_e_il_fiscale(self):
        rows = carico.propose(["Ragione sociale", "P. IVA", "Nota interna"], "it", CAMPI, [{"P. IVA": "18/10/2026", "Ragione sociale": "Meridia"}])
        by_name = {row["from"]: row for row in rows}
        self.assertEqual(by_name["Ragione sociale"]["to"], "name")
        self.assertTrue(by_name["Ragione sociale"]["known"])
        self.assertEqual(by_name["P. IVA"]["to"], "cPartitaIva")
        self.assertEqual(by_name["P. IVA"]["reading"], "2026-10-18")
        self.assertFalse(by_name["Nota interna"]["known"])
        self.assertEqual(by_name["Nota interna"]["to"], "")

    def test_i_sinonimi_inglesi_non_sono_quelli_italiani(self):
        italian = carico.propose_column("Company name", "it", CAMPI)
        english = carico.propose_column("Company name", "en", CAMPI)
        self.assertFalse(italian["known"])
        self.assertEqual(english["to"], "name")
        self.assertEqual(carico.propose_column("Ragione sociale", "en", CAMPI)["known"], False)

    def test_la_ricetta_non_scrive_e_resta_un_abbinamento(self):
        recipe = carico.recipe_anagrafiche(CAMPI)
        self.assertEqual(recipe["id"], "anagrafiche")
        self.assertEqual(recipe["entity"], "Account")
        self.assertEqual(recipe["externalIdField"], "codice")
        self.assertIn("non è un connettore", recipe["noteKey"].lower())
        names = {row["from"]: row["to"] for row in recipe["rows"]}
        self.assertEqual(names["ragione sociale"], "name")
        self.assertEqual(names["partita iva"], "cPartitaIva")
        recipe["rows"][0]["to"] = "altro"
        self.assertEqual(recipe["rows"][0]["to"], "altro")


if __name__ == "__main__":
    unittest.main()
