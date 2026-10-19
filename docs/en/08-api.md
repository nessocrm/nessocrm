# API

Base: `http://localhost:8091`. Bodies are JSON. Rule errors are `{"error": "text"}`. If the request sends `X-Nesso-Lang: en`, the error text comes out in English when the sentence is in the catalog; otherwise it stays in Italian. The journal still saves the Italian sentence.

| Situation | HTTP |
|---|---|
| validation, Espo refused, query not allowed | 400 |
| wrong hook or inbox token | 401 |
| missing integration or connection id where the code uses `KeyError` | 404 |
| unknown path | 404 |
| success | 200 |

There is no authentication on the configuration APIs. Whoever reaches port 8091 creates connections and starts runs. The only secret is the token inside the hook and inbox URLs.

## GET /api/frasi

English catalog of the page: `lingue` is `["it", "en"]` and `en` is the map from the Italian sentence to the English one. Italian is not a second list: it is the key.

## GET /api/health

```json
{"ok": true, "espo": "raggiungibile", "fields": "pronti", "detail": "Lead.externalKey presente, Account.externalKey presente, Account.partitaIva presente"}
```

`espo` goes from `in attesa` to `attendo Espo`, then `raggiungibile` or `non raggiungibile`. `fields` is `non creati`, `pronti` or `errore`. The server answers even while Espo is not up yet.

## GET /api/catalog

```json
{
  "espoPublicUrl": "http://localhost:8088",
  "entities": [
    {
      "name": "Lead",
      "label": "Lead",
      "keyField": "cExternalKey",
      "fields": [
        {"name": "firstName", "label": "Nominativo", "type": "varchar"}
      ]
    }
  ]
}
```

The real list depends on the installation. The cache lasts 120 seconds. HTTP 400 if the Espo metadata does not answer.

## GET /api/state

The page uses it on every refresh. It contains:

| Key | Content |
|---|---|
| `state` | the same `espo`, `fields`, `detail` as health |
| `espoPublicUrl` | public link |
| `publicBase` | base of the hook URLs |
| `pipelines` | all integrations, `mapping` already a list, ordered by direction and id |
| `connections` | connections without passwords. Webhook has `url`. HTTP has `inboxUrl`. CSV does not have the absolute path here: the page rebuilds `scambio/{id}` |
| `queue` | latest 30 inbound rows, `updated_at` descending |
| `sink` | latest 20 records read outbound |
| `deliveries` | latest 20 deliveries, id descending |
| `morning` | accounts percent, tone and sentence. `percent` is null if there is no successful run today |
| `alerts` | sentences of a red balance and of an expected file not processed |

On every inbound integration from CSV, `balance` is the balance and `file_alert` is 1 if the expected file has not yet been processed today. `expectAt` is saved with the integration, next to `scheduleAt`.

## POST /api/connections

Creates. Without `id`, the slug is born from the name.

Webhook:

```json
{"name": "Sito web", "kind": "webhook", "config": {}}
```

```json
{"id": "sito-web", "name": "Sito web", "kind": "webhook", "url": "http://localhost:8091/hook/sito-web/{token}"}
```

Database:

```json
{
  "name": "Gestionale clienti",
  "kind": "database",
  "config": {
    "host": "db",
    "port": 3306,
    "database": "gestionale",
    "user": "espocrm",
    "password": "locale-db",
    "query": "SELECT codice, ragione_sociale, email, piva FROM clienti"
  }
}
```

```json
{"id": "gestionale-clienti", "name": "Gestionale clienti", "kind": "database", "columns": ["codice", "ragione_sociale", "email", "piva"]}
```

`columns` is meaningless if the `LIMIT 5` trial returns zero rows: the list is empty and the connection is saved anyway.

CSV:

```json
{"name": "File notturno", "kind": "csv"}
```

```json
{"id": "file-notturno", "name": "File notturno", "kind": "csv", "folder": "file-notturno"}
```

HTTP:

```json
{"name": "Portale esterno", "kind": "http", "config": {"url": ""}}
```

```json
{"id": "portale-esterno", "name": "Portale esterno", "kind": "http", "inboxUrl": "http://localhost:8091/inbox/portale-esterno/{token}"}
```

Update: the same body plus `"id"` of an existing row. The token does not change. Kind and config are replaced.

Typical errors: "missing connection name", "connection type not recognised", "missing host", "only one SELECT is allowed", "the destination address must be http or https", plus the MariaDB connection error if the trial fails.

## DELETE /api/connections/{id}

```json
{"deleted": "sito-web"}
```

Integrations that cited it stay, with an empty connection. 404 if the delete touches no rows.

## POST /api/sheets

Creates an Espo entity. The body is `singular` and `plural`. The response has `name`, the technical name (`C` plus the singular). The external key field is born too.

## POST /api/sheets/{nome}/fields

Adds a field to an entity that Espo lets you customise. The body has `label`, `type` and, if needed, `options` and `required`.

`type` is one of `varchar`, `text`, `int`, `float`, `date`, `datetime`, `bool`, `enum`, `currency`, `email`, `phone`, `url`. For `enum`, `options` is a list or a text with one value per line. `required` true marks the field required.

The technical name is derived from the label. On standard entities Espo prefixes `c`. The field is appended to the detail and the list. If the entity is not customisable, the response is 400.

## POST /api/pipelines

```json
{
  "name": "Richieste del sito verso Lead",
  "connectionId": "sito-web",
  "direction": "in",
  "espoEntity": "Lead",
  "externalIdField": "id",
  "scheduleMinutes": 0,
  "mapping": [
    {"from": "nome", "to": "firstName"},
    {"from": "cognome", "to": "lastName"},
    {"from": "email", "to": "emailAddress"}
  ]
}
```

```json
{"id": "richieste-del-sito-verso-lead", "name": "Richieste del sito verso Lead", "direction": "in", "espoEntity": "Lead"}
```

Outbound, `from` is the Espo field:

```json
{
  "name": "Lead verso portale",
  "connectionId": "portale-esterno",
  "direction": "out",
  "espoEntity": "Lead",
  "externalIdField": "id",
  "scheduleMinutes": 0,
  "mapping": [
    {"from": "firstName", "to": "nome"},
    {"from": "cExternalKey", "to": "chiave"}
  ]
}
```

An empty `connectionId` is allowed by the API. The page does not allow it. Passing `id` of an existing integration updates it and does not delete the queue or the cursor.

Inbound, before saving, the engine calls the creation of `externalKey` on the entity. If Espo refuses the field, the save fails.

Typical errors: "missing integration name", "choose the Espo entity", "name the field that identifies the record in the external system", "map at least one field", "Espo entity not available", "unrecognised Espo fields: …", "the cadence can be manual, 5, 15 or 60 minutes", "the connection and the direction do not match".

## POST /api/pipelines/{id}/run

Optional body `{"withDependencies": true}`. If it is true, the integration named in `dependsOn` starts first, and its own, in a chain. The response depends on the channel.

| Channel | Success body |
|---|---|
| none, outbound | the pull result: `exported`, `cursor`, `records` |
| none, inbound | 400 "connect an external system before running" |
| webhook | `{"waiting": true, "url": "..."}` |
| database | `rows`, `created`, `updated`, `unchanged`, `closed`, `failed`, `status` |
| csv | `rows`, `created`, `updated`, `unchanged`, `closed`, `failed`, `status` |
| http | `{"sent": 3, "url": "...", "failed": false}` |

409 of contention on the lock: 400 "a run is already in progress". Even in that case, if the exception leaves `run_pipeline`, `mark_run` marks an error. The `finally` releases the lock.

## POST /api/pipelines/{id}/dry

Reads at most five rows and returns `rows`, each with `mapped` or `status: scartato`. It does not write to Espo. A missing lookup with the "create" policy appears as `nuovo:valore` and the record is not born. The webhook answers that it has no rows to read.

## POST /api/pipelines/{id}/anteprima

Counts the whole run without writing: created, updated, closed, rejected, and `pericolose` with today's value and the incoming one. It does not move the CSVs and does not advance the cursor.

## POST /api/pipelines/{id}/lettura

`{"enabled": true, "hours": 48}` turns read mode on. When it expires it does not switch to writing by itself: you leave it with `{"enabled": false}`.

## POST /api/pipelines/{id}/annulla

Restores the fields written by the last run, only if nobody changed them afterwards. Response `restored` and `kept`.

## POST /api/pipelines/{id}/chiusure

Confirms the first close of records that disappeared from the source and closes them. Without a status on the entity it answers 400.

## POST /api/scritture

`{"enabled": false}` stops every write toward Espo. The preview and the dry run stay.

## POST /api/connections/{id}/campione

The first three rows of the CSV or of the database, for the mapping.

## POST /api/proponi

Body `columns`, `fields` (name and label of the entity fields) and `samples`. It does not write the integration. Each row has `from`, `to`, `known`, `role` (`field` or `identity`), `sample` and `reading`. The language is that of the header. `identity` is the column to use as the external key, not a field. A recognised date in `reading` is `YYYY-MM-DD`.

## POST /api/ricette/anagrafiche

Body `fields` of the Account entity. Answers with `id` `anagrafiche`, `entity` `Account`, `externalIdField` `codice`, the mapping rows and `noteKey`. It does not create the integration: the page applies the rows and the person can still change them.

## POST /api/watch/{id}

`{"keep": "espo"}` leaves the current value. `{"keep": "sorgente"}` writes the incoming one.

## POST /api/pipelines/{id}/enabled

Body `{"enabled": false}` pauses. `true` resumes. The pause applies to the scheduler and to the webhook. "Run now" starts anyway.

## GET /api/export and POST /api/import

The download is the list of connections, without passwords, tokens and header values, and the list of integrations with the map already filled. The upload restores that file. Empty passwords, if the connection already exists, stay the previous ones. Importing an integration writes the map as it is, without recreating the fields in Espo.

## DELETE /api/pipelines/{id}

```json
{"deleted": "lead-verso-portale"}
```

Deletes queue, sink, cursor, rejects and the run journal of that id. It does not delete the records in Espo and it does not delete `delivery`.

## POST /hook/{id}/{token}

Body, one record:

```json
{"id": "WEB-77", "nome": "Giulia", "cognome": "Costa", "email": "giulia.costa@example.test"}
```

```json
{
  "accepted": 1,
  "results": [
    {
      "status": "creato",
      "espoId": "6ad353977a2a687a1",
      "externalKey": "richieste-del-sito-verso-lead:WEB-77",
      "entity": "Lead"
    }
  ]
}
```

`accepted` is the number of ingests executed. With two integrations on the same webhook and one record, it is 2. With one integration and a list of three, it is 3.

## POST /inbox/{id}/{token}

```json
{"nome": "Marta", "cognome": "Bianchi"}
```

```json
{"stored": true}
```

It does not forward to Espo.

## POST /api/ingest/{id}

A single object, the pipeline must be inbound. Same response as one item of `results` above. It is the path by which Marta Bianchi (`modulo-web`), Officina Del Porto (`anagrafica-clienti`) and Luca Neri (`contatti-del-gestionale`) entered, which have no connection.

## POST /api/pull/{id}

Same response as pull, without sending and without updating `last_run`. It is the path of `uscita-lead` and of `contatti-da-espo`.

## DELETE and POST on the wrong paths

A `GET` on `/api/pipelines` is 404. There is no separate list: the list is inside `/api/state`. There is no `PATCH`.
