# Into Espo

Every inbound channel ends in the same function, `ingest`. Webhook, SELECT and CSV differ only in how they obtain the list of objects. From there the record is a dictionary of strings.

## Conditions to enter

The function refuses, without writing to Espo, if:

- the integration id does not exist
- the direction is not `in`
- the body is missing the `external_id_field` column, or it is empty or only spaces
- the key template, after substitution, still contains a brace or is empty

The template is the saved text, for example `richieste-del-sito-verso-lead:{id}`. Every key of the body replaces `{name}`. Giulia Costa's webhook body is:

```json
{"id": "WEB-77", "nome": "Giulia", "cognome": "Costa", "email": "giulia.costa@example.test"}
```

`{id}` becomes `WEB-77`. The external key is `richieste-del-sito-verso-lead:WEB-77`.

If the integration asks for the column `codice` and the CSV has `codice` empty, the error is "missing field codice". If the template names a key the body does not have, the brace stays and the error is "external key incomplete".

One column stays the normal case: the queue key is the cell, and the template stays `{id}:{column}`. If other columns are named, for example company code and customer code, the queue key is the concatenation with `|`, `MI|C001`. Two rows with the same customer code and different companies are two records. The same pair sent again updates the one already written. A value that contains `|` is refused, because the separator would no longer be unique. On the page, next to the field, up to three keys calculated on the real rows are shown.

## Mapping

Each rule reads `transform`.

| Value | Result |
|---|---|
| missing, or `copy` | `str` of the value. `None` is skipped |
| `const:Web Site` | the string after the colon, even if `from` is empty |
| `split_first` | first word of `from` |
| `split_last` | everything after the first space. A single word produces `None` and the field is not written |
| anything else | error "unknown transform" |

If the field owner is the source, a cell that is present and empty clears that field. If the owner is Espo and the incoming value differs from what is already written, the field is not touched and the conflict goes to the review queue. Then, if the key exists and the entity accepts the field, the engine adds `mapped[key_field] = key`, even if the mapping does not mention that field. A date is normalised from `18/10/2026`, `2026-10-18` or `18-10-2026`. A list value outside the options, or a VAT number already used by another key, rejects the row and names the field. That is why Giulia Costa has `cExternalKey` even though only first name, last name and email are mapped. If the entity is not customisable, the key does not enter the JSON: it stays in the `chiave` table.

Body sent to Espo for that lead:

```json
{
  "firstName": "Giulia",
  "lastName": "Costa",
  "emailAddress": "giulia.costa@example.test",
  "cExternalKey": "richieste-del-sito-verso-lead:WEB-77"
}
```

Numbers read from MariaDB become strings before they arrive here. An integer `100` leaves as `"100"`.

When the write starts, Nesso adds the Nesso origin field itself, with the date and time of the ERP. It does not come from a column. If after that write a person saves the record, the field becomes "last edit by" followed by their name. A save made by the user Nesso uses to talk to Espo does not count as a person's edit.

## Hash

```text
SHA-256( JSON of the mapped body, keys sorted, UTF-8, ensure_ascii false )
```

The mapped body counts, not the original body. Two different external bodies that produce the same mapped body are the same send. One more Espo field in the mapping changes the hash.

Espo is skipped only if the queue row already exists, the status is `synced` and the hash is identical. The response is:

```json
{
  "status": "invariato",
  "espoId": "6ad353977a2a687a1",
  "externalKey": "richieste-del-sito-verso-lead:WEB-77",
  "entity": "Lead"
}
```

`invariato` does not appear in the `created` / `updated` count of the database run. A later run that finds two unchanged rows and one rejected is marked `errore`, because created and updated are zero and failed is one. That is the current state of `clienti-gestionale-verso-account`: the first run had created Studio Nord and Panificio Rosa; a later run skipped those two by hash and rejected Officina del Porto again, and the detail became "0 created, 0 updated, 1 rejected".

## Lookup and write

1. If the queue already has an `espo_id` for that external id, `PUT /api/v1/{Entity}/{id}` with the mapped body. Action `aggiornato`.
2. Otherwise `GET` with `where equals` on the key field, `maxSize=1`, `select=id,{field}`.
3. Found: `PUT`. Not found: `POST`. Action `creato`.

A lookup that fails (HTTP other than 200) stops the record. It does not guess.

After a 200 or 201 the engine upserts the queue: it inserts or replaces payload, mapped body, hash, status `synced`, Espo id, detail `creato` or `aggiornato`, time.

## The 409

Espo answers 409 with a list of records when its duplicate check fires. The case seen is Account: the name "Officina del Porto" looks like "Officina Del Porto" already present.

The engine looks at the first item of the list.

- If that item has the same `cExternalKey` as the mapped body and has an `id`, it does `PUT` on that id and treats the record as updated.
- If the key is different or missing, it raises "Espo already has a similar record (Officina Del Porto) with another key".

In the second case the record does not enter and the queue does not change. The two masters stay separate: `anagrafica:CLI-42` is the Account created by hand through ingest, `clienti-gestionale-verso-account:CLI-100` does not exist in Espo.

There is no attempt to merge the two records, nor to write a link. The policy is the same for every entity.

## Responses

| status | When |
|---|---|
| `creato` | new POST, new Espo id |
| `aggiornato` | PUT on a key already known, or PUT after a 409 of the same key |
| `invariato` | hash already synced |

Marta Bianchi's phone is the example of `aggiornato`: same external id `WEB-1001`, same Espo id `6ad34a7e5b76fe198`, different hash, PUT.

## Errors per channel, after ingest

| Channel | One row fails |
|---|---|
| Database | counts `failed`, remembers the first message, continues with the next row. Run status `errore` only if no row is created or updated |
| CSV | the exception leaves, the run is `errore`, files not yet moved stay in the folder. Rows already written in this run stay in the queue |
| Webhook | the exception leaves toward the caller with HTTP 400. Later integrations of that same connection do not start. `mark_run` of that integration is not executed if the error is born inside its loop |
| `POST /api/ingest/{id}` | HTTP 400 with the text. No other row, because the body is a single object |

The database run does not write a queue row for the rejected one, so "Latest rows" does not list it. It is seen in `last_detail` on the integration card.
