# API

Base: `http://localhost:8091`. I corpi sono JSON. Gli errori di regola sono `{"error": "testo"}`. Se la richiesta manda `X-Nesso-Lang: en`, il testo dell'errore esce in inglese quando la frase è nel catalogo; altrimenti resta in italiano. Il giornale salva comunque la frase italiana.

| Situazione | HTTP |
|---|---|
| validazione, Espo ha rifiutato, query vietata | 400 |
| token di hook o inbox errato | 401 |
| id integrazione o collegamento assente dove il codice usa `KeyError` | 404 |
| percorso sconosciuto | 404 |
| successo | 200 |

Non c'è autenticazione sulle API di configurazione. Chi raggiunge la porta 8091 crea collegamenti e lancia giri. L'unico segreto è il token dentro gli URL di hook e inbox.

## GET /api/frasi

Catalogo inglese della pagina: `lingue` è `["it", "en"]` e `en` è la mappa dalla frase italiana a quella inglese. L'italiano non sta in un secondo elenco: è la chiave.

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
| `morning` | percentuale delle anagrafiche, tono e frase. `percent` è nullo se oggi non c'è un giro riuscito |
| `alerts` | frasi della quadratura rossa e del file atteso non elaborato |

Su ogni integrazione in ingresso da CSV, `balance` è la quadratura e `file_alert` è 1 se il file atteso non è ancora stato elaborato oggi. `expectAt` si salva con l'integrazione, accanto a `scheduleAt`.

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

## POST /api/sheets

Crea una scheda Espo. Il corpo è `singular` e `plural`. La risposta ha `name`, il nome tecnico (`C` più il singolare). Nasce anche il campo chiave esterna.

## POST /api/sheets/{nome}/fields

Aggiunge un campo a una scheda che Espo lascia personalizzare. Il corpo ha `label`, `type` e, se serve, `options` e `required`.

`type` è uno di `varchar`, `text`, `int`, `float`, `date`, `datetime`, `bool`, `enum`, `currency`, `email`, `phone`, `url`. Per `enum`, `options` è un elenco oppure un testo con un valore per riga. `required` vero marca il campo obbligatorio.

Il nome tecnico lo ricava l'etichetta. Sulle schede standard Espo antepone `c`. Il campo viene appeso al dettaglio e all'elenco. Se la scheda non è personalizzabile, la risposta è 400.

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

Corpo facoltativo `{"withDependencies": true}`. Se è vero, prima parte l'integrazione indicata in `dependsOn`, e la sua, a catena. La risposta dipende dal canale.

| Canale | Corpo di successo |
|---|---|
| nessuno, uscita | il risultato di pull: `exported`, `cursor`, `records` |
| nessuno, ingresso | 400 «collega un sistema esterno prima di eseguire» |
| webhook | `{"waiting": true, "url": "..."}` |
| database | `rows`, `created`, `updated`, `unchanged`, `closed`, `failed`, `status` |
| csv | `rows`, `created`, `updated`, `unchanged`, `closed`, `failed`, `status` |
| http | `{"sent": 3, "url": "...", "failed": false}` |

409 di concorrenza sul lucchetto: 400 «un'esecuzione è già in corso». Anche in quel caso, se l'eccezione esce da `run_pipeline`, `mark_run` segna errore. Il `finally` rilascia il lucchetto.

## POST /api/pipelines/{id}/dry

Legge al massimo cinque righe e restituisce `rows`, ognuna con `mapped` oppure `status: scartato`. Non scrive su Espo. Un lookup mancante con politica «crea» compare come `nuovo:valore` e il record non nasce. Il webhook risponde che non ha righe da leggere.

## POST /api/pipelines/{id}/anteprima

Conta il giro intero senza scrivere: create, aggiornate, chiuse, scartate, e `pericolose` con il valore di oggi e quello in arrivo. Non sposta i CSV e non avanza il cursore.

## POST /api/pipelines/{id}/lettura

`{"enabled": true, "hours": 48}` accende la modalità lettura. Alla scadenza non si passa da soli alla scrittura: si esce con `{"enabled": false}`.

## POST /api/pipelines/{id}/annulla

Ripristina i campi scritti dall'ultimo giro, solo se nessuno li ha cambiati dopo. Risposta `restored` e `kept`.

## POST /api/pipelines/{id}/chiusure

Conferma la prima chiusura dei record spariti dalla sorgente e li chiude. Senza uno stato sulla scheda risponde 400.

## POST /api/scritture

`{"enabled": false}` ferma ogni scrittura verso Espo. L'anteprima e la prova a secco restano.

## POST /api/connections/{id}/campione

Le prime tre righe del CSV o del database, per l'abbinamento.

## POST /api/proponi

Corpo `columns`, `fields` (nome e etichetta dei campi della scheda) e `samples`. Non scrive l'integrazione. Ogni riga ha `from`, `to`, `known`, `role` (`field` o `identity`), `sample` e `reading`. La lingua è quella dell'intestazione. `identity` è la colonna da usare come chiave esterna, non un campo. Una data riconosciuta in `reading` è `AAAA-MM-GG`.

## POST /api/ricette/anagrafiche

Corpo `fields` della scheda Account. Risponde con `id` `anagrafiche`, `entity` `Account`, `externalIdField` `codice`, le righe dell'abbinamento e `noteKey`. Non crea l'integrazione: la pagina applica le righe e la persona le può ancora cambiare.

## POST /api/watch/{id}

`{"keep": "espo"}` lascia il valore attuale. `{"keep": "sorgente"}` scrive quello in arrivo.

## POST /api/pipelines/{id}/enabled

Corpo `{"enabled": false}` mette in pausa. `true` riattiva. La pausa vale per il pianificatore e per il webhook. «Esegui ora» parte lo stesso.

## GET /api/export e POST /api/import

Lo scarico è l'elenco dei collegamenti, senza password, token e valori di intestazione, e l'elenco delle integrazioni con la mappa già compilata. Il caricamento ripristina quel file. Le password vuote, se il collegamento esiste già, restano quelle di prima. L'import di un'integrazione scrive la mappa così com'è, senza ricreare i campi su Espo.

## DELETE /api/pipelines/{id}

```json
{"deleted": "lead-verso-portale"}
```

Cancella coda, sink, cursore, scarti e giornale dei giri di quell'id. Non cancella i record su Espo e non cancella `delivery`.

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
