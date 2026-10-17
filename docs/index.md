# Nesso

Manuale di Nesso. Il fatto e il non fatto sono in [00-progetto.md](00-progetto.md). La fotografia di un backup di produzione non fa parte di questo repo.

L'applicazione è un middleware. Da un lato c'è EspoCRM, dall'altro un sistema esterno. I due si parlano solo attraverso questa app. La scheda di Espo, i campi e il canale non sono scritti nel codice: si configurano. Il codice sa fare quattro canali (webhook, database in lettura, file CSV, HTTP in uscita) e, per ciascuno, creare o aggiornare qualunque scheda che Espo espone nel proprio metadata.

| Capitolo | Cosa ci trovi |
|---|---|
| [Progetto](00-progetto.md) | Nome, prima versione, difetti noti, evolutiva non ancora fatta |
| [Prodotto](01-prodotto.md) | I due oggetti dell'app, il giro di un record, che cosa significa «qualunque sistema» in questa versione |
| [Architettura](02-architettura.md) | Processi, rete, volumi, avvio, confine con il database di Espo |
| [Modello dati](03-modello-dati.md) | SQLite: tabelle, slug, cancellazioni, che cosa sopravvive |
| [Ingresso in Espo](04-ingresso-in-espo.md) | Chiave, hash, ricerca, POST, PUT, conflitto 409 |
| [Uscita da Espo](05-uscita-da-espo.md) | Cursore `modifiedAt`, sink, invio, casella |
| [Quattro canali](06-quattro-canali.md) | Contratto operativo di webhook, database, CSV e HTTP |
| [Catalogo Espo](07-catalogo-espo.md) | Come una scheda e un campo diventano selezionabili, collegamenti compresi |
| [API](08-api.md) | Ogni percorso HTTP, con corpo e risposta |
| [Interfaccia](09-interfaccia.md) | Menu, schermate, quattro passi |
| [Stato della prova](10-stato-della-prova.md) | Configurazione e record presenti sul volume locale il 17/10/2026 |
| [Esercizio](11-esercizio.md) | Avvio, fermata, database di prova, manuale MkDocs |
| [Token GitHub](12-token-github.md) | Token per le issue, da fare quando serve |
| [Demo Meridia](13-demo-meridia.md) | Demo da impresa: processi e dati del Gruppo Meridia |
| [Marchio](14-marchio.md) | Marchio, lockup e file in `assets/logo` |

L'avvio dello stack è nel README della root del repository. La scheda breve, sempre nella root, è `motore.md`.
