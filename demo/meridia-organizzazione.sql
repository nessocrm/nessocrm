USE meridia_erp;

CREATE TABLE IF NOT EXISTS team (
  codice varchar(40) NOT NULL PRIMARY KEY,
  nome varchar(120) NOT NULL,
  descrizione varchar(300)
);

CREATE TABLE IF NOT EXISTS cartelle (
  codice varchar(40) NOT NULL PRIMARY KEY,
  nome varchar(120) NOT NULL,
  descrizione varchar(300)
);

CREATE TABLE IF NOT EXISTS categorie (
  codice varchar(40) NOT NULL PRIMARY KEY,
  nome varchar(120) NOT NULL,
  descrizione varchar(300)
);

CREATE TABLE IF NOT EXISTS utenti (
  codice varchar(40) NOT NULL PRIMARY KEY,
  username varchar(80) NOT NULL,
  nome varchar(80) NOT NULL,
  cognome varchar(80) NOT NULL,
  email varchar(200) NOT NULL,
  titolo varchar(120),
  tipo varchar(40) NOT NULL,
  password varchar(80) NOT NULL,
  attivo varchar(8) NOT NULL,
  avviso varchar(8) NOT NULL,
  chiave_team varchar(180) NOT NULL,
  chiave_ruolo varchar(80) NOT NULL
);

CREATE TABLE IF NOT EXISTS documenti (
  codice varchar(40) NOT NULL PRIMARY KEY,
  nome varchar(200) NOT NULL,
  file varchar(200) NOT NULL,
  stato varchar(40) NOT NULL,
  tipo varchar(40),
  pubblicazione varchar(20) NOT NULL,
  descrizione varchar(500),
  chiave_cartella varchar(180) NOT NULL,
  chiave_account varchar(180),
  chiave_offerta varchar(180),
  chiave_team varchar(300) NOT NULL
);

CREATE TABLE IF NOT EXISTS compiti (
  codice varchar(40) NOT NULL PRIMARY KEY,
  nome varchar(200) NOT NULL,
  stato varchar(40) NOT NULL,
  priorita varchar(20) NOT NULL,
  scadenza varchar(30) NOT NULL,
  nota varchar(500),
  tipo_padre varchar(40) NOT NULL,
  chiave_padre varchar(180) NOT NULL,
  chiave_utente varchar(180) NOT NULL,
  chiave_team varchar(300) NOT NULL
);

CREATE TABLE IF NOT EXISTS chiamate (
  codice varchar(40) NOT NULL PRIMARY KEY,
  nome varchar(200) NOT NULL,
  stato varchar(40) NOT NULL,
  inizio varchar(30) NOT NULL,
  fine varchar(30) NOT NULL,
  direzione varchar(20) NOT NULL,
  nota varchar(500),
  chiave_account varchar(180) NOT NULL,
  chiave_contatto varchar(180) NOT NULL,
  chiave_utente varchar(180) NOT NULL,
  chiave_team varchar(300) NOT NULL
);

CREATE TABLE IF NOT EXISTS articoli (
  codice varchar(40) NOT NULL PRIMARY KEY,
  nome varchar(200) NOT NULL,
  stato varchar(40) NOT NULL,
  corpo text NOT NULL,
  chiave_categoria varchar(180) NOT NULL,
  chiave_team varchar(300) NOT NULL
);

CREATE TABLE IF NOT EXISTS liste (
  codice varchar(40) NOT NULL PRIMARY KEY,
  nome varchar(200) NOT NULL,
  descrizione varchar(300),
  chiave_contatti varchar(800) NOT NULL,
  chiave_team varchar(300) NOT NULL
);

CREATE TABLE IF NOT EXISTS campagne (
  codice varchar(40) NOT NULL PRIMARY KEY,
  nome varchar(200) NOT NULL,
  stato varchar(40) NOT NULL,
  tipo varchar(40) NOT NULL,
  inizio varchar(20) NOT NULL,
  fine varchar(20) NOT NULL,
  nota varchar(300),
  chiave_lista varchar(180) NOT NULL,
  chiave_team varchar(300) NOT NULL
);

CREATE TABLE IF NOT EXISTS modelli (
  codice varchar(40) NOT NULL PRIMARY KEY,
  nome varchar(200) NOT NULL,
  oggetto varchar(200) NOT NULL,
  corpo text NOT NULL,
  html varchar(8) NOT NULL,
  stato varchar(40) NOT NULL
);

INSERT IGNORE INTO team VALUES
('TEAM-VNE','Vendite Nord-Est','Clienti di Veneto, Friuli, Trentino e Adriatico.'),
('TEAM-LOM','Vendite Lombardia e Sud','Clienti di Lombardia, Emilia di confine e Sud.'),
('TEAM-ASS','Assistenza impianti','Tecnici di campo, ticket e commesse.'),
('TEAM-AMM','Amministrazione','Contratti e fatture.'),
('TEAM-DIR','Direzione','Vede l''insieme delle trattative e dei lavori.');

INSERT IGNORE INTO cartelle VALUES
('FLD-OFF','Offerte','Testi inviati al cliente.'),
('FLD-CON','Contratti','Contratti quadro e condizioni.'),
('FLD-TEC','Schede tecniche','Manuali e rilievi di impianto.');

INSERT IGNORE INTO categorie VALUES
('CAT-ASS','Assistenza sul campo','Procedure per il tecnico in stabilimento.'),
('CAT-SIC','Sicurezza macchine','ATEX, fermate e accessi.');

INSERT IGNORE INTO utenti VALUES
('USR-chiara','chiara.fabbri','Chiara','Fabbri','chiara.fabbri@meridia.example.test','Responsabile vendite Nord-Est','regular','locale-utente','1','0','team-di-visibilita:TEAM-VNE','Vendite'),
('USR-marco','marco.pellizzari','Marco','Pellizzari','marco.pellizzari@meridia.example.test','Responsabile vendite Lombardia','regular','locale-utente','1','0','team-di-visibilita:TEAM-LOM','Vendite'),
('USR-elena','elena.sartori','Elena','Sartori','elena.sartori@meridia.example.test','Coordinatrice assistenza','regular','locale-utente','1','0','team-di-visibilita:TEAM-ASS','Assistenza'),
('USR-davide','davide.rinaldi','Davide','Rinaldi','davide.rinaldi@meridia.example.test','Amministrazione clienti','regular','locale-utente','1','0','team-di-visibilita:TEAM-AMM','Amministrazione'),
('USR-laura','laura.merli','Laura','Merli','laura.merli@meridia.example.test','Direttore operations','regular','locale-utente','1','0','team-di-visibilita:TEAM-DIR','Direzione');

INSERT IGNORE INTO documenti VALUES
('DOC-1','Offerta revamping linea Brenta','documenti/offerta-brenta.pdf','Active',NULL,'2026-10-02','Revisione inviata agli acquisti di Officine Brenta.','cartelle-documenti:FLD-OFF','anagrafiche-clienti-erp:CLI-4100','offerte-commerciali:OFF-700','team-di-visibilita:TEAM-VNE,team-di-visibilita:TEAM-DIR'),
('DOC-2','Offerta quadro ATEX Isarco','documenti/offerta-atex.pdf','Active',NULL,'2026-09-12','Offerta chiusa, diventata contratto.','cartelle-documenti:FLD-OFF','anagrafiche-clienti-erp:CLI-4106','offerte-commerciali:OFF-706','team-di-visibilita:TEAM-VNE,team-di-visibilita:TEAM-DIR'),
('DOC-3','Contratto full service cartiera','documenti/contratto-cartiera.pdf','Active','Contract','2026-01-08','Testo del contratto 2026-2028.','cartelle-documenti:FLD-CON','anagrafiche-clienti-erp:CLI-4101',NULL,'team-di-visibilita:TEAM-VNE,team-di-visibilita:TEAM-AMM,team-di-visibilita:TEAM-DIR'),
('DOC-4','Condizioni generali di fornitura','documenti/condizioni-generali.pdf','Active','Contract','2026-01-01','Condizioni allegate a ogni offerta.','cartelle-documenti:FLD-CON',NULL,NULL,'team-di-visibilita:TEAM-VNE,team-di-visibilita:TEAM-LOM,team-di-visibilita:TEAM-AMM,team-di-visibilita:TEAM-DIR'),
('DOC-5','Manuale quadro ATEX','documenti/manuale-atex.pdf','Active',NULL,'2026-10-10','Revisione in italiano chiesta dall''HSE.','cartelle-documenti:FLD-TEC','anagrafiche-clienti-erp:CLI-4106',NULL,'team-di-visibilita:TEAM-ASS,team-di-visibilita:TEAM-DIR'),
('DOC-6','Scheda riduttore linea pasta','documenti/scheda-riduttore.pdf','Active',NULL,'2026-10-16','Rilievo dopo l''allarme vibrazione di Sacile.','cartelle-documenti:FLD-TEC','anagrafiche-clienti-erp:CLI-4101',NULL,'team-di-visibilita:TEAM-ASS,team-di-visibilita:TEAM-DIR'),
('DOC-7','Verbale rilievo cogeneratore','documenti/verbale-garda.pdf','Active',NULL,'2026-10-14','Misure prese in centrale a Brescia.','cartelle-documenti:FLD-TEC','anagrafiche-clienti-erp:CLI-4107','offerte-commerciali:OFF-707','team-di-visibilita:TEAM-LOM,team-di-visibilita:TEAM-ASS,team-di-visibilita:TEAM-DIR'),
('DOC-8','Copia fattura 2026/118','documenti/fattura-118.pdf','Active',NULL,'2026-10-15','Acconto ATEX emesso a ottobre.','cartelle-documenti:FLD-CON','anagrafiche-clienti-erp:CLI-4106',NULL,'team-di-visibilita:TEAM-AMM,team-di-visibilita:TEAM-DIR');

INSERT IGNORE INTO compiti VALUES
('CMP-1','Richiamare acquisti Brenta sull''offerta','Not Started','High','2026-11-03 17:00:00','Confermare la data del sopralluogo e chi manda l''ordine.','COfferta','offerte-commerciali:OFF-700','utenti-meridia:USR-chiara','team-di-visibilita:TEAM-VNE,team-di-visibilita:TEAM-DIR'),
('CMP-2','Preparare revisione prezzi cartiera','Started','Normal','2026-11-06 12:00:00','Il full service è in negoziazione: aggiornare le ore di fermata.','COfferta','offerte-commerciali:OFF-701','utenti-meridia:USR-chiara','team-di-visibilita:TEAM-VNE,team-di-visibilita:TEAM-DIR'),
('CMP-3','Mandare scheda tecnica al molino','Not Started','Normal','2026-11-12 18:00:00','Qualità chiede il layout del confezionamento.','COfferta','offerte-commerciali:OFF-702','utenti-meridia:USR-chiara','team-di-visibilita:TEAM-VNE,team-di-visibilita:TEAM-DIR'),
('CMP-4','Allineare la sicurezza del laminatoio','Not Started','High','2026-11-14 18:00:00','Mora deve controfirmare il perimetro macchine.','COfferta','offerte-commerciali:OFF-704','utenti-meridia:USR-marco','team-di-visibilita:TEAM-LOM,team-di-visibilita:TEAM-DIR'),
('CMP-5','Chiudere l''allarme vibrazione di Sacile','Started','Urgent','2026-10-20 18:00:00','Verificare il riduttore e aggiornare il cliente.','Case','ticket-di-assistenza:TCK-90','utenti-meridia:USR-elena','team-di-visibilita:TEAM-ASS,team-di-visibilita:TEAM-DIR'),
('CMP-6','Spedire il manuale ATEX in italiano','Not Started','Normal','2026-10-24 18:00:00','HSE di Isarco aspetta la revisione.','Case','ticket-di-assistenza:TCK-92','utenti-meridia:USR-elena','team-di-visibilita:TEAM-ASS,team-di-visibilita:TEAM-DIR'),
('CMP-7','Sollecitare la fattura materiali ATEX','Not Started','High','2026-10-21 12:00:00','La 2026/110 risulta scaduta.','Case','ticket-di-assistenza:TCK-92','utenti-meridia:USR-davide','team-di-visibilita:TEAM-AMM,team-di-visibilita:TEAM-DIR');

INSERT IGNORE INTO chiamate VALUES
('CHM-1','Acquisti Brenta, stato revamping','Held','2026-10-09 10:00:00','2026-10-09 10:25:00','Outbound','Marco Trevisan chiede lo slittamento di una settimana.','anagrafiche-clienti-erp:CLI-4100','rubrica-commerciale:CNT-4101','utenti-meridia:USR-chiara','team-di-visibilita:TEAM-VNE,team-di-visibilita:TEAM-DIR'),
('CHM-2','Plant manager cartiera','Held','2026-10-15 15:10:00','2026-10-15 15:40:00','Outbound','Confermata la fermata di Sacile del 4 novembre.','anagrafiche-clienti-erp:CLI-4101','rubrica-commerciale:CNT-4102','utenti-meridia:USR-chiara','team-di-visibilita:TEAM-VNE,team-di-visibilita:TEAM-DIR'),
('CHM-3','HSE Isarco sul manuale','Planned','2026-10-22 09:30:00','2026-10-22 10:00:00','Outbound','Da richiamare per la consegna del PDF in italiano.','anagrafiche-clienti-erp:CLI-4106','rubrica-commerciale:CNT-4109','utenti-meridia:USR-elena','team-di-visibilita:TEAM-ASS,team-di-visibilita:TEAM-DIR'),
('CHM-4','Energy manager Garda','Held','2026-10-13 11:00:00','2026-10-13 11:35:00','Inbound','Irene Gazza ha chiesto il verbale del rilievo.','anagrafiche-clienti-erp:CLI-4107','rubrica-commerciale:CNT-4110','utenti-meridia:USR-marco','team-di-visibilita:TEAM-LOM,team-di-visibilita:TEAM-DIR');

INSERT IGNORE INTO articoli VALUES
('KB-1','Allarme vibrazione su riduttore','Published','<p>Fermare la linea se la vibrazione supera la soglia per più di dieci minuti. Controllare olio, giunto e ancoraggi prima di riavviare. Annotare ora e turno nel ticket.</p>','categorie-conoscenza:CAT-ASS','team-di-visibilita:TEAM-ASS,team-di-visibilita:TEAM-DIR'),
('KB-2','Accesso in zona ATEX','Published','<p>Entrare solo con permesso di lavoro firmato dall''HSE dello stabilimento. Niente attrezzi non certificati. Il manuale del quadro va lasciato in copia al cliente.</p>','categorie-conoscenza:CAT-SIC','team-di-visibilita:TEAM-ASS,team-di-visibilita:TEAM-DIR'),
('KB-3','Fattura scaduta: chi avvisa il cliente','Published','<p>L''amministrazione sollecita dopo sette giorni. Se il cliente contesta la prestazione, il sollecito si ferma e si apre un compito sull''assistenza.</p>','categorie-conoscenza:CAT-ASS','team-di-visibilita:TEAM-AMM,team-di-visibilita:TEAM-ASS,team-di-visibilita:TEAM-DIR');

INSERT IGNORE INTO liste VALUES
('LST-1','Inviti MECSPE 2027','Contatti da portare in fiera a Bologna.','rubrica-commerciale:CNT-4101,rubrica-commerciale:CNT-4102,rubrica-commerciale:CNT-4107,rubrica-commerciale:CNT-4110,rubrica-commerciale:CNT-221','team-di-visibilita:TEAM-VNE,team-di-visibilita:TEAM-LOM,team-di-visibilita:TEAM-DIR');

INSERT IGNORE INTO campagne VALUES
('CMPG-1','MECSPE Bologna 2027','Planning','Mail','2027-03-18','2027-03-20','Stand automazione impianti. Gli inviti partono a gennaio.','liste-fiera:LST-1','team-di-visibilita:TEAM-VNE,team-di-visibilita:TEAM-LOM,team-di-visibilita:TEAM-DIR');

INSERT IGNORE INTO modelli VALUES
('MAIL-1','Invio offerta','La nostra offerta per {Account.name}','<p>Buongiorno,</p><p>in allegato l''offerta aggiornata. Restiamo in attesa di un riscontro per fissare il sopralluogo.</p><p>Gruppo Meridia</p>','1','Active'),
('MAIL-2','Apertura ticket','Abbiamo preso in carico la segnalazione','<p>Buongiorno,</p><p>la segnalazione è aperta. Un tecnico del team assistenza la aggiorna appena ha il rilievo.</p><p>Gruppo Meridia</p>','1','Active');
