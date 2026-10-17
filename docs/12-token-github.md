# Token GitHub per le issue

Questa guida si fa quando serve. Fino a quel momento vibeissue è installato e il repo `nessocrm/nessocrm` è già indicato in `tracker/github_repo`. Manca solo il token.

Il token non si incolla in chat, non si mette in un issue e non si committa.

## Creare il token

1. Su GitHub, in alto a destra: **Settings**.
2. In fondo al menu laterale: **Developer settings**.
3. **Personal access tokens**, poi **Fine-grained tokens**, poi **Generate new token**.
4. Repository access: solo `nessocrm/nessocrm`.
5. Permissions, **Issues**: Read and write. Nessun altro permesso.
6. Genera e copia il valore. GitHub lo mostra una volta sola. Ha la forma `github_pat_...`.

## Dove metterlo

Una delle due strade basta. Il file di progetto ha la precedenza sulla variabile di Windows.

### File locale

Apri `.secrets/github_token` nella root del repo e scrivi il token su una sola riga, senza virgolette. La cartella `.secrets/` è già in `.gitignore`.

### Variabile utente di Windows

1. Cerca «Variabili d'ambiente» e apri quelle dell'utente.
2. Nuova variabile. Nome: `GITHUB_TOKEN`. Valore: il token.
3. Conferma tutte le finestre.
4. Chiudi e riapri Cursor. Un terminale già aperto non vede la variabile nuova.

## Prova

Da questa cartella, in un terminale nuovo:

```
python scripts/github_issue.py list
```

Un elenco, anche vuoto, significa che il collegamento funziona. Poi, una volta sola:

```
python scripts/github_issue.py labels --apply
```

Crea le etichette sul repo. Da quel momento, in chat, una richiesta del tipo «apri issue per…» usa queste issue.
