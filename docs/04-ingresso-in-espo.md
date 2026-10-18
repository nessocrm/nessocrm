# Ingresso in Espo

Tutti i canali in ingresso finiscono nella stessa funzione, `ingest`. Webhook, SELECT e CSV differiscono solo per come ottengono l'elenco di oggetti. Da lì in poi il record è un dizionario di stringhe.

## Condizioni per entrare

La funzione rifiuta, senza scrivere su Espo, se:

- l'id integrazione non esiste
- la direzione non è `in`
- nel corpo manca la colonna `external_id_field`, o è vuota o solo spazi
- il modello di chiave, dopo la sostituzione, contiene ancora una graffa o è vuoto

Il modello è il testo salvato, per esempio `richieste-del-sito-verso-lead:{id}`. Ogni chiave del corpo sostituisce `{nome}`. Il corpo del webhook di Giulia Costa è:

```json
{"id": "WEB-77", "nome": "Giulia", "cognome": "Costa", "email": "giulia.costa@example.test"}
```

`{id}` diventa `WEB-77`. La chiave esterna è `richieste-del-sito-verso-lead:WEB-77`.

Se l'integrazione chiede la colonna `codice` e il CSV ha `codice` vuoto, l'errore è «manca il campo codice». Se il modello cita un nome che il corpo non ha, la graffa resta e l'errore è «chiave esterna incompleta».

## Abbinamento

Ogni regola legge `transform`.

| Valore | Risultato |
|---|---|
| assente, oppure `copy` | `str` del valore. `None` viene saltato |
| `const:Web Site` | la stringa dopo i due punti, anche se `from` è vuoto |
| `split_first` | prima parola di `from` |
| `split_last` | tutto dopo il primo spazio. Una sola parola produce `None` e il campo non si scrive |
| altro | errore «transform sconosciuto» |

Una stringa vuota non viene scritta. Poi, se la chiave c'è e la scheda accetta il campo, il motore aggiunge `mapped[key_field] = chiave`, anche se l'abbinamento non cita quel campo. È il motivo per cui Giulia Costa ha `cExternalKey` pur mappando solo nome, cognome ed email. Se la scheda non è personalizzabile, la chiave non entra nel JSON: resta nella tabella `chiave`.

Risultato mandato a Espo per quel lead:

```json
{
  "firstName": "Giulia",
  "lastName": "Costa",
  "emailAddress": "giulia.costa@example.test",
  "cExternalKey": "richieste-del-sito-verso-lead:WEB-77"
}
```

I numeri letti da MariaDB diventano stringhe prima di arrivare qui. Un intero `100` parte come `"100"`.

## Hash

```text
SHA-256( JSON del mappato, chiavi ordinate, UTF-8, ensure_ascii false )
```

Conta il mappato, non il corpo originale. Due corpi esterni diversi che producono lo stesso mappato sono lo stesso invio. Un campo Espo in più nell'abbinamento cambia l'hash.

Si salta Espo solo se esiste già la riga di coda, lo stato è `synced` e l'hash è identico. La risposta è:

```json
{
  "status": "invariato",
  "espoId": "6ad353977a2a687a1",
  "externalKey": "richieste-del-sito-verso-lead:WEB-77",
  "entity": "Lead"
}
```

`invariato` non compare nel conteggio `created` / `updated` del giro database. Un giro successivo che ritrova due righe invariate e una scartata viene marcato `errore`, perché create e updated sono zero e failed è uno. È lo stato attuale di `clienti-gestionale-verso-account`: il primo giro aveva creato Studio Nord e Panificio Rosa; un giro dopo ha saltato quei due per hash e ha riscattato Officina del Porto, e il dettaglio è diventato «0 create, 0 aggiornate, 1 scartate».

## Ricerca e scrittura

1. Se la coda ha già un `espo_id` per quell'id esterno, `PUT /api/v1/{Scheda}/{id}` con il mappato. Azione `aggiornato`.
2. Altrimenti `GET` con `where equals` sul campo chiave, `maxSize=1`, `select=id,{campo}`.
3. Trovato: `PUT`. Non trovato: `POST`. Azione `creato`.

La ricerca che fallisce (HTTP diverso da 200) ferma il record. Non si indovina.

Dopo un 200 o 201 il motore fa upsert sulla coda: inserisce o sostituisce payload, mappato, hash, stato `synced`, id Espo, dettaglio `creato` o `aggiornato`, orario.

## Il 409

Espo risponde 409 con una lista di record quando il suo controllo duplicati scatta. Il caso visto è l'Account: il nome «Officina del Porto» assomiglia a «Officina Del Porto» già presente.

Il motore guarda il primo elemento della lista.

- Se quell'elemento ha la stessa `cExternalKey` del mappato e ha un `id`, fa `PUT` su quell'id e considera il record aggiornato.
- Se la chiave è diversa o assente, alza «Espo ha già un record simile (Officina Del Porto) con un'altra chiave».

Nel secondo caso il record non entra e la coda non cambia. Le due anagrafiche restano separate: `anagrafica:CLI-42` è l'Account creato a mano via ingest, `clienti-gestionale-verso-account:CLI-100` non esiste su Espo.

Non c'è un tentativo di fondere i due record, né di scrivere un legame. La politica è unica per tutte le schede.

## Risposte

| status | Quando |
|---|---|
| `creato` | POST nuovo, id Espo nuovo |
| `aggiornato` | PUT sulla chiave già nota, oppure PUT dopo un 409 della stessa chiave |
| `invariato` | hash già sincronizzato |

Il telefono di Marta Bianchi è l'esempio di `aggiornato`: stesso id esterno `WEB-1001`, stesso id Espo `6ad34a7e5b76fe198`, hash diverso, PUT.

## Errori per canale, dopo ingest

| Canale | Una riga fallisce |
|---|---|
| Database | conta `failed`, ricorda il primo messaggio, continua con la riga dopo. Stato del giro `errore` solo se nessuna riga è creata o aggiornata |
| CSV | l'eccezione esce, il giro è `errore`, i file non ancora spostati restano in cartella. Le righe già scritte in questo giro restano in coda |
| Webhook | l'eccezione esce verso il chiamante con HTTP 400. Le integrazioni successive di quello stesso collegamento non partono. `mark_run` di quella integrazione non viene eseguito se l'errore nasce dentro il suo ciclo |
| `POST /api/ingest/{id}` | HTTP 400 con il testo. Nessun'altra riga, perché il corpo è un solo oggetto |

Il giro database non scrive una riga di coda per la scartata, quindi «Ultimi passaggi» non la elenca. Si vede in `last_detail` sulla scheda dell'integrazione.
