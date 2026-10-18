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
| File CSV | entra in Espo | Cartella `scambio/{id}`, UTF-8, virgola o punto e virgola. Dopo il giro il file va in `elaborati/`, anche se qualche riga è scartata |
| HTTP | esce da Espo | POST JSON verso un indirizzo, oppure verso la casella locale. Si può aggiungere Bearer, utente e password, o un'intestazione |

La scheda non è scritta nel codice. Nesso legge il metadata di Espo e propone le schede con tab e i campi scrivibili.

La scheda si può anche creare da Nesso, durante una integrazione nuova, al passo «Scheda di Espo», voce «Una scheda che ancora non esiste». Espo antepone `C` al nome: Consegna diventa `CConsegna`. Su quella scheda nascono la chiave esterna, i campi abbinati (testo) e il lookup verso un'altra scheda. Il lookup è many-to-one. Se il record collegato non c'è, si sceglie: scartare la riga, lasciare il legame vuoto, oppure creare il record.

L'identità di un record in ingresso è `{id integrazione}:{valore esterno}`. Sulle schede standard il campo è `cExternalKey`. Sulle schede create da Nesso è `externalKey`. Sulle schede che Espo non lascia personalizzare (team, cartelle, categorie, ruoli, modelli email) la chiave sta solo nella tabella `chiave` del motore. Lo stesso valore, con gli stessi campi, non richiama Espo: resta `invariato`. Se i campi cambiano, Nesso fa `PUT` sullo stesso record.

L'uscita ricorda l'ultimo `modifiedAt` insieme all'id Espo. Un giro legge a pagine da 50, senza saltare i record che hanno lo stesso istante. Il cursore dell'invio HTTP avanza solo dopo i POST riusciti: quello che non è partito esce al giro dopo.

La cadenza è manuale, 5 minuti, 15 minuti o un'ora. Un'integrazione può dichiarare quale altra deve partire prima. Si può mettere in pausa: il pianificatore e il webhook la saltano, «Esegui ora» no. L'interfaccia ha il menu laterale di Espo. Si crea e si modifica un'integrazione in quattro passi. Nell'abbinamento si copia un campo, si prende la prima parola o il resto, si scrive un valore fisso, si mappa un elenco, si collega una scheda, più record, oppure un'attività. Un telefono italiano viene messo in forma `+39`. La prova a secco mostra le prime righe senza scrivere su Espo. Attività elenca anche le righe scartate e gli ultimi giri. La configurazione si scarica e si ricarica, senza le password.

Ogni chiamata verso Espo usa le API HTTP, header `Espo-Authorization`. Creare una scheda, creare un campo, creare un lookup, leggere e scrivere un record: sono tutte API. Nesso non esegue SQL sulle tabelle di Espo.

L'istanza locale è l'immagine pubblica `espocrm/espocrm:10.0`, installata vuota. Non è il backup. Il backup di produzione è Espo 10.0.8 con l'Advanced Pack. Quel pacchetto non è nell'immagine pubblica. Sulla prova il compose lo monta da `local/advanced-pack/`, cartella ignorata da git.

### Difetti noti di questa versione

- La creazione della scheda è dentro il passo 2 dell'integrazione. Non ha una schermata propria.
- Se Espo non restituisce `modifiedAt`, il cursore di uscita non si muove e il giro dopo rimanda gli stessi record.
- `/api/pull` scrive il sink e avanza il cursore, perché lì la consegna è la lettura stessa. L'invio HTTP no: il cursore si muove solo dopo i POST riusciti.
- Gira una esecuzione alla volta. La seconda riceve «un'esecuzione è già in corso».
- La password del database esterno è in chiaro nel file SQLite del volume locale.
- La porta 8091 non ha login. Chi la raggiunge configura e lancia i giri.
- Il pianificatore non è stato osservato per un ciclo intero da 15 minuti.
- Non ci sono test automatici.

## Evolutiva, non ancora fatta

Ogni voce è lavoro da fare. Quello che il 18 ottobre è entrato nel motore non è più in questo elenco: giornale degli scarti, CSV e webhook che proseguono, cursore in ingresso se si indica la colonna, pagine in uscita, ordine fra integrazioni, lookup che può restare vuoto o creare il padre, trasformazioni e mappa valori in pagina, telefono in forma internazionale, prova a secco, modifica, pausa, credenziali sull'uscita HTTP, scarico della configurazione.

Questo elenco è il tubo. Non basta a rendere l'app utile. Il giudizio su che cosa manca, e che cosa va deciso prima di costruirlo, sta più sotto, in «Per diventare utile».

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
- Data da un formato all'altro. La mappa dei valori di un elenco c'è già nel passo di abbinamento.
- Più lookup verso la stessa scheda, con un nome scelto da chi configura. Il collegamento di più record e l'attività appesa a una scheda ci sono già nel passo di abbinamento.
- Campi obbligatori di Espo dichiarati prima del salvataggio, così il giro non fallisce a metà.
- Modificare una scheda già creata: aggiungere un campo, cambiare un'etichetta.

### Canali

- SFTP e FTPS, in lettura e in deposito.
- Postgres, SQL Server e Oracle, sempre con il vincolo di una sola lettura finché non esiste una politica di scrittura.
- Scrittura di ritorno sul sistema di origine, esplicita e disattivata se non si sceglie.
- HTTP in ingresso firmato, e OAuth in uscita. L'uscita ha già Bearer, utente e password, e un'intestazione con nome e valore. Il webhook ha ancora solo il token nell'indirizzo.
- Coda: se il sistema esterno non risponde, il record resta e viene ritentato.
- Allegati e file collegati al record.

### Regole di passaggio

- Cancellazione: se il record sparisce dal sistema esterno, decidere se chiuderlo su Espo o lasciarlo. Sul duplicato, scartare o aggiornare il record già presente, è già una scelta dell'integrazione.

### Affidabilità e accesso

- Login di Nesso, ruoli, e un utente delle API diverso dall'admin di Espo.
- Segreti fuori dal SQLite in chiaro.
- Ripetizione del giro con backoff. Lo scarto di una riga non blocca più le altre, ed è visibile in Attività. Il pianificatore, dopo un errore, aspetta ancora l'intervallo intero.
- Test automatici sui quattro canali, sulla creazione scheda e sul lookup.
- Pubblicare l'Advanced Pack. Sulla prova locale il compose lo monta già da `local/advanced-pack/`, fuori da git. L'immagine pubblica non lo contiene. I dati di produzione restano fuori.

## Ancora aperto, dopo il 18 ottobre 2026

Il motore ora tiene il giornale della riga, non si ferma alla prima, pagina l'uscita e sposta il cursore solo dopo un invio riuscito. Restano questi buchi.

- Il database in ingresso diventa incrementale solo se si indica la colonna di variazione. Senza, rilegge fino a 500 righe. Il CSV non ha un cursore: a ogni giro legge i file presenti, poi li sposta.
- Ogni valore letto dal database è ancora una stringa. Una cella vuota non svuota il campo già pieno su Espo.
- La chiave dalla pagina è ancora una colonna sola. Un record sparito dalla sorgente resta su Espo.
- Il webhook è solo JSON, con il token nell'indirizzo. Non c'è firma del corpo. «Esegui ora» non manda un esempio.
- Il database esterno è solo MySQL o MariaDB, senza TLS né tunnel.
- La casella locale accumula il JSON e non lo consegna a un'altra integrazione.
- Una sola esecuzione alla volta. Due contenitori non si coordinano. Dopo un errore il pianificatore aspetta l'intervallo intero. Non c'è un avviso.
- I campi creati da Nesso sono testo. Numero, data, elenco e valuta si abbinano se la scheda li ha già.
- L'utente assegnato e i team non hanno una regola propria: si collegano come un lookup.
- L'uscita manda l'id Espo del collegamento, salvo che la mappa includa la chiave esterna.
- Posta, login, SFTP, altri database, OAuth e la politica di cancellazione restano nell'elenco sopra.

## Per diventare utile

Nesso oggi sposta una colonna in un campo. Una persona che apre Espo non ci vede la propria azienda, e una persona che apre Nesso non ci governa il CRM. Qui c'è quello che va valutato e poi costruito, oltre al tubo. Le voci già scritte sopra non si ripetono: si dice solo dove entrano.

### Decisioni chiuse

Sono le scelte di prodotto. Il codice che viene dopo le rispetta.

- Nesso governa le schede. Ha una schermata propria: si vede che cosa c'è in Espo, si crea una scheda, si aggiunge un campo con il tipo vero, l'etichetta e l'obbligo. I quattro passi dell'integrazione restano per il passaggio dei dati.
- La visibilità è una regola dell'integrazione: «questa riga è del team Vendite, assegnata a questa persona». Ancora da costruire. Oggi team e utente si collegano come un lookup.
- Se il record sparisce dalla sorgente, su Espo si chiude e resta nello storico. Ancora da costruire. Oggi non succede nulla.
- Se la sorgente e Espo hanno cambiato lo stesso campo, vince la sorgente, anche quando la cella arriva vuota. Ancora da costruire. Oggi vince chi scrive per ultimo e il vuoto viene ignorato.
- La posta del CRM resta in Espo. Nesso non la sostituisce. La posta di Nesso, se si fa, serve agli avvisi e a un canale in più.
- Report e processi dell'Advanced Pack non si riscrivono in Nesso. Nesso consegna un record che quelli sanno leggere. Il pacchetto resta fuori da git.
- Il demo è la prova che l'app serve, non un secondo prodotto. Non si inventano schede per far vedere movimento.

### Vedere l'azienda dentro Espo

- La schermata Schede c'è: elenco, integrazioni che la toccano, scheda nuova, campo nuovo con tipo vero (testo, testo lungo, numeri, data, data e ora, sì/no, elenco, valuta, email, telefono, indirizzo web) e obbligo. Manca cambiare l'etichetta di un campo già creato.
- Più collegamenti verso la stessa scheda, con il nome scelto da chi configura. Se ne esiste uno solo, Nesso lo riusa. Se ne esistono due, si blocca o ne crea un altro senza chiedere il nome.
- Layout: quali campi stanno in dettaglio, in elenco, in scheda kanban. Oggi un campo nuovo viene solo appeso in fondo.
- Obbligatori dichiarati prima del giro, con il messaggio sul campo, non a metà esecuzione.
- Chiave fatta di più colonne. Oggi dalla pagina è una sola. Il formato già salvato non si riscrive se la colonna non cambia, e questo va tenuto.
- Valuta e fuso. Le offerte della prova sono in euro. Una data «18/10/2026» e una «2026-10-18 10:00» non hanno ancora una regola di lettura. Il telefono italiano viene già messo in forma internazionale.

### Farla usare senza leggere il codice

- Login, e due gesti diversi: chi può cambiare un'integrazione, chi può solo lanciarla e leggere l'esito.
- Nesso parla con Espo con un utente suo, non con l'admin.
- Prossimo giro, ultimo successo, ultimo errore, da quanto tace. Oggi c'è l'ultima frase, tagliata a 500 caratteri, e il giornale dei giri.
- Avviso quando un giro fallisce o quando non parte da troppo tempo. La posta di Nesso, sopra, è il canale previsto.
- Ripetere una sola riga scartata, dopo la correzione, senza rilanciare tutto il file. Lo scarto c'è. Il tasto no.
- Errore detto col nome del campo. «Telefono non valido» e non il corpo HTTP di Espo.
- Prova a secco sul webhook: incollare un esempio. Oggi il webhook risponde che non ha righe.
- Due ambienti, prova e esercizio, e il passaggio della configurazione dall'uno all'altro con le password messe a mano. Lo scarico c'è. Gli ambienti no.
- Storia della regola: chi ha cambiato l'abbinamento, e tornare alla versione di prima.

### Tenere i dati veri

- Svuotare un campo quando la cella arriva vuota. Oggi il vuoto viene ignorato e il valore vecchio resta. Va legato alla decisione sul conflitto.
- Cancellare o chiudere, secondo la decisione sopra. Oggi sparire dalla sorgente non fa nulla.
- Ordine vero fra integrazioni. Oggi se ne indica una sola, «prima esegui questa». Una rubrica che dipende da aziende e da sedi non si può dire.
- Coda di ritento con attesa crescente, per l'uscita che non risponde e per la riga il cui padre non è ancora arrivato. Il lookup può già restare vuoto o creare il padre. Non riprova da solo più tardi.
- Più esecuzioni insieme, o almeno una per canale. Oggi la seconda riceve «un'esecuzione è già in corso». Due contenitori non si parlano.
- Il pianificatore, dopo un errore, non aspetta sempre lo stesso intervallo.
- Segreti fuori dal file SQLite in chiaro.
- Test automatici sui quattro canali, sulla scheda nuova e sul lookup. Il ciclo da 15 minuti del pianificatore non è stato osservato.

### Parlare con i sistemi che un'azienda ha davvero

Il tubo ha webhook JSON, una SELECT MySQL o MariaDB, un CSV, un POST in uscita. Manca il resto, già elencato nei canali e qui richiamato perché senza non è utile:

- File su SFTP e FTPS, in lettura e in deposito. Excel, non solo CSV.
- Postgres, SQL Server, Oracle. TLS e tunnel sul database, anche su MySQL.
- HTTP firmato in ingresso. OAuth in uscita. Il Bearer e l'intestazione ci sono già.
- Scrittura di ritorno sulla sorgente, spenta finché non si accende apposta.
- Allegati: il percorso di un file locale si può già caricare su un campo file. Manca il documento come canale, con cartella e visibilità.
- La casella locale che riceve un JSON e lo consegna a un'altra integrazione. Oggi lo accumula e si ferma.
- Posta in ingresso e in uscita del motore, nei limiti decisi sopra.

### Rispettare come Espo organizza il lavoro

- Regola «assegna a questo utente» e «visibile a questo team», non un lookup scoperto per caso.
- Portale: un contatto che deve entrare da fuori ha un percorso, non un campo dimenticato.
- Attività nata insieme al record: compito, chiamata, riunione, con data e assegnatario. Il legame «attività appesa a una scheda» c'è. Manca il gesto «quando entra questo cliente, crea questo compito».
- Nota nello storico, così chi apre la scheda vede da dove è arrivata.
- In uscita, il collegamento parte come chiave del sistema esterno, non come id interno di Espo. Oggi l'id parte, salvo che la mappa includa a mano la chiave.
- Lo stato e la fase sono valori di un elenco. La mappa c'è. Manca il controllo, prima del giro, che il valore esista davvero fra le opzioni di Espo.

### Dimostrare che serve

Il demo Gruppo Meridia carica anagrafiche, offerte, contratti, commesse, fatture, ticket, visite e l'organizzazione. All'avvio arrivano i ruoli Vendite, Assistenza, Amministrazione e Direzione, cinque team, cinque utenti, le cartelle, otto documenti con file, compiti, chiamate, articoli di conoscenza, la lista della fiera, la campagna e i modelli email. Chiara Fabbri, vendite Nord-Est, legge i clienti del suo team e non quelli della Lombardia. Il documento dell'offerta Brenta sta sull'azienda e sull'opportunità. Gli importi sono in euro. La home di direzione resta quella del capitolo sul demo.

Il capitolo «Stato della prova» è la fotografia del primo seme. Non è questo demo.

### In che ordine valutarle

1. Le decisioni in cima. Senza quelle, schede, visibilità e cancellazione si costruiscono due volte.
2. Il demo dell'organizzazione è caricato. Usarlo fa vedere che cosa l'app non sa ancora fare.
3. La schermata Schede c'è, con i tipi veri. Resta da cambiare l'etichetta di un campo già creato, e da mettere la visibilità come regola.
4. Visibilità e utente assegnato come regole, più la chiave esterna in uscita al posto dell'id.
5. Conflitto, svuotamento, cancellazione, ritento della riga.
6. Login, utente Espo dedicato, avviso, ambienti.
7. I canali che mancano, a partire da quello che il demo non riesce a mostrare.

### Quello che resta documentazione del backup

I quattro flussi del backup (sito, file notturni, anagrafiche, commesse) non diventano codice dentro Nesso. Diventano configurazioni: un collegamento e un'integrazione per ciascuno, quando i canali che servono esistono. Quel piano resta nel backup, fuori da questo repo. Non è l'elenco delle funzioni mancanti di Nesso.
