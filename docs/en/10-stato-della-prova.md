# Trial snapshot

This page is the photograph of the first seed, read on the afternoon of 17/10/2026. It is not the demo that runs now. The current demo is Gruppo Meridia, in the chapter of that name.

Photograph read from `motore.sqlite` and from the `gestionale` database. They are invented data on an empty Espo, plus a lead inserted with a call to the seed integration. No row comes from the production dump.

The Espo ids are those of this installation. A recreated volume will have others.

## Connections

| Id | Name | Type | Useful configuration |
|---|---|---|---|
| `file-notturno` | File notturno | csv | folder `scambio/file-notturno/` |
| `gestionale-clienti` | Gestionale clienti | database | host `db`, port 3306, database `gestionale`, user `espocrm`, query `SELECT codice, ragione_sociale, email, piva FROM clienti` |
| `portale-esterno` | Portale esterno | http | empty URL, so the local inbox |
| `sito-web` | Sito web | webhook | no parameter; the address is on the card in the page |

The tokens are not reported here. They are in the URLs on the page.

## Integrations

| Id | Direction | Entity | Connection | Cadence | Identity | Mapping |
|---|---|---|---|---|---|---|
| `anagrafica-clienti` | in | Account | none | manual | `codice` → key `anagrafica:{codice}` | ragioneSociale→name, piva→cPartitaIva, email→emailAddress, constant description |
| `clienti-gestionale-verso-account` | in | Account | gestionale-clienti | 15 min | `codice` | ragione_sociale→name, email→emailAddress, piva→cPartitaIva |
| `contatti-da-espo` | out | Account | none | manual | — | name→bo |
| `contatti-del-gestionale` | in | Contact | none | manual | `codice` | nome→firstName, cognome→lastName, email→emailAddress |
| `file-notturno-verso-contatti` | in | Contact | file-notturno | manual | `codice` | nome, cognome, email as above |
| `lead-verso-portale` | out | Lead | portale-esterno | manual | — | firstName→nome, lastName→cognome, emailAddress→email, cExternalKey→chiave |
| `modulo-web` | in | Lead | none | manual | `id` → key `modulo-web:{id}` | nome, cognome, email, phone, source constant `Web Site`, constant description |
| `richieste-del-sito-verso-lead` | in | Lead | sito-web | manual | `id` | nome, cognome, email |
| `uscita-lead` | out | Lead | none | manual | — | id, cExternalKey, firstName, lastName, emailAddress, source, modifiedAt |

`clienti-gestionale-verso-account` has `last_status` error and detail "3 righe dal database, 0 create, 0 aggiornate, 1 scartate. Espo ha già un record simile (Officina Del Porto) con un'altra chiave". It is a run after the first, which had created two accounts. The two creations became `invariato` and do not enter the counters, so the run with a single reject is an error. The two accounts are in Espo.

`file-notturno-verso-contatti`: ok, "1 righe dai file CSV".

`richieste-del-sito-verso-lead`: ok, "1 record ricevuti via webhook".

`lead-verso-portale`: ok, three records sent to the inbox on `127.0.0.1`.

The others have an empty `last_status`. `uscita-lead` and `contatti-da-espo` do have a cursor: they were read with `/api/pull`, which does not fill the last result.

## Inbound queue

| Integration | External id | Queue result | Espo id | Key |
|---|---|---|---|---|
| modulo-web | WEB-1001 | updated | 6ad34a7e5b76fe198 | modulo-web:WEB-1001 |
| anagrafica-clienti | CLI-42 | created | 6ad34a7f1b75d9805 | anagrafica:CLI-42 |
| contatti-del-gestionale | CNT-7 | created | 6ad3506c454f0810b | contatti-del-gestionale:CNT-7 |
| modulo-web | 1 | created | 6ad3526c86e9ea0d2 | modulo-web:1 |
| richieste-del-sito-verso-lead | WEB-77 | created | 6ad353977a2a687a1 | richieste-del-sito-verso-lead:WEB-77 |
| clienti-gestionale-verso-account | CLI-101 | created | 6ad353c4a4f2c162d | clienti-gestionale-verso-account:CLI-101 |
| clienti-gestionale-verso-account | CLI-102 | created | 6ad353c524876194f | clienti-gestionale-verso-account:CLI-102 |
| file-notturno-verso-contatti | CNT-20 | created | 6ad353c8f0c326d5f | file-notturno-verso-contatti:CNT-20 |

`CLI-100` is not in the queue. It is the reject.

Useful content of the records, without repeating personal data beyond the trial names:

| Record | Data sent to Espo |
|---|---|
| Marta Bianchi | first name Marta, last name Bianchi, email `marta.bianchi@example.test`, phone `+393339009009`, source Web Site, description "Creato dal motore locale" |
| Officina Del Porto | name, email `contatti@officina-porto.example.test`, VAT `12345678901` |
| Luca Neri | first name Luca, last name Neri, email `luca.neri@example.test` |
| Lead external id 1 on modulo-web | entered from the same integration as Marta, Lead entity |
| Giulia Costa | first name Giulia, last name Costa, email `giulia.costa@example.test` |
| Studio Nord | email `nord@example.test`, VAT `10000000002` |
| Panificio Rosa | email `rosa@example.test`, VAT `10000000003` |
| Sara Verdi | first name Sara, last name Verdi, email `sara.verdi@example.test` |

Sara's file is `scambio/file-notturno/elaborati/20261017105401-contatti.csv`.

## Trial table on the ERP

```text
CLI-100  Officina del Porto  porto@example.test   10000000001
CLI-101  Studio Nord         nord@example.test    10000000002
CLI-102  Panificio Rosa      rosa@example.test    10000000003
```

## Outbound

Sink:

| Integration | Espo id | Payload |
|---|---|---|
| uscita-lead | 6ad34a7e5b76fe198 | Marta, with espoId, external key, first name, last name, email |
| contatti-da-espo | 6ad34a7f1b75d9805 | `{"bo": "Officina Del Porto"}` |
| lead-verso-portale | three ids | Marta, the lead `modulo-web:1`, Giulia, each with first name, last name, email, key |

Delivery of `lead-verso-portale`: for each lead one `inviato` row and one `ricevuto` row on the `portale-esterno` inbox.

## How to read it again

From this folder, with the containers up:

```text
docker exec nessocrm-motore python -c "import sqlite3; c=sqlite3.connect('/data/motore.sqlite'); print(list(c.execute('SELECT id, name, direction, espo_entity, connection_id, last_status, last_detail FROM pipeline')))"
```

Espo, after login `admin` / `locale-admin`: Lead, Account, Contacts. The records above are the ones to look for.
