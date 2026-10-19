# Nesso

Nesso is the name of the project. It is the link between EspoCRM and an external system: the channel, the entity and the fields are configured, and the passage happens only with the Espo APIs.

Repository: https://github.com/nessocrm/nessocrm. Domain, written as one word: `nessocrm`.

The trial stack is the `nessocrm` compose, in this folder. Trial Espo: http://localhost:8088. Nesso: http://localhost:8091.

This document says what is already done and what is missing. The behaviour of the first version is in the [manual](index.md). The photograph of the production backup stays outside this repo. It is not the Nesso backlog.

## First version, 17 October 2026

It is a first version. It does the universal passage within the limits written below. It does not cover every system and it has the defects listed later.

### What it does

Nesso sits in the middle. Espo on one side, an external system on the other. Neither writes in the other's tables.

A **connection** is the channel. An **integration** is the rule: which connection, which entity, which fields, which column identifies the record, how often.

| Channel | Direction | Behaviour already working |
|---|---|---|
| Webhook | into Espo | Address with a token. Body as an object, a list, or `{records:[]}` |
| Database | into Espo | One SELECT on MySQL or MariaDB, read in pages of 200 until the end. The engine does not write on that database |
| CSV file | into Espo | Folder `scambio/{id}`, UTF-8, comma or semicolon. After the run the file goes to `elaborati/`, even if some row was rejected. If a required column is missing the file stays where it is |
| HTTP | out of Espo | JSON POST toward an address, or toward the local inbox. Bearer, user and password, or a header can be added |

The entity is not written in the code. Nesso reads the Espo metadata and offers the entities that have a tab and the writable fields.

The entity is created from the Entities screen, with singular and plural, or still from the "Espo entity" step of a new integration. Espo prefixes `C` to the name: Consegna becomes `CConsegna`. On that entity the external key and the mapped fields are born. From the Entities screen the new field has its real type. From the integration step the mapped fields are still born as text. The lookup toward another entity is many-to-one. If the linked record is missing, you choose: reject the row, leave the link empty, or create the record.

The identity of an inbound record is `{integration id}:{external value}`. On standard entities the field is `cExternalKey`. On entities created by Nesso it is `externalKey`. On entities that Espo does not let you customise (teams, folders, categories, roles, email templates) the key lives only in the engine `chiave` table. The same value, with the same fields, does not call Espo again: it stays `invariato`. If the fields change, Nesso does `PUT` on the same record.

Outbound remembers the last `modifiedAt` together with the Espo id. A run reads pages of 50, without skipping records that share the same instant. The HTTP send cursor moves only after the POSTs that succeeded: what did not leave goes out on the next run.

The cadence is manual, 5 minutes, 15 minutes, one hour, or a fixed time. An integration can declare which other one must start first. It can be paused: the scheduler and the webhook skip it, "Run now" does not. A switch stops every write toward Espo, and a read mode does the same for one integration. The interface has the Espo side menu. An integration is created and edited in four steps. In the mapping you copy a field, take the first word or the rest, write a fixed value, map a list, link an entity, several records, an activity, or name the team and the person. Every field has an owner. An Italian phone number is rewritten as `+39`. A date is read in three formats. The dry run shows the first rows without writing to Espo. The preview counts the whole run. Activity also lists rejected rows, conflicts and the latest runs. The configuration is downloaded and uploaded again, without the passwords.

Every call toward Espo uses the HTTP APIs, header `Espo-Authorization`. Creating an entity, creating a field, creating a lookup, reading and writing a record: they are all APIs. Nesso does not run SQL on the Espo tables.

The local instance is the public image `espocrm/espocrm:10.0`, installed empty. It is not the backup. The production backup is Espo 10.0.8 with the Advanced Pack. That package is not in the public image. On the trial, compose mounts it from `local/advanced-pack/`, a folder ignored by git.

### Known defects of this version

- If Espo does not return `modifiedAt`, the outbound cursor does not move and the next run sends the same records again.
- `/api/pull` writes the sink and advances the cursor, because there the delivery is the read itself. The HTTP send does not: the cursor moves only after the POSTs that succeeded.
- One run at a time. The second receives "a run is already in progress".
- The external database password is in clear text in the SQLite file of the local volume.
- The scheduler has not been watched for a full 15-minute cycle.
- There are no automatic tests.

## Archived

Closed. They are no longer work.

### Pipe, 18 October 2026

Reject journal. CSV and webhook that continue after a bad row. CSV with a semicolon, file moved to `elaborati/` even if some row fails. Inbound cursor if the column is named. Outbound pages. HTTP cursor that advances only after a successful send. One parent per integration. Lookup that can fail, stay empty or create the parent. On a duplicate, reject or adopt. Transforms, value map, phone `+39`. Dry run, edit, pause. Credentials on the HTTP outbound. Download and upload of the configuration. Key kept in the engine for entities Espo does not let you customise (teams, folders, categories, roles, email templates).

### Load, 19 October 2026

Field owner, with clearing only on source-owned fields and a queue if the owner is Espo. Preview of the whole run and a diff of the dangerous rows. Confirmation of the first close. Switch for every write. Read mode. Value history and undo of the run. VAT number or fiscal code already present, and a shape check. Inbound pages without the cap of 500. Fixed time. Quality before Espo: dates, lists, the field named in the error. The file stays put if a required column is missing. Three real values next to the mapping. Run summary with created, updated, closed and rejected. Visibility rule. Close of a record that disappeared, only on an entity that already has a status and only after confirmation the first time. The tests are in `motore/test_carico.py` and `motore/test_giro.py`.

### Language and recipe, 19 October 2026

The page speaks Italian or English. The choice is in the menu, key `nesso-lang`. The composed sentences of home have a key, so the same percent is read in the chosen language. The manual is in Italian and in English. A journal row already written is not rewritten. Nesso origin uses the language of the run; the scheduler writes in Italian. In the mapping step, "Propose the mapping" reads the column names and does not save until the person confirms. "Accounts recipe" prepares Account with the fields a customer export already has, and says it is not a certified connector. The synonyms are a list per language. The tests are in `motore/test_frasi.py`.

### Group key, 19 October 2026

The key can be several columns. The group case is company code plus customer code: in the queue it becomes `MI|C001`. Two companies with the same customer code stay two companies, and the same pair sent again updates. One column does not change: the cell stays the key, even if it contains `|`. The tests are in the class `ChiaveComposta` and in the runs `due societa` and `una colonna`.

### Handover, 19 October 2026

"Contacts recipe" prepares Contact: code, first name, last name, email, phone, and the company looked up by name. "Sites recipe" prepares the shipping address on Account, one site per company. Neither creates an entity. The handover page, `#/consegna`, lists addresses, integrations, schedule, the owner of each field and how to stop writes, and it contains no passwords and no tokens. The mapping sheet is downloaded and uploaded: column, field, transform, owner, required. A link stays where it is. JSON stays the configuration download. The tests are in the classes `RicetteSediEContatti`, `FoglioAbbinamento` and `PaginaConsegna`.

### Price list, PDF, stage, privacy, 19 October 2026

"Price list recipe" prepares Espo's Product: code, description, price, currency. It does not create the entity. In this trial Product is not there, and the fields stay empty until the entity is already in Espo. A PDF connection drops files in `scambio/{id}`: if the name contains the company key, the file becomes a Document on the customer, in the named folder and team, and moves to `elaborati/`. A name without that key stays where it is. An order can propose an offer's stage: the stage does not change until it is confirmed in Activity. The export of one person downloads what Nesso wrote about that contact and that company, skips password fields, and does not close or delete. The tests are in the class `ListinoPdfFasePrivacy` and in the runs `il pdf`, `l'ordine` and `l'export`.

### Sign-in, 20 October 2026

The port asks for a name and a password. The first entry changes the integrations; from Home you add who runs the jobs and reads the result, and that person does not save a mapping. Without an entry the configuration does not open and "Run now" does not start. Passwords do not end up in the journal or in the download. Webhook and inbox stay on the token in the address. `/api/health` stays open.

Runs write to Espo as the user `nesso`, created through the API, not as the admin. The password stays in the local volume and does not leave in the download. The role covers the entities of the enabled integrations, the links those use, and Document with Attachment if there is a PDF. Espo's user is read and is not created from that role. An entity outside the role is not written. New entities and fields stay calls of the bootstrap admin, because Espo's entity manager is not the run.

A failed run lights a notice on home with the integration's name, once, not once per rejected row. If the integration says "warn if it stays quiet for more than" so many minutes, and the last success is older, a second notice appears. The engine mail, when it exists, attaches to `deliver_notice`. Today that function does not send, and it does not use Espo's mail.

The tests are in the class `IngressoRuoloAvviso` and in the runs `senza ingresso`, `il giro fallito` and `la scrittura`.

### Switch-on, 19 October 2026

A plan orders integrations that are already saved. The next step can be turned back on only if the previous one was confirmed after its preview, and it does not turn on by itself. An integration outside the plan is paused and resumed as before. A quiet window, for one integration or for all of them, does not write on those days: the file stays where it is. When the window ends it does not start on its own: you confirm it, and then it writes, or you discard it into `scartati/` without touching Espo. With no windows and no plan the run is the one from before. The tests are in the class `FinestraEPiano` and in the runs `la finestra`, `dopo la finestra`, `scartare`, `il piano`.

### Morning, 19 October 2026

On home, the percent of accounts in sync and the time of the last successful run on the integration toward Account. A run already marked `ok`, with unchanged rows, counts even if it ran before the last-success field existed. If today's run fails, the percent is not shown and yesterday's time is not presented as today. A balance between keys in the source and keys already in Espo, with the amount gap if there is a currency or decimal field: it is a check, it does not write. For a file, a time by which it is expected: past that moment without a successful run, home is red, and a file already in `elaborati/` is not read again. On the Espo record, the Nesso origin field says whether the last update is from the ERP or from a person. The tests of the four functions are in the classes `Mattina`, `QuadraturaNumeri`, `FileAtteso` and `Badge`.

### Product and demo, 18 October 2026

Entities screen: list, integrations that touch it, new entity, new field with a real type and required. The field is appended to the detail and the list.

Gruppo Meridia demo loaded: customer masters, quotes in euro, contracts, jobs, invoices, tickets, visits, roles (Direction included), teams, users, folders, eight PDFs linked to company and quote, tasks, calls, articles, fair list, campaign, email templates. Chiara Fabbri reads the north-east customers and not those of Lombardy. The direction home stays readable. The "Trial snapshot" chapter is the photograph of the first seed, not this demo.

## Outside the product

These are not built. They are the boundary.

- CRM mail stays in Espo. Nesso does not send it.
- Advanced Pack reports and processes are not rewritten and not published. The package stays in `local/advanced-pack/`, outside git. Nesso delivers records that those already know how to read.
- The demo is the proof, not a second product. Entities are not invented to show movement.
- Nesso always has Espo on one side. It is not a bridge between two arbitrary systems.
- No SQL on the Espo tables. No production dumps.
- Espo users are not born from a customer master. A people run, if it is needed, stays off until it is switched on.
- Closing a record that disappeared from the source leaves it in the history. The right to be forgotten is another gesture, and it is not this close.
- The four flows of the backup (site, night files, masters, jobs) do not become code. They become configurations when the channels exist. The plan stays in the backup, outside this repo.

## Closed decisions

The open code respects them.

- Nesso governs the entities.
- Visibility is a rule: "this row belongs to the Sales team, assigned to this person".
- If the record disappears from the source, it is closed in Espo and stays in the history.
- By default the source wins, even if the cell arrives empty. The field can have another owner: the open item "field owner" says so.
- Write-back toward the ERP stays off until it is chosen.

## Open

An item stays here until it is in the engine. Those already closed are not repeated. The functions meant to convince a company, distinct from this technical list, are in [Adoption](15-adozione.md).

### Data and visibility

- Several parents: "companies and sites first, then the address book". Today only one is named.
- A retry queue with growing wait, for a silent outbound and for the row whose parent has not arrived yet.
- Outbound, the link leaves as an external key, not as an Espo id.
- Change the label of a field that was already created.
- Several links toward the same entity, with the chosen name. If one exists, Nesso reuses it. If two exist, it stops or creates another without asking the name.
- Layout: detail, list, kanban. Today the new field is appended at the end.
- Required fields checked before the run, with the message on the field.
- Currency and time zone on read. The Italian phone is already `+39`. The trial quotes are already in euro.
- An activity born with the record: task, call, meeting, with date and assignee.
- A note in the history, so you can see where the row came from.
- Portal: a contact that enters from outside has a path.

### Use

- Next run, last success, last error, how long it has been silent.
- Repeat a single rejected row, without replaying the whole file.
- An error with the field name.
- Dry run of the webhook: paste an example. Today it answers that it has no rows.
- Two environments, trial and production, and moving the configuration with the passwords typed by hand.
- History of the rule: who changed the mapping, and going back to the previous version.
- Secrets outside SQLite in clear text.
- Several runs together, or at least one per channel. After an error the scheduler still waits the whole interval.
- Automatic tests on the four channels, on the new entity and on the lookup.

### Channels

- SFTP and FTPS, for reading and for drop-off. Excel, not only CSV.
- Postgres, SQL Server, Oracle. TLS and a tunnel, also on MySQL.
- Signed HTTP inbound. OAuth outbound.
- Write-back on the source, off until it is switched on.
- The document as a channel, with folder and visibility. The path of a local file can already be uploaded to a file field.
- The local inbox delivers the JSON to another integration. Today it accumulates it and stops.
- Engine mail, SMTP and IMAP, separate from Espo's: a notice, the day's summary, an outbound message composed from the fields, an inbound message that becomes a record. Its own credentials, a send test, a queue if the send fails.

### In what order

1. The channels, starting from the one a real load cannot read.
