# Nesso

Manuale di Nesso. Il fatto e il non fatto sono in [00-progetto.md](00-progetto.md). La fotografia di un backup di produzione non fa parte di questo repo.

L'applicazione è un middleware. Da un lato c'è EspoCRM, dall'altro un sistema esterno. I due si parlano solo attraverso questa app. La scheda di Espo, i campi e il canale non sono scritti nel codice: si configurano. Il codice sa fare quattro canali (webhook, database in lettura, file CSV, HTTP in uscita) e, per ciascuno, creare o aggiornare qualunque scheda che Espo espone nel proprio metadata.

| Capitolo | Cosa ci trovi |
|---|---|
| [00-progetto.md](00-progetto.md) | Nome, prima versione, difetti noti, evolutiva non ancora fatta (posta compresa) |
| [01-prodotto.md](01-prodotto.md) | I due oggetti dell'app, il giro di un record, che cosa significa «qualunque sistema» in questa versione |
| [02-architettura.md](02-architettura.md) | Processi, rete, volumi, avvio, confine con il database di Espo |
| [03-modello-dati.md](03-modello-dati.md) | SQLite: tabelle, slug, cancellazioni, che cosa sopravvive |
| [04-ingresso-in-espo.md](04-ingresso-in-espo.md) | Chiave, hash, ricerca, POST, PUT, conflitto 409, esempi con i record della prova |
| [05-uscita-da-espo.md](05-uscita-da-espo.md) | Cursore `modifiedAt`, sink, invio, casella |
| [06-quattro-canali.md](06-quattro-canali.md) | Contratto operativo di webhook, database, CSV e HTTP |
| [07-catalogo-espo.md](07-catalogo-espo.md) | Come una scheda e un campo diventano selezionabili, prefisso `c` |
| [08-api.md](08-api.md) | Ogni percorso HTTP, con corpo e risposta |
| [09-interfaccia.md](09-interfaccia.md) | Ogni controllo della pagina, e che cosa la pagina non fa |
| [10-stato-della-prova.md](10-stato-della-prova.md) | Configurazione e record presenti sul volume locale il 17/10/2026 |
| [11-esercizio.md](11-esercizio.md) | Avvio, fermata, database di prova, dove guardare se un giro fallisce |
| [12-token-github.md](12-token-github.md) | Token per le issue, da fare quando serve |
| [13-demo-meridia.md](13-demo-meridia.md) | Demo da impresa: processi e dati del Gruppo Meridia |

La scheda breve usata come ingresso è [../motore.md](../motore.md). L'avvio rapido è [../README.md](../README.md).
