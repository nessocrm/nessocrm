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

Le preferenze dell'admin hanno la dashboard Direzione: pipeline aperto per fase, ticket aperti per priorità, offerte da chiudere, visite in agenda. Sono report dell'Advanced Pack.

## Dove sono i dati

Il database `meridia_erp` nasce sullo stesso MariaDB della prova. Lo schema e le righe sono in `demo/meridia.sql`. I file sono in `demo/csv/`. Il corpo del sito è in `demo/webhook/richieste-sito.json`.

Per rifare la demo da zero si fermano i contenitori e si cancellano i volumi di questo compose, poi si rilancia. I volumi tengono Espo e la configurazione già caricata.
