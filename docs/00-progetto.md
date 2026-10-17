# Nesso

Nesso è il nome del progetto. È il legame fra EspoCRM e un sistema esterno: il canale, la scheda e i campi si configurano, e il passaggio avviene solo con le API di Espo.

Repository: https://github.com/nessocrm/nessocrm. Dominio, tutto attaccato: `nessocrm`.

Lo stack di prova è il compose `nessocrm`, in questa cartella. Espo di prova: http://localhost:8088. Nesso: http://localhost:8091.

Questo documento dice che cosa è già fatto e che cosa manca. Il comportamento della prima versione è nel [manuale](index.md). La fotografia del backup di produzione resta fuori da questo repo. Non è il backlog di Nesso.

## Prima versione, 17 ottobre 2026

È una prima versione. Fa il passaggio universale nei limiti scritti sotto. Non copre ogni sistema e ha i difetti elencati più avanti.

### Che cosa fa

Nesso sta in mezzo. Da un lato Espo, dall'altro un sistema esterno. Nessuno dei due scrive nelle tabelle dell'altro.

Un **collegamento** è il canale. Un'**integrazione** è la regola: quale collegamento, quale scheda, quali campi, quale colonna identifica il record, ogni quanto.

| Canale | Verso | Comportamento già in funzione |
|---|---|---|
| Webhook | entra in Espo | Indirizzo con token. Corpo oggetto, elenco, oppure `{records:[]}` |
| Database | entra in Espo | Una SELECT su MySQL o MariaDB, al massimo 500 righe. Il motore non scrive su quel database |
| File CSV | entra in Espo | Cartella `scambio/{id}`. Dopo la lettura il file va in `elaborati/` |
| HTTP | esce da Espo | POST JSON verso un indirizzo, oppure verso la casella locale se l'indirizzo è vuoto |

La scheda non è scritta nel codice. Nesso legge il metadata di Espo e propone le schede con tab e i campi scrivibili.

La scheda si può anche creare da Nesso, durante una integrazione nuova, al passo «Scheda di Espo», voce «Una scheda che ancora non esiste». Espo antepone `C` al nome: Consegna diventa `CConsegna`. Su quella scheda nascono la chiave esterna, i campi abbinati (testo) e il lookup verso un'altra scheda. Il lookup è many-to-one: il valore esterno viene cercato sull'altra scheda e, se il record c'è, l'id viene scritto sul record nuovo. Se non c'è, la riga non entra.

L'identità di un record in ingresso è `{id integrazione}:{valore esterno}`. Sulle schede standard il campo è `cExternalKey`. Sulle schede create da Nesso è `externalKey`. Lo stesso valore, con gli stessi campi, non richiama Espo: resta `invariato`. Se i campi cambiano, Nesso fa `PUT` sullo stesso record.

L'uscita ricorda l'ultimo `modifiedAt` e al giro dopo manda solo i record successivi, al massimo 50.

La cadenza è manuale, 5 minuti, 15 minuti o un'ora. L'interfaccia ha il menu laterale di Espo: Inizio, Collegamenti, Integrazioni, Attività, e la voce EspoCRM. La creazione di un'integrazione è in quattro passi. Nell'abbinamento si scrive un campo, si collega una scheda, si collegano più record, oppure si appende un'attività a una scheda.

Ogni chiamata verso Espo usa le API HTTP, header `Espo-Authorization`. Creare una scheda, creare un campo, creare un lookup, leggere e scrivere un record: sono tutte API. Nesso non esegue SQL sulle tabelle di Espo.

L'istanza locale è l'immagine pubblica `espocrm/espocrm:10.0`, installata vuota. Non è il backup. Il backup di produzione è Espo 10.0.8 con l'Advanced Pack. Quel pacchetto non è nell'immagine pubblica. Sulla prova il compose lo monta da `local/advanced-pack/`, cartella ignorata da git.

### Difetti noti di questa versione

- La creazione della scheda è dentro il passo 2 dell'integrazione. Non ha una schermata propria.
- Un invio in uscita che fallisce a metà non torna indietro: il cursore è già avanzato e quei record non vengono ritentati.
- Se Espo non restituisce `modifiedAt`, il cursore non si muove e il giro dopo rimanda gli stessi record.
- Nel CSV e nel webhook, la prima riga che fallisce ferma le successive. Nel database le righe dopo vengono tentate.
- Gira una esecuzione alla volta. La seconda riceve «un'esecuzione è già in corso».
- La password del database esterno è in chiaro nel file SQLite del volume locale.
- La porta 8091 non ha login. Chi la raggiunge configura e lancia i giri.
- Il pianificatore non è stato osservato per un ciclo intero da 15 minuti.
- Non ci sono test automatici.

## Evolutiva, non ancora fatta

Ogni voce è lavoro da fare. Nessuna di queste è nel codice di oggi.

### Posta del motore

Nesso avrà un proprio SMTP, e una casella IMAP. Serve al motore, non sostituisce la posta in uscita di Espo: quella resta in Espo, perché è Espo a mandare le email del CRM.

Usi già chiari:

- Avvisare quando un giro fallisce o quando una riga viene scartata, a un indirizzo configurato.
- Mandare il riepilogo di una giornata: create, aggiornate, invariate, scartate.
- Canale in uscita: un record che esce da Espo diventa un messaggio verso un destinatario indicato nell'abbinamento.
- Canale in ingresso: una casella riceve messaggi e ogni messaggio diventa un record, come già fa il webhook con un POST.
- Il testo del messaggio si compone dai campi abbinati. Mittente, risposta e oggetto sono configurabili per integrazione.

Da prevedere insieme: credenziali separate da quelle di Espo, prova di invio dalla schermata, e il fatto che un messaggio non inviato resti in coda e venga ritentato.

### Schede e campi

- Una schermata Entità, fuori dal percorso dell'integrazione: creare, rivedere e aggiungere campi senza dover rifare i quattro passi.
- Tipi oltre il testo: numero, data, data e ora, sì/no, elenco, valuta, email, telefono, url.
- Valori di un elenco: la colonna esterna «aperto» diventa il valore che Espo si aspetta.
- Più lookup verso la stessa scheda, con un nome scelto da chi configura. Il collegamento di più record e l'attività appesa a una scheda ci sono già nel passo di abbinamento.
- Campi obbligatori di Espo dichiarati prima del salvataggio, così il giro non fallisce a metà.
- Modificare una scheda già creata: aggiungere un campo, cambiare un'etichetta.

### Canali

- SFTP e FTPS, in lettura e in deposito.
- Postgres, SQL Server e Oracle, sempre con il vincolo di una sola lettura finché non esiste una politica di scrittura.
- Scrittura di ritorno sul sistema di origine, esplicita e disattivata se non si sceglie.
- HTTP in ingresso e in uscita con API key, OAuth e header propri. Oggi il token sta solo nell'URL del webhook, e l'uscita HTTP parte senza firma.
- Coda: se il sistema esterno non risponde, il record resta e viene ritentato.
- Allegati e file collegati al record.

### Regole di passaggio

- Politica sul duplicato, scelta per integrazione: scarta, aggiorna, oppure collega al record già presente.
- Trasformazioni nel modulo: valore fisso, prima parola, resto del testo, data da un formato a un altro. Oggi il modulo salva solo la copia.
- Prova a secco: mostra che cosa scriverebbe, senza chiamare Espo.
- Modifica di un collegamento e di un'integrazione dalla schermata, senza cancellare e ricreare.
- Cancellazione: se il record sparisce dal sistema esterno, decidere se chiuderlo su Espo o lasciarlo.
- Paginazione dell'uscita oltre i 50 record per giro, senza perdere il cursore quando un invio fallisce.

### Affidabilità e accesso

- Login di Nesso, ruoli, e un utente delle API diverso dall'admin di Espo.
- Segreti fuori dal SQLite in chiaro.
- Giornale degli scarti, riga per riga, visibile in Attività. Oggi lo scarto del database sta solo nel dettaglio dell'ultimo giro.
- Ripetizione del giro con backoff, e uno scarto che non blocca l'intervallo successivo.
- Test automatici sui quattro canali, sulla creazione scheda e sul lookup.
- Pubblicare l'Advanced Pack. Sulla prova locale il compose lo monta già da `local/advanced-pack/`, fuori da git. L'immagine pubblica non lo contiene. I dati di produzione restano fuori.

### Quello che resta documentazione del backup

I quattro flussi del backup (sito, file notturni, anagrafiche, commesse) non diventano codice dentro Nesso. Diventano configurazioni: un collegamento e un'integrazione per ciascuno, quando i canali che servono esistono. Quel piano resta nel backup, fuori da questo repo. Non è l'elenco delle funzioni mancanti di Nesso.
