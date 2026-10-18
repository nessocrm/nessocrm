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

Il cursore parte da `1970-01-01 00:00:00` se l'integrazione non ha ancora una riga in `cursor_state`. Il valore salvato è `modifiedAt`, poi una tabulazione, poi l'id Espo. Un cursore vecchio, senza tabulazione, viene letto lo stesso: al giro successivo i record con quell'istante possono uscire un'altra volta, poi il formato nuovo li distingue.

La lettura è a pagine da 50. Prima completa i record con lo stesso `modifiedAt` del cursore e id maggiore. Poi prende i `modifiedAt` successivi. Se una pagina è piena di uno stesso istante, continua per id, così nessuno resta fuori. Un giro si ferma a 1000 record. Il select include sempre `id` e `modifiedAt`.

`/api/pull` scrive il sink e poi il cursore, perché la consegna è la lettura. L'invio HTTP non usa questo percorso.

Cursori presenti il 17/10/2026:

| Integrazione | Cursore |
|---|---|
| `uscita-lead` | 2026-10-17 10:14:22 |
| `contatti-da-espo` | 2026-10-17 10:14:23 |
| `lead-verso-portale` | 2026-10-17 10:53:11 |

Il select chiede sempre `id` e `modifiedAt`, anche se l'abbinamento non li mappa. Se un record non ha `modifiedAt`, il cursore non avanza su quel record.

## Invio

Solo il kind `http` invia. L'indirizzo è `config.url` se è valorizzato. Se è vuoto, l'indirizzo è la casella interna:

```
http://127.0.0.1:8091/inbox/{id collegamento}/{token}
```

È un POST JSON, header `Content-Type: application/json`, timeout 20 secondi. Sul collegamento si può aggiungere un Bearer, utente e password, oppure un'intestazione con nome e valore. Il token nell'indirizzo resta solo per la casella interna.

Per ogni record, dopo un HTTP sotto 300:

- una riga `delivery` con status `inviato`, dettaglio uguale all'URL, `pipeline_id` valorizzato
- il contatore `sent` cresce

Un HTTP da 300 in su, o un errore di rete, ferma il ciclo. I record già inviati restano inviati e il cursore arriva all'ultimo di quelli. Il record che ha fallito, e i successivi, escono al giro dopo. Lo scarto sta in `scarto` e in `delivery` con status `errore`.

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

Non cancella su Espo. Non manda gli eliminati. Non segue le relazioni. Un giro legge fino a 1000 record, a pagine da 50. Il POST può portare Bearer, basic o un'intestazione. Un invio fallito non fa avanzare il cursore oltre l'ultimo POST riuscito.
