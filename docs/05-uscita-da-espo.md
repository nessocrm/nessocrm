# Uscita da Espo

L'uscita è `pull`. La usa il collegamento HTTP e anche `POST /api/pull/{id}`, che si ferma al motore e non chiama nessuno fuori.

## Chi può uscire

La pipeline deve esistere e avere direzione `out`. Altrimenti «la pipeline non è in uscita», oppure 404.

L'abbinamento si legge al contrario rispetto all'ingresso: `from` è il campo Espo, `to` è il nome nel JSON che esce. Per `lead-verso-portale`:

| Campo Espo | Nome inviato |
|---|---|
| `firstName` | `nome` |
| `lastName` | `cognome` |
| `emailAddress` | `email` |
| `cExternalKey` | `chiave` |

Un valore `None` nel record Espo non entra nel JSON. Una stringa vuota, se Espo la restituisce, entra.

## Lettura

Il cursore parte da `1970-01-01 00:00:00` se l'integrazione non ha ancora una riga in `cursor_state`.

```
GET /api/v1/{Scheda}
  select = campi from, separati da virgola, ordinati
  maxSize = 50
  orderBy = modifiedAt
  order = asc
  where[0][type] = after
  where[0][attribute] = modifiedAt
  where[0][value] = cursore
```

`after` è successivo, non «uguale o successivo». Un record con `modifiedAt` identico al cursore non esce un'altra volta. Cinquanta è il tetto di un giro. Se ne esistono di più, il cursore avanza all'ultimo dei cinquanta e il giro dopo prende i successivi, a patto che il loro `modifiedAt` sia maggiore.

Per ogni record:

1. costruisce il JSON con i nomi `to`
2. inserisce una riga in `sink_item` (integrazione, id Espo, JSON, ora)
3. se `modifiedAt` è presente e maggiore del cursore di lavoro, lo tiene
4. se ne ha esportato almeno uno, salva quel cursore

Poi restituisce `exported`, `cursor`, `total` (il totale che Espo dichiara per il filtro) e `records`.

Cursori presenti il 17/10/2026:

| Integrazione | Cursore |
|---|---|
| `uscita-lead` | 2026-10-17 10:14:22 |
| `contatti-da-espo` | 2026-10-17 10:14:23 |
| `lead-verso-portale` | 2026-10-17 10:53:11 |

`lead-verso-portale` non chiede `modifiedAt` nell'abbinamento. Il cursore è comunque avanzato: Espo ha restituito `modifiedAt` insieme ai campi chiesti, e il motore lo ha letto. Se una versione di Espo omettesse `modifiedAt` quando non è in `select`, il cursore resterebbe fermo e ogni giro rimanderebbe gli stessi 50. Il select non lo aggiunge da sé.

## Invio

Solo il kind `http` invia. L'indirizzo è `config.url` se è valorizzato. Se è vuoto, l'indirizzo è la casella interna:

```
http://127.0.0.1:8091/inbox/{id collegamento}/{token}
```

È un POST JSON, header `Content-Type: application/json`, timeout 20 secondi, senza altro header di autenticazione. Il token sta nel percorso solo quando la destinazione è la casella. Una destinazione esterna riceve il corpo nudo.

Per ogni record, dopo un HTTP sotto 300:

- una riga `delivery` con status `inviato`, dettaglio uguale all'URL, `pipeline_id` valorizzato
- il contatore `sent` cresce

Un HTTP da 300 in su, o un errore di rete, ferma il ciclo. I record già inviati in quel giro restano inviati. Il cursore è già stato salvato da `pull` prima del primo POST. I record letti e non ancora inviati non vengono ritentati al giro dopo, perché il loro `modifiedAt` non è più successivo al cursore.

`mark_run` scrive «N record inviati a {url}».

Nella prova, tre lead sono usciti verso la casella. Il diario ha, per ciascuno, una riga `inviato` e una riga `ricevuto`. La seconda la scrive la casella, non il giro di invio. `pipeline_id` della riga ricevuta è nullo: la casella non sa quale integrazione ha spedito.

Corpo di Marta Bianchi, sia inviato sia ricevuto:

```json
{
  "nome": "Marta",
  "cognome": "Bianchi",
  "email": "marta.bianchi@example.test",
  "chiave": "modulo-web:WEB-1001"
}
```

La chiave è quella con cui il lead era entrato, non un id nuovo calcolato in uscita. L'uscita non inventa chiavi. Copia i campi abbinati.

## Senza destinazione

«Esegui ora» su un'uscita senza collegamento chiama lo stesso `pull`, salva sink e cursore, e il dettaglio è «letti N record, senza destinazione». Non crea `delivery`. È il caso di `uscita-lead` e di `contatti-da-espo`.

`contatti-da-espo` mappa il nome Account sul nome esterno `bo`. Nel sink c'è una riga: `{"bo": "Officina Del Porto"}`, id Espo `6ad34a7f1b75d9805`. `last_status` di quell'integrazione è vuoto: la lettura è passata da `/api/pull/`, che non aggiorna l'ultimo esito. La pagina, invece, usa `/api/pipelines/{id}/run`.

## Casella

`POST /inbox/{id}/{token}` con un collegamento di kind `http` e token uguale:

- HTTP 200 `{"stored": true}`
- una riga `delivery` status `ricevuto`, dettaglio «sistema esterno»

Token o id errati, o kind diverso da `http`: HTTP 401 «casella non valida». Il corpo può essere qualsiasi JSON oggetto. La casella non lo manda a Espo e non lo valida contro un abbinamento. È un punto di osservazione per provare l'uscita senza un server esterno, e un indirizzo che un sistema esterno può chiamare se gli si dà il token.

## Che cosa l'uscita non fa

Non cancella su Espo. Non manda gli eliminati. Non segue le relazioni (il contatto di un account, le opportunità). Non pagina oltre i 50 nello stesso giro. Non firma il POST. Non ritenta un invio fallito senza spostare il cursore all'indietro: il cursore non si sposta all'indietro da solo.
