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

Il primo avvio scarica le immagini e installa un Espo vuoto. I dati di un backup di produzione non fanno parte di questo repo e non vanno importati.

I CSV si depositano in `scambio/<id-collegamento>/`.
