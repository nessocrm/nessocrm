# Nesso

Questo è il repository del prodotto. Remoto: https://github.com/nessocrm/nessocrm. Cartella: `C:\Users\ndoni\Documents\github\nessocrm`.

Il backup di produzione è un'altra cartella: `C:\Users\ndoni\Documents\bitbuket\2026-10-14-backup-espocrm-produzione`. Quella cartella non si modifica, non si sposta e non entra in questo repo.

## Confine

- Espo e il sistema esterno si parlano solo via API HTTP di Espo. Niente SQL sulle tabelle di Espo.
- La prova locale usa un Espo vuoto. I dump di produzione non si montano e non si importano.
- L'Advanced Pack sta solo in `local/advanced-pack/`, ignorato da git. Non committarlo e non pubblicarlo. Non copiare insieme i dati, gli allegati o la configurazione di produzione.
- `analisi/` e `evoluzione/` del backup descrivono quel sistema. Non sono il backlog di Nesso. Il backlog è `docs/00-progetto.md`.
- Non committare segreti, database SQLite, né i CSV in `scambio/`.

## Documentazione

Ogni modifica al prodotto, alla demo, alle API, all'interfaccia o al marchio aggiorna i docs nello stesso cambio. Vale anche per un giro di issue: non si chiude il giro se i capitoli raccontano ancora il comportamento precedente.

- Si aggiorna il capitolo che descrive già quel comportamento. Si rileggono le frasi vecchie (tetti, file che si spostano sempre, campi che non si svuotano, risposte di API senza i conteggi nuovi) e si correggono.
- Una pagina nuova si crea solo se nessun capitolo parla di quella funzione. In quel caso si aggiunge in `docs/`, nella chiave `nav` di `mkdocs.yml` e nella tabella di `docs/index.md`.
- Il manuale è bilingue. L'italiano in `docs/` è la lingua di partenza; l'inglese è lo stesso capitolo in `docs/en/`, con lo stesso nome di file. Si aggiornano insieme. Il build `py -3 -m mkdocs build --strict` deve passare. Niente link che escono da `docs/`: un file della root si cita per nome, non con un percorso relativo.
- Il fatto e il non fatto restano in `docs/00-progetto.md`. Una cosa fatta si toglie dall'elenco di ciò che manca.
- Il marchio sta in `assets/logo`. Se cambia il segno, si rilancia `py -3 scripts/build_logo.py` e si aggiorna `docs/14-marchio.md`.

## Git

Il commit e il push partono da questa cartella, verso `nessocrm/nessocrm`. Non inizializzare git nel backup.

## Issue

Bug, evolutive e task si aprono su GitHub Issues con vibeissue, dalla root del repo:

```
python scripts/github_issue.py list
```

Il token non si incolla in chat. Sta in `.env`, nella variabile `GITHUB_TOKEN`, oppure in `.secrets/github_token`. La regola per Cursor è `.cursor/rules/github-issues.mdc`.
