CREATE DATABASE IF NOT EXISTS meridia_erp CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON meridia_erp.* TO 'espocrm'@'%';
FLUSH PRIVILEGES;
USE meridia_erp;

CREATE TABLE IF NOT EXISTS clienti (
  codice varchar(40) NOT NULL PRIMARY KEY,
  ragione_sociale varchar(200) NOT NULL,
  email varchar(200),
  telefono varchar(40),
  citta varchar(80),
  sito varchar(200),
  tipo varchar(40),
  settore varchar(80),
  nazione varchar(40),
  nota varchar(500)
);

CREATE TABLE IF NOT EXISTS partner (
  codice varchar(40) NOT NULL PRIMARY KEY,
  ragione_sociale varchar(200) NOT NULL,
  email varchar(200),
  telefono varchar(40),
  citta varchar(80),
  sito varchar(200),
  tipo varchar(40),
  settore varchar(80),
  nazione varchar(40),
  nota varchar(500)
);

CREATE TABLE IF NOT EXISTS contatti (
  codice varchar(40) NOT NULL PRIMARY KEY,
  nome varchar(80),
  cognome varchar(80) NOT NULL,
  email varchar(200),
  telefono varchar(40),
  ruolo varchar(120),
  chiave_account varchar(180) NOT NULL
);

CREATE TABLE IF NOT EXISTS sedi (
  codice varchar(40) NOT NULL PRIMARY KEY,
  nome varchar(200) NOT NULL,
  indirizzo varchar(200),
  chiave_account varchar(180) NOT NULL
);

CREATE TABLE IF NOT EXISTS offerte (
  codice varchar(40) NOT NULL PRIMARY KEY,
  titolo varchar(200) NOT NULL,
  fase varchar(40) NOT NULL,
  chiusura date,
  importo decimal(14,2),
  probabilita int,
  chiave_account varchar(180) NOT NULL,
  chiave_contatto varchar(180)
);

CREATE TABLE IF NOT EXISTS contratti (
  codice varchar(40) NOT NULL PRIMARY KEY,
  nome varchar(200) NOT NULL,
  stato varchar(40),
  valore varchar(40),
  decorrenza varchar(20),
  scadenza varchar(20),
  chiave_account varchar(180) NOT NULL,
  chiave_offerta varchar(180)
);

CREATE TABLE IF NOT EXISTS commesse (
  codice varchar(40) NOT NULL PRIMARY KEY,
  nome varchar(200) NOT NULL,
  stato varchar(40),
  valore varchar(40),
  apertura varchar(20),
  chiave_account varchar(180) NOT NULL,
  chiave_contratto varchar(180)
);

CREATE TABLE IF NOT EXISTS interventi (
  codice varchar(40) NOT NULL PRIMARY KEY,
  nome varchar(200) NOT NULL,
  stato varchar(40),
  data_prevista varchar(20),
  tecnico varchar(120),
  chiave_commessa varchar(180) NOT NULL,
  chiave_contatto varchar(180)
);

CREATE TABLE IF NOT EXISTS fatture (
  codice varchar(40) NOT NULL PRIMARY KEY,
  nome varchar(200) NOT NULL,
  stato varchar(40),
  importo varchar(40),
  data_fattura varchar(20),
  chiave_account varchar(180) NOT NULL,
  chiave_commessa varchar(180)
);

CREATE TABLE IF NOT EXISTS ticket (
  codice varchar(40) NOT NULL PRIMARY KEY,
  nome varchar(200) NOT NULL,
  stato varchar(40),
  priorita varchar(20),
  tipo varchar(40),
  nota varchar(500),
  chiave_account varchar(180) NOT NULL,
  chiave_contatto varchar(180)
);

INSERT IGNORE INTO clienti VALUES
('CLI-4100','Officine Brenta S.p.A.','acquisti@brenta.example.test','0444123400','Vicenza','https://brenta.example.test','Customer','Manufacturing','Italy','Cliente storico, linee di assemblaggio e revamping.'),
('CLI-4101','Cartiera del Livenza S.r.l.','impianti@livenza.example.test','0434123401','Pordenone','https://livenza.example.test','Customer','Manufacturing','Italy','Due stabilimenti, contratto di manutenzione in scadenza.'),
('CLI-4102','Molino Adriatico S.p.A.','tecnico@adriatico.example.test','071123402','Ancona','https://adriatico.example.test','Customer','Food & Beverage','Italy','Nuovo silo e automazione del confezionamento.'),
('CLI-4103','Vetreria Levante S.p.A.','operations@levante.example.test','080123403','Bari','https://levante.example.test','Customer','Manufacturing','Italy','Forno 2 in fermata programmata a novembre.'),
('CLI-4104','Acciaierie del Mincio S.p.A.','buyer@mincio.example.test','0376123404','Mantova','https://mincio.example.test','Customer','Manufacturing','Italy','Trattativa sul laminatoio e sulla sicurezza macchine.'),
('CLI-4105','Latteria Valsugana S.c.a.','qualita@valsugana.example.test','0461123405','Trento','https://valsugana.example.test','Customer','Food & Beverage','Italy','Tracciabilità lotti e celle frigorifere.'),
('CLI-4106','Chimica Isarco S.p.A.','hse@isarco.example.test','0471123406','Bolzano','https://isarco.example.test','Customer','Chemical','Italy','Quadro di controllo e messa a norma ATEX.'),
('CLI-4107','Cogenera Garda S.r.l.','energia@garda.example.test','030123407','Brescia','https://garda.example.test','Customer','Energy','Italy','Impianto di cogenerazione e telegestione.');

INSERT IGNORE INTO partner VALUES
('FOR-220','Quadri Elettrici Piave S.r.l.','ordini@piave.example.test','0422123220','Treviso','https://piave.example.test','Partner','Electronics','Italy','Costruttore dei quadri di potenza.'),
('FOR-221','Sensori Delta S.p.A.','sales@delta.example.test','022123221','Milano','https://delta.example.test','Partner','Electronics','Italy','Sensori di processo e ricambi.'),
('FOR-222','Logistica Pedemontana S.r.l.','traffico@pedemontana.example.test','045123222','Verona','https://pedemontana.example.test','Partner','Service','Italy','Trasporto eccezionale dei macchinari.'),
('FOR-223','Studio Ingegneria Mora','progetti@mora.example.test','049123223','Padova','https://mora.example.test','Partner','Consulting','Italy','Progettazione elettrica e direzione lavori.');

INSERT IGNORE INTO contatti VALUES
('CNT-4100','Elena','Marchiori','elena.marchiori@brenta.example.test','0444123410','Direttore operations','anagrafiche-clienti-erp:CLI-4100'),
('CNT-4101','Marco','Trevisan','marco.trevisan@brenta.example.test','0444123411','Responsabile acquisti','anagrafiche-clienti-erp:CLI-4100'),
('CNT-4102','Giulia','Santin','giulia.santin@livenza.example.test','0434123412','Plant manager','anagrafiche-clienti-erp:CLI-4101'),
('CNT-4103','Davide','Pozzo','davide.pozzo@livenza.example.test','0434123413','Manutenzione','anagrafiche-clienti-erp:CLI-4101'),
('CNT-4104','Chiara','Bonetti','chiara.bonetti@adriatico.example.test','071123414','Responsabile qualità','anagrafiche-clienti-erp:CLI-4102'),
('CNT-4105','Andrea','Ferri','andrea.ferri@adriatico.example.test','071123415','Tecnico di stabilimento','anagrafiche-clienti-erp:CLI-4102'),
('CNT-4106','Paola','Greco','paola.greco@levante.example.test','080123416','Direttore di produzione','anagrafiche-clienti-erp:CLI-4103'),
('CNT-4107','Luca','Rizzi','luca.rizzi@mincio.example.test','0376123417','Buyer impianti','anagrafiche-clienti-erp:CLI-4104'),
('CNT-4108','Sara','Endrizzi','sara.endrizzi@valsugana.example.test','0461123418','Responsabile qualità','anagrafiche-clienti-erp:CLI-4105'),
('CNT-4109','Matteo','Hofer','matteo.hofer@isarco.example.test','0471123419','HSE manager','anagrafiche-clienti-erp:CLI-4106'),
('CNT-4110','Irene','Gazza','irene.gazza@garda.example.test','030123420','Energy manager','anagrafiche-clienti-erp:CLI-4107'),
('CNT-220','Roberto','Cavallin','roberto.cavallin@piave.example.test','0422123221','Responsabile ordini','fornitori-e-partner-erp:FOR-220'),
('CNT-221','Silvia','Negri','silvia.negri@delta.example.test','022123231','Account tecnico','fornitori-e-partner-erp:FOR-221'),
('CNT-223','Paolo','Mora','paolo.mora@mora.example.test','049123233','Socio progettista','fornitori-e-partner-erp:FOR-223');

INSERT IGNORE INTO sedi VALUES
('SED-1','Stabilimento Vicenza nord','Via dell''Industria 18, Vicenza','anagrafiche-clienti-erp:CLI-4100'),
('SED-2','Reparto montaggio Vicenza','Via dell''Industria 22, Vicenza','anagrafiche-clienti-erp:CLI-4100'),
('SED-3','Cartiera Sacile','Via del Fiume 4, Sacile','anagrafiche-clienti-erp:CLI-4101'),
('SED-4','Cartiera Portogruaro','Via della Carta 9, Portogruaro','anagrafiche-clienti-erp:CLI-4101'),
('SED-5','Molino porto','Banchina Mazzini 2, Ancona','anagrafiche-clienti-erp:CLI-4102'),
('SED-6','Forno 2','Zona industriale Asi, Bari','anagrafiche-clienti-erp:CLI-4103'),
('SED-7','Laminatoio','Via Acciaio 1, Mantova','anagrafiche-clienti-erp:CLI-4104'),
('SED-8','Centrale di cogenerazione','Via Energia 7, Brescia','anagrafiche-clienti-erp:CLI-4107');

INSERT IGNORE INTO offerte VALUES
('OFF-700','Revamping linea assemblaggio Brenta','Proposal','2026-12-15',480000,60,'anagrafiche-clienti-erp:CLI-4100','rubrica-commerciale:CNT-4101'),
('OFF-701','Manutenzione full service cartiera','Negotiation','2026-11-20',220000,70,'anagrafiche-clienti-erp:CLI-4101','rubrica-commerciale:CNT-4102'),
('OFF-702','Automazione confezionamento molino','Qualification','2027-01-31',310000,40,'anagrafiche-clienti-erp:CLI-4102','rubrica-commerciale:CNT-4104'),
('OFF-703','Fermata forno 2 e ricambi','Prospecting','2026-11-30',150000,30,'anagrafiche-clienti-erp:CLI-4103','rubrica-commerciale:CNT-4106'),
('OFF-704','Sicurezza macchine laminatoio','Proposal','2026-12-20',890000,50,'anagrafiche-clienti-erp:CLI-4104','rubrica-commerciale:CNT-4107'),
('OFF-705','Tracciabilità lotti latteria','Negotiation','2026-11-10',175000,80,'anagrafiche-clienti-erp:CLI-4105','rubrica-commerciale:CNT-4108'),
('OFF-706','Quadro ATEX isarco','Closed Won','2026-09-30',260000,100,'anagrafiche-clienti-erp:CLI-4106','rubrica-commerciale:CNT-4109'),
('OFF-707','Telegestione cogenerazione','Qualification','2027-02-28',540000,35,'anagrafiche-clienti-erp:CLI-4107','rubrica-commerciale:CNT-4110');

INSERT IGNORE INTO contratti VALUES
('CON-300','Full service cartiera 2026-2028','In vigore','220000','2026-01-01','2028-12-31','anagrafiche-clienti-erp:CLI-4101','offerte-commerciali:OFF-701'),
('CON-301','Quadro ATEX Isarco','In vigore','260000','2026-10-01','2027-09-30','anagrafiche-clienti-erp:CLI-4106','offerte-commerciali:OFF-706'),
('CON-302','Manutenzione linee Brenta','In rinnovo','180000','2024-01-01','2026-12-31','anagrafiche-clienti-erp:CLI-4100','offerte-commerciali:OFF-700'),
('CON-303','Ricambi programmati Levante','Bozza','90000','2027-01-01','2027-12-31','anagrafiche-clienti-erp:CLI-4103','offerte-commerciali:OFF-703'),
('CON-304','Telegestione Garda','Bozza','540000','2027-03-01','2030-02-28','anagrafiche-clienti-erp:CLI-4107','offerte-commerciali:OFF-707');

INSERT IGNORE INTO commesse VALUES
('COM-800','Fermata programmata Sacile','In corso','140000','2026-10-01','anagrafiche-clienti-erp:CLI-4101','contratti-quadro:CON-300'),
('COM-801','Installazione quadro ATEX','In corso','260000','2026-10-06','anagrafiche-clienti-erp:CLI-4106','contratti-quadro:CON-301'),
('COM-802','Ricambi linea 3 Brenta','Pianificata','45000','2026-11-02','anagrafiche-clienti-erp:CLI-4100','contratti-quadro:CON-302'),
('COM-803','Collaudo celle Valsugana','Pianificata','60000','2026-11-16','anagrafiche-clienti-erp:CLI-4105','contratti-quadro:CON-300'),
('COM-804','Messa in servizio forno','Da avviare','150000','2026-11-20','anagrafiche-clienti-erp:CLI-4103','contratti-quadro:CON-303'),
('COM-805','Rilievo cogeneratore','In corso','30000','2026-10-12','anagrafiche-clienti-erp:CLI-4107','contratti-quadro:CON-304');

INSERT IGNORE INTO interventi VALUES
('INT-1','Ispezione riduttori Sacile','Pianificato','2026-11-04','Lucia Ferraro','commesse-di-lavoro:COM-800','rubrica-commerciale:CNT-4103'),
('INT-2','Taratura sensori ATEX','Pianificato','2026-11-06','Nicola Baldo','commesse-di-lavoro:COM-801','rubrica-commerciale:CNT-4109'),
('INT-3','Sostituzione inverter linea 3','Pianificato','2026-11-12','Lucia Ferraro','commesse-di-lavoro:COM-802','rubrica-commerciale:CNT-4100'),
('INT-4','Verifica sonde celle','Pianificato','2026-11-18','Marta Conte','commesse-di-lavoro:COM-803','rubrica-commerciale:CNT-4108'),
('INT-5','Rilievo quadri forno','Da confermare','2026-11-24','Nicola Baldo','commesse-di-lavoro:COM-804','rubrica-commerciale:CNT-4106'),
('INT-6','Messa in rete telegestione','In corso','2026-10-21','Marta Conte','commesse-di-lavoro:COM-805','rubrica-commerciale:CNT-4110');

INSERT IGNORE INTO fatture VALUES
('FAT-2026-118','Fattura 2026/118 acconto ATEX','Emessa','104000','2026-10-15','anagrafiche-clienti-erp:CLI-4106','commesse-di-lavoro:COM-801'),
('FAT-2026-104','Fattura 2026/104 canone ottobre cartiera','Emessa','18300','2026-10-05','anagrafiche-clienti-erp:CLI-4101','commesse-di-lavoro:COM-800'),
('FAT-2026-097','Fattura 2026/097 ricambi Brenta','Pagata','22000','2026-09-20','anagrafiche-clienti-erp:CLI-4100','commesse-di-lavoro:COM-802'),
('FAT-2026-121','Fattura 2026/121 rilievo Garda','Emessa','12000','2026-10-18','anagrafiche-clienti-erp:CLI-4107','commesse-di-lavoro:COM-805'),
('FAT-2026-088','Fattura 2026/088 chiusura trimestre cartiera','Pagata','18300','2026-09-05','anagrafiche-clienti-erp:CLI-4101','commesse-di-lavoro:COM-800'),
('FAT-2026-110','Fattura 2026/110 materiali ATEX','Scaduta','36000','2026-09-28','anagrafiche-clienti-erp:CLI-4106','commesse-di-lavoro:COM-801');

INSERT IGNORE INTO ticket VALUES
('TCK-90','Allarme vibrazione riduttore Sacile','Assigned','High','Incident','Il riduttore della linea pasta sale di vibrazione a fine turno.','anagrafiche-clienti-erp:CLI-4101','rubrica-commerciale:CNT-4103'),
('TCK-91','Sensore livello silo in deriva','Pending','Normal','Problem','Lettura instabile dopo il temporale del 12 ottobre.','anagrafiche-clienti-erp:CLI-4102','rubrica-commerciale:CNT-4105'),
('TCK-92','Richiesta manuale ATEX in italiano','New','Low','Question','Il responsabile HSE chiede la revisione del manuale.','anagrafiche-clienti-erp:CLI-4106','rubrica-commerciale:CNT-4109'),
('TCK-93','Fermata non prevista linea 3','Assigned','Urgent','Incident','Inverter in fault, produzione ferma dal turno di notte.','anagrafiche-clienti-erp:CLI-4100','rubrica-commerciale:CNT-4100'),
('TCK-94','Scostamento temperatura cella 2','Pending','High','Incident','Soglia superata due notti di fila.','anagrafiche-clienti-erp:CLI-4105','rubrica-commerciale:CNT-4108'),
('TCK-95','Domanda su finestra di fermata forno','New','Normal','Question','Chiedono se la fermata può slittare di una settimana.','anagrafiche-clienti-erp:CLI-4103','rubrica-commerciale:CNT-4106');
