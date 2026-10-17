# Tracker — GitHub Issues (vibeissue)

**GitHub Issues** è la **fonte di verità** per bug, task e evolutive del progetto.

I file markdown locali (piani, note, post-mortem) restano **riferimento e archivio**. Lo stato operativo (aperto / in corso / chiuso) vive su GitHub.

**Vibeissue** funziona su **Windows, macOS e Linux** con **qualsiasi agente AI** (Cursor, Claude Code, Copilot, …) o **senza agente** (CLI manuale). Documentazione: [vibeissue.github.io/docs/it](https://vibeissue.github.io/docs/it/).

---

## Configurazione repository

Lo script risolve `owner/repo` in questo ordine:

| Priorità | Sorgente |
|----------|----------|
| 1 | File `.env` → `GITHUB_REPO=owner/repo` |
| 2 | Variabile `GITHUB_REPO` nella sessione |
| 3 | File `tracker/github_repo` — una riga (creato da `adopt.py`) |

Override una tantum: `python scripts/github_issue.py --repo owner/repo list`

---

## Token GitHub

Lo script legge il token **automaticamente** (l'agente non deve chiedere comandi manuali):

| Priorità | Sorgente |
|----------|----------|
| 1 | File `.env` nella root: `GITHUB_TOKEN=github_pat_...` |
| 2 | Variabile `GITHUB_TOKEN` nella sessione corrente |
| 3 | File `.secrets/github_token` — una riga, gitignored |
| 4 | **Solo Windows:** variabili utente da registry (fallback) |

**Setup consigliato:** `GITHUB_TOKEN` in `.env` (gitignored) per token specifici del progetto. Su Windows, `.env` ha priorità su variabili utente ereditate dall'IDE.

**Alternativa file:**

```bash
mkdir -p .secrets
cp tracker/github_token.example .secrets/github_token
# modifica .secrets/github_token con il token su una riga
```

Incolla il token su una riga, salva. **Mai** committare quel file.

---

## Uso con agenti AI

Quando segnali un bug o chiedi un task, l'agente può creare o aggiornare issue GitHub:

- *«Apri issue per il bug del form login»*
- *«Crea task GitHub per dark mode»*
- *«Commenta issue #42 con il fix applicato»*

L'agente esegue `python scripts/github_issue.py ...` secondo le istruzioni nel repo:

| Piattaforma | File |
|-------------|------|
| Cursor | `.cursor/rules/github-issues.mdc` |
| Claude Code | `CLAUDE.md`, `AGENTS.md` |
| GitHub Copilot | `.github/copilot-instructions.md`, `AGENTS.md` |
| Altro | `AGENTS.md` — vedi [docs piattaforme](https://vibeissue.github.io/docs/it/platforms/overview/) |

Guida completa: [vibeissue.github.io/docs/it](https://vibeissue.github.io/docs/it/) · Sito: [vibeissue.github.io](https://vibeissue.github.io)

---

## Comandi

### Label (prima import o setup repo)

```bash
python scripts/github_issue.py labels
python scripts/github_issue.py labels --apply
```

### Import issue da manifest

Copia l'esempio se serve:

```bash
cp tracker/import-manifest.example.json tracker/import-manifest.json
python scripts/github_issue.py import --dry-run
python scripts/github_issue.py import --apply
```

Salta duplicati se trova lo stesso **Legacy ID** nel body.

### Creare issue manualmente

```bash
python scripts/github_issue.py create "Titolo breve" --body "Descrizione markdown" --labels bug,priority-high,area-frontend
```

### Modificare issue

```bash
python scripts/github_issue.py edit 12 --title "Nuovo titolo" --body "Corpo aggiornato" --labels task,priority-low
```

`--labels` sostituisce l'intero set di label.

### Elencare issue

```bash
python scripts/github_issue.py list
python scripts/github_issue.py list --state closed --limit 50
```

### Commento e chiusura

```bash
python scripts/github_issue.py comment 12 --body "Fix in PR #99"
python scripts/github_issue.py close 12
python scripts/github_issue.py close-batch 10 11 12 --reason "Duplicati"
```

---

## Struttura cartella

| File | Ruolo |
|------|--------|
| `labels.yml` | Definizione label GitHub |
| `import-manifest.example.json` | Esempio batch import |
| `import-manifest.json` | Manifest reale (gitignored, copia da example) |
| `github_repo` | Slug repo (gitignored, creato da adopt) |
| `github_repo.example` | Template slug |
| `github_token.example` | Template token (non usare in produzione) |

---

## Commit e PR

Nei commit e nelle PR che risolvono lavoro tracciato, referenzia l'issue:

```
fix(auth): handle Safari redirect loop

Fixes #NN
```
