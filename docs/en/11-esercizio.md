# Running it

## Start

From the repository root:

```text
docker compose up -d --build
```

The first time it downloads `mariadb:11.4`, `espocrm/espocrm:10.0` and builds the engine (`python:3.12-slim`, pip of `pymysql`). Espo installs the CRM in the volume. The engine waits for the healthcheck.

| Check | Expected |
|---|---|
| http://localhost:8088 | Espo login page, Italian |
| `admin` / `locale-admin` | signs in |
| http://localhost:8091 | first entry, then the Home page |
| http://localhost:8091/api/health | `espo` reachable, `fields` ready |

`docker compose ps` must show `nessocrm-db`, `nessocrm-espo`, `nessocrm-daemon`, `nessocrm-motore`.

Stop without losing data: `docker compose stop`. Start again: `docker compose start`. Delete the volumes, and with them Espo, the state and `gestionale`: `docker compose down -v`. The `scambio` folder on the host stays.

A change to `motore/app.py` or `motore/index.html` requires `docker compose up -d --build motore`. The build copies the files into the image. Mounting the code folder is not provided.

## Recreate the trial database

Needed only if the MariaDB volume is new. `gestionale` is not in the compose init script. From the PC, with the container up:

```text
docker exec nessocrm-db mariadb -uroot -plocale-root -e "CREATE DATABASE IF NOT EXISTS gestionale; GRANT ALL ON gestionale.* TO 'espocrm'@'%'; FLUSH PRIVILEGES; CREATE TABLE IF NOT EXISTS gestionale.clienti (codice varchar(40) NOT NULL, ragione_sociale varchar(200), email varchar(200), piva varchar(20), PRIMARY KEY (codice)); INSERT IGNORE INTO gestionale.clienti VALUES ('CLI-100','Officina del Porto','porto@example.test','10000000001'), ('CLI-101','Studio Nord','nord@example.test','10000000002'), ('CLI-102','Panificio Rosa','rosa@example.test','10000000003');"
```

Then, on the page, a database connection with host `db`, port 3306, database `gestionale`, user `espocrm`, password `locale-db`, and the SELECT on the four columns. The save that lists the columns has already run the query.

## Try the four channels by hand

Webhook. Copy the address from the card. A POST:

```text
curl -H "Content-Type: application/json" -d "{\"id\":\"WEB-200\",\"nome\":\"Prova\",\"cognome\":\"Canale\",\"email\":\"prova.canale@example.test\"}" http://localhost:8091/hook/{id}/{token}
```

The response `creato` and, in Espo, a new lead. The same command a second time: `invariato`.

Database. On the integration attached to that connection, "Run now". The detail reports rows, created, updated, rejected. The second click, with the data still, brings created and updated to zero.

CSV. Put a file in `scambio/{id}/`, header equal to the mapping, identity column filled:

```text
codice,nome,cognome,email
CNT-30,Nino,Re,nino.re@example.test
```

"Run now". The file must appear in `elaborati/` with the date-time prefix. The contact is in Espo.

Outbound. Integration on an HTTP connection, "Run now". With an empty URL, "Latest rows" shows `inviato` and `ricevuto` for every record whose `modifiedAt` is new. A second click with the CRM still sends zero records.

## Where a failure is looked at

| Symptom | Where |
|---|---|
| The page does not list entities | Espo is not up yet, or `/api/catalog` is 400. Health says whether the admin answers |
| Saving a database connection fails | text in the form: host, permission, or "only one SELECT is allowed" |
| Run now on the database marks rejected | `last_detail` has the first reason. The known case is the account name already used by another key |
| A CSV row does not enter | if the column exists, the file is still in `elaborati/` and the row is in Activity. If a required column is missing, the file stays in the folder and there is a single reject |
| Run now says a run is already in progress | the same integration is already running, from "Run now" or from the scheduler |
| Outbound always resends the same records | the cursor does not advance. If `modifiedAt` is missing the cursor follows the id already delivered; if it still resends, the previous POST did not succeed |
| Outbound does not resend a record that is already in Espo | its `modifiedAt` is less than or equal to the cursor in `cursor_state` |
| A field is not in the menu | type not writable, read only, entity without a tab, or the 120-second cache just after a creation |
| The build does not change the page | the image was not rebuilt |

Engine log: `docker logs nessocrm-motore`. Every request is a line `[motore]`. The scheduler, on error, prints `[motore] pianificazione`.

## Ports already taken

The choice of 8088 and 8091 is of this machine. If one of the two is taken, Compose does not publish the service. The port is not changed in the CRM already installed without aligning `ESPOCRM_SITE_URL` and `ESPO_PUBLIC_URL`: the addresses inside the app are those of the variables, not those guessed by the browser.

## What not to do on this PC while thinking of production

The containers are named `nessocrm-*`. The dumps in `01-espocrm-database` and `03-dwh-database` are not arguments of any service. Importing them into `nessocrm-db` would mix the real data with the trial. The manual does not describe that command.

## Manual

The docs site is built from this root.

```text
py -3 -m pip install -r requirements-docs.txt
py -3 -m mkdocs serve
```

It opens at http://127.0.0.1:8000. The check, without starting the server, is `py -3 -m mkdocs build --strict`. The configuration is `mkdocs.yml`. The Italian chapters are in `docs/` and the same chapters in English are in `docs/en/`, with the same file name. The site menu is the `nav` key of `mkdocs.yml`. The language switch is in the site header.
