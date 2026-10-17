# Nesso

Il progetto si chiama Nesso. L'applicazione sta in questa cartella: è il legame fra EspoCRM e un sistema esterno. Il canale, la scheda e l'abbinamento dei campi si configurano.

Che cosa è già fatto e che cosa manca, posta del motore compresa: [docs/00-progetto.md](docs/00-progetto.md).

Il manuale è in [docs/README.md](docs/README.md). Undici capitoli: prodotto, architettura, tabelle, ingresso, uscita, i quattro canali, catalogo Espo, API, pagina, stato reale della prova, esercizio.

| Per fare | Apri |
|---|---|
| Capire che oggetto crea l'utente | [docs/01-prodotto.md](docs/01-prodotto.md) |
| Vedere processi, porte e volumi | [docs/02-architettura.md](docs/02-architettura.md) |
| Seguire un record fino al POST su Espo | [docs/04-ingresso-in-espo.md](docs/04-ingresso-in-espo.md) |
| Seguire un record che esce da Espo | [docs/05-uscita-da-espo.md](docs/05-uscita-da-espo.md) |
| Chiamare l'API | [docs/08-api.md](docs/08-api.md) |
| Vedere che cosa c'è adesso sul PC | [docs/10-stato-della-prova.md](docs/10-stato-della-prova.md) |
| Accendere lo stack | [README.md](README.md) e [docs/11-esercizio.md](docs/11-esercizio.md) |

La prova è su http://localhost:8091, Espo su http://localhost:8088 (`admin` / `locale-admin`). I dump di produzione non sono montati.

La fotografia di un backup di produzione non sta in questo repo e non descrive questa applicazione.
