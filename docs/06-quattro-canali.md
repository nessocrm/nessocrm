# I quattro canali

Il kind è scelto alla creazione e, se si aggiorna via API passando l'id, può cambiare perché `save_connection` riscrive `kind` e `config_json`. Il token resta. La pagina non ha un modulo di modifica: il cambiamento di kind è solo API.

Il verso ammesso sull'integrazione è fisso: `http` solo `out`, gli altri tre solo `in`. Salvare un accoppiamento storto risponde «il collegamento e il verso non coincidono».

## Webhook

Pensato per un sistema che chiama appena nasce un dato: un form, un gestionale con un evento.

Alla creazione il motore non chiede parametri. Costruisce:

```
{PUBLIC_BASE_URL}/hook/{id}/{token}
```

Con i valori di compose, la base è `http://localhost:8091`. L'indirizzo compare sulla scheda del collegamento. Chi lo possiede può inserire dati. Non c'è un secondo fattore.

`POST` accetta:

| Corpo | Interpretazione |
|---|---|
| `{...}` | un record |
| `[ {...}, {...} ]` | un record per elemento |
| `{ "records": [ {...} ] }` | un record per elemento di `records` |
| altro | HTTP 400 «il corpo deve essere un oggetto o un elenco» |

Il token è confrontato in tempo costante (`hmac.compare_digest`). Collegamento inesistente, kind diverso, token diverso: HTTP 401 «collegamento non valido».

Se nessuna integrazione in ingresso punta a questo id: HTTP 400 «nessuna integrazione usa questo collegamento». Il corpo non viene conservato.

Per ogni integrazione in ingresso attiva, per ogni record, chiama l'ingresso. Una riga che fallisce viene scritta in `scarto` e il lotto continua. Un elemento che non è un oggetto è uno scarto. A fine lotto `mark_run` riporta create, aggiornate, invariate e scartate. Un'integrazione in pausa non riceve il webhook.

«Esegui ora» non simula un payload. Risponde `{"waiting": true, "url": "..."}` e scrive lo stesso stato `ok` con «in attesa che il sistema esterno chiami l'indirizzo». La pagina mostra «In attesa di chiamate sull'indirizzo del webhook.»

Nella prova il collegamento è `sito-web`, l'integrazione è `richieste-del-sito-verso-lead`. Un POST ha creato il lead `WEB-77`.

## Database

Pensato per un gestionale o una vista di commesse, letti dal motore.

Campi richiesti al salvataggio: `host`, `database`, `user`, `query`. `port` mancante diventa 3306. `password` può essere vuota. In aggiornamento, password vuota e password precedente presente: si tiene la precedente.

La query è rifiutata se:

- è vuota
- supera i 4000 caratteri
- contiene `;`
- non inizia con `SELECT` o `WITH`, ignorando maiuscole e spazi iniziali

Il motore non esegue il testo così com'è. Lo avvolge:

```sql
SELECT * FROM ( {query} ) AS sorgente LIMIT {n} OFFSET {scostamento}
```

`n` è 5 durante il salvataggio e nella prova a secco. In esecuzione le pagine sono da 200 e si continua finché la pagina non è corta: non c'è il tetto di 500. Se l'integrazione ha una colonna di variazione, la SELECT è ordinata per quella colonna e per la colonna identità, e il giro dopo riparte dall'ultimo valore letto, anche se è uguale, usando l'identità come spareggio. I nomi colonna sono solo lettere, cifre e trattino basso. Il salvataggio fallisce se l'host non risponde, se l'utente non ha il permesso, o se la query è invalida. Se risponde, la API restituisce `columns` e le salva nel collegamento, così il passo di abbinamento le propone. La connessione usa `connect_timeout` 8 secondi e `read_timeout` 30. Cursore dizionario. Ogni valore non nullo diventa stringa.

Non c'è un parser SQL oltre la regex iniziale. Una SELECT che contiene la parola insert in una stringa passa. Una seconda istruzione no, perché il punto e virgola è vietato. `INSERT`, `UPDATE`, `DELETE` a inizio testo no.

Esecuzione: legge tutte le pagine, ingest per riga, prosegue dopo l'errore. Dettaglio:

```text
{n} righe dal database, {c} create, {u} aggiornate, {chiuse} chiuse, {i} invariate, {f} scartate
```

Lo stato è `errore` solo quando ci sono scarti e non c'è nessuna riga creata, aggiornata o invariata. Ogni scarto resta nella tabella `scarto`.

Host usabile da dentro il contenitore per la prova: `db`. Database `gestionale`, utente `espocrm`, password `locale-db`. La query salvata è:

```sql
SELECT codice, ragione_sociale, email, piva FROM clienti
```

Il capitolo esercizio ha il `CREATE TABLE` e le tre righe. Quel database non è nel compose: vive nel volume MariaDB.

La pagina, sotto la scheda, mostra la query. Non mostra host, utente, password.

## File CSV

Pensato per un deposito notturno: qualcuno lascia un file, il motore lo consuma.

Alla creazione crea:

```
{SCAMBIO_DIR}/{id}/
{SCAMBIO_DIR}/{id}/elaborati/
```

Con compose, sull'host è `scambio/{id}/`. Il config è vuoto. La scheda dice di depositare i `.csv` in `scambio/{id}`.

Lettura:

- solo i file `*.csv` direttamente in quella cartella, non nelle sottocartelle
- ordine per nome
- encoding `utf-8-sig`, quindi un BOM in testa non diventa parte del primo nome colonna
- `csv.DictReader`: la prima riga è l'intestazione
- chiavi `None` (colonne in più senza nome) vengono tolte
- una cella vuota resta stringa vuota. Se il padrone del campo è la sorgente, quella cella svuota il campo su Espo. Se il padrone è Espo, il contrasto va in coda e il campo non si tocca

Il separatore è la virgola, oppure il punto e virgola se nella prima riga i punti e virgola sono di più. Una riga che fallisce va in `scarto` e le altre continuano. A fine giro ogni file letto viene rinominato in `elaborati/{AAAAMMGGHHMMSS}-{nome}`, anche se qualche riga è stata scartata. Se manca una colonna obbligatoria, fra cui la colonna identità, quel file non si sposta e lo scarto è uno solo: «manca la colonna …».

Nella prova: `scambio/file-notturno/elaborati/20261017105401-contatti.csv`, una riga, contatto Sara Verdi, id esterno `CNT-20`, integrazione `file-notturno-verso-contatti`.

Un CSV senza una colonna obbligatoria, compresa quella identificativa, produce un solo scarto «manca la colonna …» e non viene spostato. Il giro dopo riprova. I file già in `elaborati/` non si rileggono. Se l'integrazione ha un'ora «atteso entro» e a quell'ora non c'è un giro riuscito di oggi, la home è rossa e il giornale registra l'assenza una volta al giorno.

## PDF sul cliente

Il collegamento è `pdf`. I file `*.pdf` si depositano in `scambio/{id}`, non nelle sottocartelle. Se il nome contiene la chiave di un'azienda, come parola intera, il file diventa un Document collegato a quell'Account, nella cartella documenti e nel team scritti sul collegamento, e si sposta in `elaborati/`. Fra due chiavi vince la più lunga: `C001` non prende `fattura-C0012.pdf`. Un nome senza chiave resta in cartella. Non è il canale documenti generale: è questo gesto.

## HTTP in uscita

Pensato per un portale che riceve i cambiamenti di Espo.

L'unico parametro è `url`. Vuoto è ammesso. Se è valorizzato deve iniziare con `http://` o `https://`. Non si verifica, al salvataggio, che l'host risponda.

URL vuoto: il giro spedisce alla casella del motore, descritta nel capitolo uscita. La scheda mostra `inboxUrl` pubblico (`localhost`), mentre l'invio interno usa `127.0.0.1` e la porta del processo. Sono lo stesso server. Nel dettaglio dell'ultimo giro si vede l'indirizzo interno.

URL valorizzato: un POST per record, e la casella di questo collegamento non riceve nulla, a meno che l'URL non sia proprio quello della casella.

«Esegui ora» con zero record nuovi risponde `sent: 0` e stato `ok`. Non è un errore.

## Pianificatore e canali

Ogni 30 secondi, le integrazioni con `schedule_minutes > 0` e `connection_id` valorizzato sono candidate. Se `last_run` è più recente di `schedule_minutes` minuti, si saltano. Il formato di `last_run` è `YYYY-MM-DD HH:MM:SS`. Un valore illeggibile fa fallire il ciclo del pianificatore, che stampa e riprova dopo 30 secondi. Non uccide il server.

Un webhook pianificato ogni 15 minuti non riceve dati da solo: il giro fa la stessa cosa di «Esegui ora», cioè segna «in attesa». La cadenza ha senso per database, CSV e HTTP.

Un'eccezione dentro `run_pipeline` viene stampata e l'integrazione al giro dopo è di nuovo candidata, perché `mark_run` ha comunque scritto `last_run` nel ramo di errore prima di rilanciare. Non c'è backoff oltre l'intervallo configurato.

Il lucchetto è globale. Due integrazioni scadute nello stesso controllo partono una dopo l'altra, non insieme. Se la prima tiene il lucchetto, la seconda riceve l'errore «un'esecuzione è già in corso», che viene scritto in `last_status` e fa slittare il prossimo tentativo di un intervallo intero.
