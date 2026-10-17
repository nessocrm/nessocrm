# Nesso

Questo è il repository del prodotto. Remoto: https://github.com/nessocrm/nessocrm. Cartella: `C:\Users\ndoni\Documents\github\nessocrm`.

Il backup di produzione è un'altra cartella: `C:\Users\ndoni\Documents\bitbuket\2026-10-14-backup-espocrm-produzione`. Quella cartella non si modifica, non si sposta e non entra in questo repo.

## Confine

- Espo e il sistema esterno si parlano solo via API HTTP di Espo. Niente SQL sulle tabelle di Espo.
- La prova locale usa un Espo vuoto. I dump di produzione non si montano e non si importano.
- L'Advanced Pack sta solo in `local/advanced-pack/`, ignorato da git. Non committarlo e non pubblicarlo. Non copiare insieme i dati, gli allegati o la configurazione di produzione.
- `analisi/` e `evoluzione/` del backup descrivono quel sistema. Non sono il backlog di Nesso. Il backlog è `docs/00-progetto.md`.
- Non committare segreti, database SQLite, né i CSV in `scambio/`.

## Git

Il commit e il push partono da questa cartella, verso `nessocrm/nessocrm`. Non inizializzare git nel backup.

## Issue

Bug, evolutive e task si aprono su GitHub Issues con vibeissue, dalla root del repo:

```
python scripts/github_issue.py list
```

Il token non si incolla in chat. Sta in `.env`, nella variabile `GITHUB_TOKEN`, oppure in `.secrets/github_token`. La regola per Cursor è `.cursor/rules/github-issues.mdc`.
