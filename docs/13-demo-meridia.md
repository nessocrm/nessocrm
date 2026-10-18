# Demo Gruppo Meridia

Gruppo Meridia è un'impresa industriale inventata. Progetta, installa e mantiene impianti di automazione per fabbriche. Ha clienti produttori, una rete di partner e il lavoro che va dall'anagrafica fino all'incasso e all'assistenza. Non è un cliente reale e non usa dati di un backup.

`docker compose up -d --build` installa Espo vuoto e, a Espo pronto, carica questa demo. Le integrazioni di database e l'uscita verso il portale si ripetono ogni 15 minuti. Le richieste da file e dal sito partono una volta, all'avvio.

Espo: http://localhost:8088 (`admin` / `locale-admin`). Nesso: http://localhost:8091.

## I processi

| Processo | Da dove arriva | Scheda |
|---|---|---|
| Anagrafiche clienti | ERP, database | Account, tipo Customer |
| Fornitori e partner | ERP, database | Account, tipo Partner |
| Rubrica di chi decide e di chi lavora in stabilimento | ERP, database | Contatto, collegato all'azienda |
| Sedi e reparti | ERP, database | Sede, collegata all'azienda |
| Richieste da fiera, telefono, email, partner | File CSV | Lead |
| Richieste dal configuratore del sito | Webhook | Lead |
| Offerte in corso | Vendite, database | Opportunità (`COfferta`, tipo Base Plus), collegata ad azienda e contatto |
| Contratti quadro | ERP, database | Contratto, collegato ad azienda e offerta |
| Commesse di lavoro | Gestione lavori, database | Commessa, collegata ad azienda e contratto |
| Interventi dei tecnici | Pianificazione, database | Intervento, collegato a commessa e contatto |
| Fatture emesse, pagate, scadute | Amministrazione, database | Fattura, collegata ad azienda e commessa |
| Ticket di assistenza | Helpdesk, database | Caso, collegato ad azienda e contatto |
| Visite e sopralluoghi | Agenda, file CSV | Riunione, collegata all'azienda |
| Offerte pubblicate al portale dei partner | Uscita HTTP | la stessa Opportunità, verso la casella locale |

La contabilità generale, il magazzino fisico e le buste paga restano fuori dal CRM. In Meridia si vede il commerciale, il contratto, il lavoro, la fattura e il guasto.

## Opportunità Base Plus

Le offerte non restano sulla scheda standard Opportunity. All'avvio `demo/promuovi_offerta.py` crea `COfferta`, tipo Base Plus, con etichetta Opportunità. Ha fase, importo, probabilità, chiusura, azienda, contatto e documenti, e i pannelli Attività, Storico e Compiti. I contratti puntano a questa scheda. La voce Opportunity sparisce dal menu.

## Home di direzione

Le preferenze dell'admin hanno la dashboard Direzione: pipeline aperto per fase, ticket aperti per priorità, offerte da chiudere, visite in agenda. Sono report dell'Advanced Pack. Gli importi delle offerte sono in euro.

## Organizzazione

Dopo i processi, lo stesso avvio carica team, persone e documenti. I ruoli sono Vendite, Assistenza, Amministrazione e Direzione. Direzione legge tutto; sugli utenti può modificare solo il proprio, perché Espo non ammette «modifica tutti» su User.

| Team | Chi ci entra | Vede |
|---|---|---|
| Vendite Nord-Est | Chiara Fabbri | Clienti e offerte del Nord-Est |
| Vendite Lombardia e Sud | Marco Pellizzari | Clienti e offerte di Lombardia |
| Assistenza impianti | Elena Sartori | Ticket, interventi, articoli |
| Amministrazione | Davide Rinaldi | Contratti e fatture del proprio team |
| Direzione | Laura Merli, e anche l'admin | L'insieme |

Le cinque persone entrano in Espo con password `locale-utente`. Chiara non apre un cliente della Lombardia: la lettura di quel record restituisce zero righe.

Gli otto PDF stanno in `demo/documenti/`. Finiscono su Document, in una cartella (Offerte, Contratti, Schede tecniche), collegati all'azienda e, quando c'è, all'opportunità. Ci sono anche compiti sulle offerte e sui ticket, quattro chiamate, tre articoli di conoscenza, la lista inviti MECSPE e la campagna omonima, due modelli email. I contatti della lista si agganciano dopo la creazione: Espo rifiuta l'elenco contatti nel corpo della lista.

Team, cartelle, categorie e modelli email non accettano un campo chiave. La chiave di quei record sta nella tabella `chiave` del motore.

## Dove sono i dati

Il database `meridia_erp` nasce sullo stesso MariaDB della prova. Lo schema e le righe dei processi sono in `demo/meridia.sql`. Team, utenti e documenti sono in `demo/meridia-organizzazione.sql`. I file CSV sono in `demo/csv/`. I PDF sono in `demo/documenti/`. Il corpo del sito è in `demo/webhook/richieste-sito.json`.

Per rifare la demo da zero si fermano i contenitori e si cancellano i volumi di questo compose, poi si rilancia. I volumi tengono Espo e la configurazione già caricata.
