# API

Base: `http://localhost:8091`. I corpi sono JSON. Gli errori di regola sono `{"error": "testo"}`.

| Situazione | HTTP |
|---|---|
| validazione, Espo ha rifiutato, query vietata | 400 |
| token di hook o inbox errato | 401 |
| id integrazione o collegamento assente dove il codice usa `KeyError` | 404 |
| percorso sconosciuto | 404 |
| successo | 200 |

Non c'è autenticazione sulle API di configurazione. Chi raggiunge la porta 8091 crea collegamenti e lancia giri. L'unico segreto è il token dentro gli URL di hook e inbox.

## GET /api/health

```json
{"ok": true, "espo": "raggiungibile", "fields": "pronti", "detail": "Lead.externalKey presente, Account.externalKey presente, Account.partitaIva presente"}
```

`espo` passa da `in attesa` a `attendo Espo`, poi `raggiungibile` o `non raggiungibile`. `fields` è `non creati`, `pronti` o `errore`. Il server risponde anche mentre Espo non c'è ancora.

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

L'elenco reale dipende dall'installazione. La cache dura 120 secondi. HTTP 400 se il metadata di Espo non risponde.

## GET /api/state

Lo usa la pagina a ogni refresh. Contiene:

| Chiave | Contenuto |
|---|---|
| `state` | gli stessi `espo`, `fields`, `detail` di health |
| `espoPublicUrl` | link pubblico |
| `publicBase` | base degli URL di hook |
| `pipelines` | tutte le integrazioni, `mapping` già lista, ordinate per direzione e id |
| `connections` | collegamenti senza password. Webhook ha `url`. HTTP ha `inboxUrl`. Il CSV non ha il path assoluto qui: la pagina ricostruisce `scambio/{id}` |
| `queue` | ultimi 30 ingressi, `updated_at` discendente |
| `sink` | ultimi 20 record letti in uscita |
| `deliveries` | ultime 20 consegne, id discendente |

## POST /api/connections

Crea. Senza `id`, lo slug nasce dal nome.

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

`columns` manca di senso se la prova `LIMIT 5` torna zero righe: la lista è vuota e il collegamento è comunque salvato.

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

Aggiornare: stesso corpo più `"id"` di una riga esistente. Il token non cambia. Kind e config vengono sostituiti.

Errori tipici: «manca il nome del collegamento», «tipo di collegamento non riconosciuto», «manca host», «è ammessa una sola SELECT», «l'indirizzo di destinazione deve essere http o https», più l'errore di connessione a MariaDB se la prova fallisce.

## DELETE /api/connections/{id}

```json
{"deleted": "sito-web"}
```

Le integrazioni che lo citavano restano, con collegamento vuoto. 404 se la delete non tocca righe.

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

In uscita, `from` è il campo Espo:

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

`connectionId` vuoto è ammesso dall'API. La pagina no. Passare `id` di una integrazione esistente la aggiorna e non cancella coda né cursore.

In ingresso, prima di salvare, il motore chiama la creazione di `externalKey` sulla scheda. Se Espo rifiuta il campo, il salvataggio fallisce.

Errori tipici: «manca il nome dell'integrazione», «scegli la scheda Espo», «indica il campo che identifica il record nel sistema esterno», «abbina almeno un campo», «scheda Espo non disponibile», «campi Espo non riconosciuti: …», «la cadenza può essere manuale, 5, 15 o 60 minuti», «il collegamento e il verso non coincidono».

## POST /api/pipelines/{id}/run

Il corpo è ignorato. La risposta dipende dal canale.

| Canale | Corpo di successo |
|---|---|
| nessuno, uscita | il risultato di pull: `exported`, `cursor`, `total`, `records` |
| nessuno, ingresso | 400 «collega un sistema esterno prima di eseguire» |
| webhook | `{"waiting": true, "url": "..."}` |
| database | `{"rows": 3, "created": 2, "updated": 0, "failed": 1}` |
| csv | `{"rows": 1, "results": 1}` |
| http | `{"sent": 3, "url": "http://127.0.0.1:8091/inbox/..."}` |

409 di concorrenza sul lucchetto: 400 «un'esecuzione è già in corso». Anche in quel caso, se l'eccezione esce da `run_pipeline`, `mark_run` segna errore. Il `finally` rilascia il lucchetto.

## DELETE /api/pipelines/{id}

```json
{"deleted": "lead-verso-portale"}
```

Cancella coda, sink e cursore di quell'id. Non cancella i record su Espo e non cancella `delivery`.

## POST /hook/{id}/{token}

Corpo, un record:

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

`accepted` è il numero di ingest eseguiti. Con due integrazioni sullo stesso webhook e un record, è 2. Con una integrazione e una lista di tre, è 3.

## POST /inbox/{id}/{token}

```json
{"nome": "Marta", "cognome": "Bianchi"}
```

```json
{"stored": true}
```

Non inoltra a Espo.

## POST /api/ingest/{id}

Un solo oggetto, la pipeline deve essere in ingresso. Stessa risposta di un elemento di `results` qui sopra. È il percorso con cui sono entrati Marta Bianchi (`modulo-web`), Officina Del Porto (`anagrafica-clienti`) e Luca Neri (`contatti-del-gestionale`), che non hanno un collegamento.

## POST /api/pull/{id}

Stessa risposta di pull, senza invio e senza aggiornare `last_run`. È il percorso di `uscita-lead` e di `contatti-da-espo`.

## DELETE e POST su percorsi sbagliati

Un `GET` su `/api/pipelines` è 404. Non c'è lista separata: la lista è dentro `/api/state`. Non c'è `PATCH`.
