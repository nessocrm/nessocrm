# Nesso

Nesso collega EspoCRM a un sistema esterno, solo tramite le API di Espo. Il canale, la scheda e i campi si configurano.

Repository: https://github.com/nessocrm/nessocrm

| Cosa | Dove |
|---|---|
| Fatto e mancante | [docs/00-progetto.md](docs/00-progetto.md) |
| Manuale | [docs/README.md](docs/README.md) |
| Espo di prova | http://localhost:8088 (`admin` / `locale-admin`) |
| Applicazione | http://localhost:8091 |

Avvio, da questa cartella:

```
docker compose up -d --build
```

Il primo avvio scarica le immagini, installa un Espo vuoto e carica la demo del Gruppo Meridia: clienti, fornitori, contatti, sedi, richieste, offerte, contratti, commesse, interventi, fatture, ticket e visite. Sono dati inventati di un'impresa industriale. Il percorso è in [docs/13-demo-meridia.md](docs/13-demo-meridia.md). I dati di un backup di produzione non fanno parte di questo repo e non vanno importati.

L'Advanced Pack, commerciale, sta solo in `local/advanced-pack/` su questo PC. Git lo ignora. Il compose lo monta sull'istanza locale. Non va committato e non va pubblicato.

I CSV si depositano in `scambio/<id-collegamento>/`.
