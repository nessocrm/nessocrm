![Nesso](img/lockup-su-chiaro.svg){ width="360" }

# Nesso

Manual of Nesso, in Italian and in English. What is done and what is not is in [00-progetto.md](00-progetto.md). A photograph of a production backup is not part of this repo.

The application is a middleware. EspoCRM is on one side, an external system on the other. They talk only through this app. The Espo entity, the fields and the channel are not written in the code: they are configured. The code knows four channels (webhook, database read, CSV file, outbound HTTP) and, for each of them, can create or update any entity that Espo exposes in its metadata.

| Chapter | What is in it |
|---|---|
| [Project](00-progetto.md) | Name, first version, archived items, boundary, open work |
| [Product](01-prodotto.md) | The two objects of the app, one record's run, what "any system" means in this version |
| [Architecture](02-architettura.md) | Processes, network, volumes, startup, boundary with the Espo database |
| [Data model](03-modello-dati.md) | SQLite: tables, slugs, deletions, what survives |
| [Into Espo](04-ingresso-in-espo.md) | Key, hash, lookup, POST, PUT, 409 conflict |
| [Out of Espo](05-uscita-da-espo.md) | `modifiedAt` cursor, sink, send, inbox |
| [Four channels](06-quattro-canali.md) | Operating contract of webhook, database, CSV and HTTP |
| [Espo catalog](07-catalogo-espo.md) | How an entity and a field become selectable, links included |
| [API](08-api.md) | Every HTTP path, with body and response |
| [Interface](09-interfaccia.md) | Menu, screens, four steps |
| [Trial snapshot](10-stato-della-prova.md) | Configuration and records on the local volume on 17/10/2026 |
| [Running it](11-esercizio.md) | Start, stop, trial database, MkDocs manual |
| [GitHub token](12-token-github.md) | Token for issues, when it is needed |
| [Meridia demo](13-demo-meridia.md) | A company demo: processes and data of Gruppo Meridia |
| [Brand](14-marchio.md) | Mark, lockup and files in `assets/logo` |
| [Adoption](15-adozione.md) | Functions that would make a company choose Nesso |

How to start the stack is in the repository root README. The short card, also in the root, is `motore.md`.
