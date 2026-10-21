# Out of Espo

Outbound is `pull`. The HTTP connection uses it, and so does `POST /api/pull/{id}`, which stops at the engine and calls nobody outside.

## Who can leave

The pipeline must exist and have direction `out`. Otherwise "the pipeline is not outbound", or 404.

The mapping is read the other way from inbound: `from` is the Espo field, `to` is the name in the JSON that leaves. For `lead-verso-portale`:

| Espo field | Name sent |
|---|---|
| `firstName` | `nome` |
| `lastName` | `cognome` |
| `emailAddress` | `email` |
| `cExternalKey` | `chiave` |

A `None` value in the Espo record does not enter the JSON. An empty string, if Espo returns it, does.

## Read

The cursor starts from `1970-01-01 00:00:00` if the integration does not yet have a row in `cursor_state`. The saved value is `modifiedAt`, then a tab, then the Espo id. An old cursor, without a tab, is still read: on the next run the records with that instant can leave once more, then the new format tells them apart.

The read is in pages of 50. First it completes the records with the same `modifiedAt` as the cursor and a greater id. Then it takes the later `modifiedAt` values. If a page is full of one instant, it continues by id, so nobody is left out. A run stops at 1000 records. The select always includes `id` and `modifiedAt`.

`/api/pull` writes the sink and then the cursor, because the delivery is the read. The HTTP send does not use this path.

Cursors present on 17/10/2026:

| Integration | Cursor |
|---|---|
| `uscita-lead` | 2026-10-17 10:14:22 |
| `contatti-da-espo` | 2026-10-17 10:14:23 |
| `lead-verso-portale` | 2026-10-17 10:53:11 |

The select always asks for `id` and `modifiedAt`, even if the mapping does not map them. If a record has no `modifiedAt`, the cursor still advances on the id already delivered and the run detail says the date is missing. That id does not leave again on the next run.

## Send

Only kind `http` sends. The address is `config.url` if it is set. If it is empty, the address is the internal inbox:

```
http://127.0.0.1:8091/inbox/{connection id}/{token}
```

It is a JSON POST, header `Content-Type: application/json`, timeout 20 seconds. On the connection you can add a Bearer, user and password, a header, or OAuth client credentials. The OAuth token is renewed when it has expired, and then the JSON goes out as before. The token in the address stays only for the internal inbox.

For each record, after an HTTP under 300:

- a `delivery` row with status `inviato`, detail equal to the URL, `pipeline_id` set
- the `sent` counter grows

An HTTP of 300 or more, or a network error, stops the loop. Records already sent stay sent and the cursor reaches the last of those. The record that failed, and the ones after it, leave on the next run. The reject is in `scarto` and in `delivery` with status `errore`.

`mark_run` writes "N records sent to {url}".

In the trial, three leads left toward the inbox. The journal has, for each, one `inviato` row and one `ricevuto` row. The second is written by the inbox, not by the send run. `pipeline_id` of the received row is null: the inbox does not know which integration sent it.

Body of Marta Bianchi, both sent and received:

```json
{
  "nome": "Marta",
  "cognome": "Bianchi",
  "email": "marta.bianchi@example.test",
  "chiave": "modulo-web:WEB-1001"
}
```

The key is the one the lead entered with, not a new id calculated on the way out. Outbound does not invent keys. It copies the mapped fields.

## Without a destination

"Run now" on an outbound integration without a connection still calls `pull`, saves sink and cursor, and the detail is "read N records, no destination". It does not create `delivery`. That is the case of `uscita-lead` and of `contatti-da-espo`.

`contatti-da-espo` maps the Account name onto the external name `bo`. In the sink there is one row: `{"bo": "Officina Del Porto"}`, Espo id `6ad34a7f1b75d9805`. `last_status` of that integration is empty: the read went through `/api/pull/`, which does not update the last result. The page, instead, uses `/api/pipelines/{id}/run`.

## Inbox

`POST /inbox/{id}/{token}` with a connection of kind `http` and a matching token:

- HTTP 200 `{"stored": true}`
- a `delivery` row, status `ricevuto`, detail "external system"

Wrong token or id, or a kind other than `http`: HTTP 401 "inbox not valid". The body can be any JSON object. Without `deliverTo` the inbox does not send it to Espo. With `deliverTo` it delivers it once to that integration, if it is enabled; if it is paused, the row stays `ricevuto`. It is an observation point to try outbound without an external server, and an address an external system can call if it is given the token.

## What outbound does not do

It does not delete in Espo. It does not send deletions. It does not follow relations. A run reads up to 1000 records, in pages of 50. The POST can carry Bearer, basic, a header or OAuth. A link leaves as an Espo id. If the rule says `as: chiave`, the external key of the linked record leaves; if it is missing, the row is rejected and the id is not sent in its place. A failed send does not move the cursor past the last POST that succeeded.
