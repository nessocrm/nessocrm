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
| Database | entra in Espo | Una SELECT su MySQL o MariaDB, letta a pagine da 200 fino in fondo. Il motore non scrive su quel database |
| File CSV | entra in Espo | Cartella `scambio/{id}`, UTF-8, virgola o punto e virgola. Dopo il giro il file va in `elaborati/`, anche se qualche riga è scartata. Se manca una colonna obbligatoria il file resta dov'è |
| HTTP | esce da Espo | POST JSON verso un indirizzo, oppure verso la casella locale. Si può aggiungere Bearer, utente e password, o un'intestazione |

La scheda non è scritta nel codice. Nesso legge il metadata di Espo e propone le schede con tab e i campi scrivibili.

La scheda si crea dalla schermata Schede, con singolare e plurale, oppure ancora dal passo «Scheda di Espo» di un'integrazione nuova. Espo antepone `C` al nome: Consegna diventa `CConsegna`. Su quella scheda nascono la chiave esterna e i campi abbinati. Dalla schermata Schede il campo nuovo ha il tipo vero. Dal passo dell'integrazione i campi abbinati nascono ancora come testo. Il lookup verso un'altra scheda è many-to-one. Il lookup è many-to-one. Se il record collegato non c'è, si sceglie: scartare la riga, lasciare il legame vuoto, oppure creare il record.

L'identità di un record in ingresso è `{id integrazione}:{valore esterno}`. Sulle schede standard il campo è `cExternalKey`. Sulle schede create da Nesso è `externalKey`. Sulle schede che Espo non lascia personalizzare (team, cartelle, categorie, ruoli, modelli email) la chiave sta solo nella tabella `chiave` del motore. Lo stesso valore, con gli stessi campi, non richiama Espo: resta `invariato`. Se i campi cambiano, Nesso fa `PUT` sullo stesso record.

L'uscita ricorda l'ultimo `modifiedAt` insieme all'id Espo. Un giro legge a pagine da 50, senza saltare i record che hanno lo stesso istante. Il cursore dell'invio HTTP avanza solo dopo i POST riusciti: quello che non è partito esce al giro dopo.

La cadenza è manuale, 5 minuti, 15 minuti, un'ora, oppure un orario fisso. Un'integrazione può dichiarare quale altra deve partire prima. Si può mettere in pausa: il pianificatore e il webhook la saltano, «Esegui ora» no. Un interruttore ferma ogni scrittura verso Espo, e una modalità lettura fa lo stesso per una integrazione. L'interfaccia ha il menu laterale di Espo. Si crea e si modifica un'integrazione in quattro passi. Nell'abbinamento si copia un campo, si prende la prima parola o il resto, si scrive un valore fisso, si mappa un elenco, si collega una scheda, più record, un'attività, oppure si dice il team e la persona. Ogni campo ha un padrone. Un telefono italiano viene messo in forma `+39`. Una data si legge in tre formati. La prova a secco mostra le prime righe senza scrivere su Espo. L'anteprima conta il giro intero. Attività elenca anche le righe scartate, i contrasti e gli ultimi giri. La configurazione si scarica e si ricarica, senza le password.

Ogni chiamata verso Espo usa le API HTTP, header `Espo-Authorization`. Creare una scheda, creare un campo, creare un lookup, leggere e scrivere un record: sono tutte API. Nesso non esegue SQL sulle tabelle di Espo.

L'istanza locale è l'immagine pubblica `espocrm/espocrm:10.0`, installata vuota. Non è il backup. Il backup di produzione è Espo 10.0.8 con l'Advanced Pack. Quel pacchetto non è nell'immagine pubblica. Sulla prova il compose lo monta da `local/advanced-pack/`, cartella ignorata da git.

### Difetti noti di questa versione

- Se Espo non restituisce `modifiedAt`, il cursore di uscita non si muove e il giro dopo rimanda gli stessi record.
- `/api/pull` scrive il sink e avanza il cursore, perché lì la consegna è la lettura stessa. L'invio HTTP no: il cursore si muove solo dopo i POST riusciti.
- Gira una esecuzione alla volta. La seconda riceve «un'esecuzione è già in corso».
- La password del database esterno è in chiaro nel file SQLite del volume locale.
- La porta 8091 non ha login. Chi la raggiunge configura e lancia i giri.
- Il pianificatore non è stato osservato per un ciclo intero da 15 minuti.
- Non ci sono test automatici.

## Archiviate

Chiuse. Non sono più lavoro.

### Tubo, 18 ottobre 2026

Giornale degli scarti. CSV e webhook che proseguono dopo una riga errata. CSV con punto e virgola, file spostato in `elaborati/` anche se qualche riga fallisce. Cursore in ingresso se si indica la colonna. Pagine in uscita. Cursore HTTP che avanza solo dopo l'invio riuscito. Un padre per integrazione. Lookup che può fallire, restare vuoto o creare il padre. Sul duplicato si scarta o si adotta. Trasformazioni, mappa valori, telefono `+39`. Prova a secco, modifica, pausa. Credenziali sull'uscita HTTP. Scarico e ricarico della configurazione. Chiave tenuta nel motore per le schede che Espo non lascia personalizzare (team, cartelle, categorie, ruoli, modelli email).

### Carico, 19 ottobre 2026

Padrone del campo, con svuotamento solo sui campi della sorgente e coda se il padrone è Espo. Anteprima del giro intero e diff delle righe pericolose. Conferma della prima chiusura. Interruttore di ogni scrittura. Modalità lettura. Storico dei valori e annullamento del giro. Partita IVA o codice fiscale già presente, e controllo di forma. Pagine in ingresso senza il tetto di 500. Orario fisso. Qualità prima di Espo: date, elenchi, campo nominato nell'errore. Il file si ferma se manca una colonna obbligatoria. Tre valori veri accanto all'abbinamento. Riepilogo del giro con create, aggiornate, chiuse e scartate. Regola di visibilità. Chiusura del record sparito, solo su una scheda che ha già uno stato e solo dopo la conferma la prima volta. I test stanno in `motore/test_carico.py` e `motore/test_giro.py`.

### Lingua e ricetta, 19 ottobre 2026

La pagina parla italiano o inglese. La scelta sta nel menu, chiave `nesso-lang`. Le frasi composte della home hanno una chiave, così la stessa percentuale si legge nella lingua scelta. Il manuale è in italiano e in inglese. Il giornale già scritto non si riscrive. Origine Nesso usa la lingua del giro; il pianificatore scrive in italiano. Nel passo di abbinamento, «Proponi l'abbinamento» legge i nomi delle colonne e non salva finché la persona non conferma. «Ricetta anagrafiche» prepara Account con i campi che un export di clienti ha già, e dice che non è un connettore certificato. I sinonimi sono un elenco per lingua. I test stanno in `motore/test_frasi.py`.

### Mattina, 19 ottobre 2026

In home, la percentuale di anagrafiche allineate e l'ora dell'ultimo giro riuscito sull'integrazione verso Account. Un giro già segnato `ok`, con righe invariate, conta anche se è stato eseguito prima che esistesse il campo dell'ultimo successo. Se il giro di oggi fallisce, non si mostra la percentuale e l'ora di ieri non viene presentata come oggi. Quadratura fra chiavi in sorgente e chiavi già in Espo, con lo scarto importi se c'è un campo valuta o decimale: è un controllo, non scrive. Per un file, un'ora entro cui è atteso: passato quel momento senza un giro riuscito la home è rossa, e un file già in `elaborati/` non viene riletto. Sulla scheda Espo, il campo Origine Nesso dice se l'ultimo aggiornamento è del gestionale o di una persona. I test delle quattro funzioni sono nelle classi `Mattina`, `QuadraturaNumeri`, `FileAtteso` e `Badge`.

### Prodotto e demo, 18 ottobre 2026

Schermata Schede: elenco, integrazioni che la toccano, scheda nuova, campo nuovo con tipo vero e obbligo. Il campo viene appeso al dettaglio e all'elenco.

Demo Gruppo Meridia caricata: anagrafiche, offerte in euro, contratti, commesse, fatture, ticket, visite, ruoli (Direzione compresa), team, utenti, cartelle, otto PDF collegati ad azienda e offerta, compiti, chiamate, articoli, lista fiera, campagna, modelli email. Chiara Fabbri legge i clienti del Nord-Est e non quelli della Lombardia. La home di direzione resta leggibile. Il capitolo «Stato della prova» è la fotografia del primo seme, non questo demo.

## Fuori dal prodotto

Non si costruiscono. Sono il confine.

- La posta del CRM resta in Espo. Nesso non la manda.
- Report e processi dell'Advanced Pack non si riscrivono e non si pubblicano. Il pacchetto resta in `local/advanced-pack/`, fuori da git. Nesso consegna record che quelli sanno leggere.
- Il demo è la prova, non un secondo prodotto. Non si inventano schede per far vedere movimento.
- Nesso ha sempre Espo da un lato. Non è un ponte fra due sistemi qualunque.
- Niente SQL sulle tabelle di Espo. Niente dump di produzione.
- Gli utenti di Espo non nascono da un'anagrafica. Un giro persone, se servirà, sta spento finché non lo si accende.
- Chiudere un record sparito dalla sorgente lo lascia nello storico. Il diritto all'oblio è un altro gesto, e non è questa chiusura.
- I quattro flussi del backup (sito, file notturni, anagrafiche, commesse) non diventano codice. Diventano configurazioni quando i canali esistono. Il piano resta nel backup, fuori da questo repo.

## Decisioni chiuse

Il codice aperto le rispetta.

- Nesso governa le schede.
- La visibilità è una regola: «questa riga è del team Vendite, assegnata a questa persona».
- Se il record sparisce dalla sorgente, su Espo si chiude e resta nello storico.
- Di default vince la sorgente, anche se la cella arriva vuota. Il campo può avere un altro padrone: lo dice la voce aperta «Padrone del campo».
- La scrittura di ritorno verso il gestionale resta spenta finché non la si sceglie.

## Aperte

Una voce sta qui finché non è nel motore. Quelle già chiuse non si ripetono. Le funzioni pensate per convincere un'azienda, distinte da questo elenco tecnico, stanno in [Adozione](15-adozione.md).

### Dati e visibilità

- Chiave di più colonne. Oggi dalla pagina è una sola.
- Più padri: «prima le aziende e le sedi, poi la rubrica». Oggi se ne indica uno solo.
- Coda di ritento con attesa crescente, per l'uscita muta e per la riga il cui padre non è ancora arrivato.
- In uscita il collegamento parte come chiave esterna, non come id Espo.
- Cambiare l'etichetta di un campo già creato.
- Più collegamenti verso la stessa scheda, con il nome scelto. Se ne esiste uno, Nesso lo riusa. Se ne esistono due, si blocca o ne crea un altro senza chiedere il nome.
- Layout: dettaglio, elenco, kanban. Oggi il campo nuovo viene appeso in fondo.
- Obbligatori controllati prima del giro, con il messaggio sul campo.
- Valuta e fuso in lettura. Il telefono italiano è già `+39`. Le offerte della prova sono già in euro.
- Attività nata insieme al record: compito, chiamata, riunione, con data e assegnatario.
- Nota nello storico, così si vede da dove è arrivata la riga.
- Portale: un contatto che entra da fuori ha un percorso.

### Uso

- Login, e due gesti: chi cambia l'integrazione, chi la lancia e legge l'esito.
- Nesso parla con Espo con un utente suo, non con l'admin.
- Prossimo giro, ultimo successo, ultimo errore, da quanto tace.
- Avviso quando un giro fallisce o tace troppo. Il canale previsto è la posta del motore, sotto.
- Ripetere una sola riga scartata, senza rilanciare tutto il file.
- Errore col nome del campo.
- Prova a secco del webhook: incollare un esempio. Oggi risponde che non ha righe.
- Due ambienti, prova e esercizio, e il passaggio della configurazione con le password messe a mano.
- Storia della regola: chi ha cambiato l'abbinamento, e tornare alla versione di prima.
- Segreti fuori dal SQLite in chiaro.
- Più esecuzioni insieme, o almeno una per canale. Dopo un errore il pianificatore aspetta ancora l'intervallo intero.
- Test automatici sui quattro canali, sulla scheda nuova e sul lookup.

### Canali

- SFTP e FTPS, in lettura e in deposito. Excel, non solo CSV.
- Postgres, SQL Server, Oracle. TLS e tunnel, anche su MySQL.
- HTTP firmato in ingresso. OAuth in uscita.
- Scrittura di ritorno sulla sorgente, spenta finché non si accende.
- Il documento come canale, con cartella e visibilità. Il percorso di un file locale si può già caricare su un campo file.
- La casella locale consegna il JSON a un'altra integrazione. Oggi lo accumula e si ferma.
- Posta del motore, SMTP e IMAP, separata da quella di Espo: avviso, riepilogo della giornata, messaggio in uscita composto dai campi, messaggio in ingresso che diventa un record. Credenziali proprie, prova di invio, coda se l'invio fallisce.

### In che ordine

1. Login, utente Espo dedicato, avviso.
2. I canali, a partire da quello che il carico vero non riesce a leggere.
