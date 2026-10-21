# The four channels

The kind is chosen at creation and, if you update through the API by passing the id, it can change because `save_connection` rewrites `kind` and `config_json`. The token stays. The page has the connection form.

The direction allowed on the integration: `http` only `out`, `sftp` and `ftps` either way, the others only `in`. Saving a mismatched pair answers "the connection and the direction do not match".

## Webhook

Meant for a system that calls as soon as a datum is born: a form, an ERP with an event.

The signing secret is optional. Without it, only the token in the address remains. It builds:

```
{PUBLIC_BASE_URL}/hook/{id}/{token}
```

With the compose values, the base is `http://localhost:8091`. The address appears on the connection card. Whoever has it can insert data. The signature, when the secret is set, is the extra check.

`POST` accepts:

| Body | Reading |
|---|---|
| `{...}` | one record |
| `[ {...}, {...} ]` | one record per item |
| `{ "records": [ {...} ] }` | one record per item of `records` |
| anything else | HTTP 400 "the body must be an object or a list" |

The token is compared in constant time (`hmac.compare_digest`). Missing connection, different kind, different token: HTTP 401 "connection not valid".

If `signSecret` is set, the raw body must arrive with the `X-Nesso-Firma` header: HMAC-SHA256 in hexadecimal, also with the `sha256=` prefix. A missing or different signature: HTTP 401 "invalid signature", and no run starts. Without a secret the webhook from before keeps coming in. The secret does not appear in the download.

If no inbound integration points at this id: HTTP 400 "no integration uses this connection". The body is not kept.

For every active inbound integration, for every record, it calls inbound. A row that fails is written in `scarto` and the batch continues. An item that is not an object is a reject. At the end of the batch `mark_run` reports created, updated, unchanged and rejected. A paused integration does not receive the webhook.

"Run now" does not simulate a payload. It answers `{"waiting": true, "url": "..."}` and writes the same status `ok` with "waiting for the external system to call the address". The page shows "Waiting for calls on the webhook address."

In the trial the connection is `sito-web`, the integration is `richieste-del-sito-verso-lead`. One POST created the lead `WEB-77`.

## Database

Meant for an ERP or a jobs view, read by the engine.

Fields required on save: `host`, `database`, `user`, `query`. A missing `engine` is `mysql`. A missing `port` becomes 3306 for MySQL and MariaDB, 5432 for Postgres, 1433 for SQL Server, 1521 for Oracle. `password` can be empty. On update, empty password and a previous password present: the previous one is kept. `tls` off does not change the previous MySQL connection. On, the connection asks for TLS. `tunnelHost`, if set, opens an SSH forward and the database is reached from there; the tunnel password does not enter the download. The engine does not write to the external database: the query stays a single SELECT.

The query is refused if:

- it is empty
- it is longer than 4000 characters
- it contains `;`
- it does not start with `SELECT` or `WITH`, ignoring case and leading spaces

The engine does not run the text as it is. It wraps it:

```sql
SELECT * FROM ( {query} ) AS sorgente LIMIT {n} OFFSET {offset}
```

On MySQL, MariaDB and Postgres the page is `LIMIT` and `OFFSET`. On SQL Server and Oracle it is `OFFSET … ROWS FETCH NEXT … ROWS ONLY`. `n` is 5 during the save and in the dry run. In a run the pages are of 200 and it continues until the page is short: there is no cap of 500. If the integration has a change column, the SELECT is ordered by that column and by the identity column, and the next run starts again from the last value read, even if it is equal, using the identity as the tie-break. Column names are only letters, digits and underscore. The save fails if the host does not answer, if the user has no permission, or if the query is invalid. If it answers, the API returns `columns` and saves them on the connection, so the mapping step offers them. The connection uses `connect_timeout` 8 seconds and `read_timeout` 30. Dictionary cursor. Every non-null value becomes a string.

There is no SQL parser beyond the initial regex. A SELECT that contains the word insert inside a string passes. A second statement does not, because the semicolon is forbidden. `INSERT`, `UPDATE`, `DELETE` at the start of the text do not.

Run: reads all the pages, ingest per row, continues after the error. Detail:

```text
{n} righe dal database, {c} create, {u} aggiornate, {chiuse} chiuse, {i} invariate, {f} scartate
```

The status is `errore` only when there are rejects and there is no row created, updated or unchanged. Every reject stays in the `scarto` table.

Host usable from inside the container for the trial: `db`. Database `gestionale`, user `espocrm`, password `locale-db`. The saved query is:

```sql
SELECT codice, ragione_sociale, email, piva FROM clienti
```

The running chapter has the `CREATE TABLE` and the three rows. That database is not in compose: it lives in the MariaDB volume.

The page, under the card, shows the query. It does not show host, user, password.

## CSV file

Meant for a night drop: someone leaves a file, the engine consumes it.

At creation it creates:

```
{SCAMBIO_DIR}/{id}/
{SCAMBIO_DIR}/{id}/elaborati/
```

With compose, on the host it is `scambio/{id}/`. The config is empty. The card says to drop the `.csv` and `.xlsx` files in `scambio/{id}`.

Read:

- the `*.csv` and `*.xlsx` files directly in that folder, not in subfolders
- order by name
- encoding `utf-8-sig`, so a BOM at the start does not become part of the first column name
- `csv.DictReader`: the first row is the header
- `None` keys (extra columns without a name) are removed
- an empty cell stays an empty string. If the field owner is the source, that cell clears the field in Espo. If the owner is Espo, the conflict goes to the queue and the field is not touched

The separator is the comma, or the semicolon if the first row has more semicolons. A row that fails goes to `scarto` and the others continue. At the end of the run every file that was read is renamed to `elaborati/{YYYYMMDDHHMMSS}-{name}`, even if some row was rejected. If a required column is missing, including the identity column, that file is not moved and the reject is a single one: "manca la colonna …".

In the trial: `scambio/file-notturno/elaborati/20261017105401-contatti.csv`, one row, contact Sara Verdi, external id `CNT-20`, integration `file-notturno-verso-contatti`.

A CSV without a required column, including the identity one, produces a single reject "manca la colonna …" and is not moved. The next run tries again. Files already in `elaborati/` are not read again. If the integration has an "expected by" time and at that time there is no successful run today, home is red and the journal records the absence once a day.

An `.xlsx` uses the first row as the header, like the CSV. The columns map the same way. If a required column is missing the file does not move.

## SFTP and FTPS

The kind is `sftp` or `ftps`. Fields: `host`, `user`, `path`. A missing port is 22 or 21. An empty password, on update, keeps the previous one and does not appear in the download.

Inbound, it reads the `.csv` and `.xlsx` files in that folder, not the ones already under `elaborati/`. After the run the remote file is named `elaborati/{stamp}-{name}`, even if some row was rejected. If a required column is missing, that file stays where it is. Outbound, if there are new records, Nesso drops a CSV `nesso-{stamp}.csv` and the cursor advances only after the drop.

## PDF on the customer

The connection is `pdf`. The `*.pdf` files are dropped in `scambio/{id}`, not in subfolders. If the name contains a company's key, as a whole word, the file becomes a Document linked to that Account, in the document folder and the team written on the connection, and it moves to `elaborati/`. Between two keys the longer one wins: `C001` does not take `fattura-C0012.pdf`. A name without a key stays in the folder. This is not the general document channel: it is this gesture.

## Outbound HTTP

Meant for a portal that receives the changes of Espo.

The only parameter is `url`. Empty is allowed. If it is set it must start with `http://` or `https://`. At save time it is not checked that the host answers.

Empty URL: the run sends to the engine inbox, described in the outbound chapter. The card shows the public `inboxUrl` (`localhost`), while the internal send uses `127.0.0.1` and the process port. They are the same server. In the detail of the last run the internal address is visible.

A set URL: one POST per record, and the inbox of this connection receives nothing, unless the URL is exactly that of the inbox.

Authentication is none, Bearer, user and password, or a header. With OAuth the engine asks for the token at the given address, with the client credentials, and renews it when it has expired. Then the JSON goes out as before, with `Authorization: Bearer`. The client secret and the token do not enter the journal or the download. Without OAuth the send stays the one from before.

"Run now" with zero new records answers `sent: 0` and status `ok`. It is not an error.

## Scheduler and channels

Every 30 seconds, integrations with `schedule_minutes > 0` and a set `connection_id` are candidates. If `last_run` is more recent than `schedule_minutes` minutes, they are skipped. The format of `last_run` is `YYYY-MM-DD HH:MM:SS`. An unreadable value fails the scheduler cycle, which prints and tries again after 30 seconds. It does not kill the server.

A webhook scheduled every 15 minutes does not receive data by itself: the run does the same thing as "Run now", that is it marks "waiting". The cadence makes sense for database, CSV, Excel, SFTP, FTPS and HTTP.

An exception inside `run_pipeline` is printed and the integration is a candidate again on the next cycle, because `mark_run` has anyway written `last_run` in the error branch before re-raising. There is no backoff beyond the configured interval.

The lock is global. Two integrations due in the same check start one after the other, not together. If the first holds the lock, the second receives the error "a run is already in progress", which is written in `last_status` and shifts the next attempt by a whole interval.
