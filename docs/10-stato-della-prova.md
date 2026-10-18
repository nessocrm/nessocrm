# Stato della prova

Questa pagina è la fotografia del primo seme, letta il 17/10/2026 nel pomeriggio. Non è il demo che gira adesso. Il demo corrente è Gruppo Meridia, nel capitolo omonimo.

Fotografia letta da `motore.sqlite` e dal database `gestionale`. Sono dati inventati su Espo vuoto, più un lead inserito con una chiamata all'integrazione di seme. Nessuna riga viene dal dump di produzione.

Gli id Espo sono quelli di questa installazione. Un volume ricreato ne avrà altri.

## Collegamenti

| Id | Nome | Tipo | Configurazione utile |
|---|---|---|---|
| `file-notturno` | File notturno | csv | cartella `scambio/file-notturno/` |
| `gestionale-clienti` | Gestionale clienti | database | host `db`, porta 3306, database `gestionale`, utente `espocrm`, query `SELECT codice, ragione_sociale, email, piva FROM clienti` |
| `portale-esterno` | Portale esterno | http | URL vuoto, quindi casella locale |
| `sito-web` | Sito web | webhook | nessun parametro; l'indirizzo è sulla scheda in pagina |

I token non sono riportati qui. Stanno negli URL sulla pagina.

## Integrazioni

| Id | Verso | Scheda | Collegamento | Cadenza | Identità | Abbinamento |
|---|---|---|---|---|---|---|
| `anagrafica-clienti` | in | Account | nessuno | manuale | `codice` → chiave `anagrafica:{codice}` | ragioneSociale→name, piva→cPartitaIva, email→emailAddress, descrizione costante |
| `clienti-gestionale-verso-account` | in | Account | gestionale-clienti | 15 min | `codice` | ragione_sociale→name, email→emailAddress, piva→cPartitaIva |
| `contatti-da-espo` | out | Account | nessuno | manuale | — | name→bo |
| `contatti-del-gestionale` | in | Contact | nessuno | manuale | `codice` | nome→firstName, cognome→lastName, email→emailAddress |
| `file-notturno-verso-contatti` | in | Contact | file-notturno | manuale | `codice` | nome, cognome, email come sopra |
| `lead-verso-portale` | out | Lead | portale-esterno | manuale | — | firstName→nome, lastName→cognome, emailAddress→email, cExternalKey→chiave |
| `modulo-web` | in | Lead | nessuno | manuale | `id` → chiave `modulo-web:{id}` | nome, cognome, email, telefono, source costante `Web Site`, descrizione costante |
| `richieste-del-sito-verso-lead` | in | Lead | sito-web | manuale | `id` | nome, cognome, email |
| `uscita-lead` | out | Lead | nessuno | manuale | — | id, cExternalKey, firstName, lastName, emailAddress, source, modifiedAt |

`clienti-gestionale-verso-account` ha `last_status` errore e dettaglio «3 righe dal database, 0 create, 0 aggiornate, 1 scartate. Espo ha già un record simile (Officina Del Porto) con un'altra chiave». È un giro successivo al primo, che aveva creato due account. Le due creazioni sono diventate `invariato` e non entrano nei contatori, quindi il giro con un solo scarto risulta errore. I due account su Espo ci sono.

`file-notturno-verso-contatti`: ok, «1 righe dai file CSV».

`richieste-del-sito-verso-lead`: ok, «1 record ricevuti via webhook».

`lead-verso-portale`: ok, tre record inviati alla casella su `127.0.0.1`.

Le altre hanno `last_status` vuoto. `uscita-lead` e `contatti-da-espo` hanno però un cursore: sono state lette con `/api/pull`, che non compila l'ultimo esito.

## Coda di ingresso

| Integrazione | Id esterno | Esito in coda | Id Espo | Chiave |
|---|---|---|---|---|
| modulo-web | WEB-1001 | aggiornato | 6ad34a7e5b76fe198 | modulo-web:WEB-1001 |
| anagrafica-clienti | CLI-42 | creato | 6ad34a7f1b75d9805 | anagrafica:CLI-42 |
| contatti-del-gestionale | CNT-7 | creato | 6ad3506c454f0810b | contatti-del-gestionale:CNT-7 |
| modulo-web | 1 | creato | 6ad3526c86e9ea0d2 | modulo-web:1 |
| richieste-del-sito-verso-lead | WEB-77 | creato | 6ad353977a2a687a1 | richieste-del-sito-verso-lead:WEB-77 |
| clienti-gestionale-verso-account | CLI-101 | creato | 6ad353c4a4f2c162d | clienti-gestionale-verso-account:CLI-101 |
| clienti-gestionale-verso-account | CLI-102 | creato | 6ad353c524876194f | clienti-gestionale-verso-account:CLI-102 |
| file-notturno-verso-contatti | CNT-20 | creato | 6ad353c8f0c326d5f | file-notturno-verso-contatti:CNT-20 |

`CLI-100` non è in coda. È lo scarto.

Contenuto utile dei record, senza ripetere l'anagrafica personale oltre i nomi di prova:

| Record | Dati mandati a Espo |
|---|---|
| Marta Bianchi | nome Marta, cognome Bianchi, email `marta.bianchi@example.test`, telefono `+393339009009`, source Web Site, descrizione «Creato dal motore locale» |
| Officina Del Porto | nome, email `contatti@officina-porto.example.test`, partita IVA `12345678901` |
| Luca Neri | nome Luca, cognome Neri, email `luca.neri@example.test` |
| Lead id esterno 1 su modulo-web | entrato dalla stessa integrazione di Marta, scheda Lead |
| Giulia Costa | nome Giulia, cognome Costa, email `giulia.costa@example.test` |
| Studio Nord | email `nord@example.test`, partita IVA `10000000002` |
| Panificio Rosa | email `rosa@example.test`, partita IVA `10000000003` |
| Sara Verdi | nome Sara, cognome Verdi, email `sara.verdi@example.test` |

Il file di Sara è `scambio/file-notturno/elaborati/20261017105401-contatti.csv`.

## Tabella di prova sul gestionale

```text
CLI-100  Officina del Porto  porto@example.test   10000000001
CLI-101  Studio Nord         nord@example.test    10000000002
CLI-102  Panificio Rosa      rosa@example.test    10000000003
```

## Uscite

Sink:

| Integrazione | Id Espo | Payload |
|---|---|---|
| uscita-lead | 6ad34a7e5b76fe198 | Marta, con espoId, chiaveEsterna, nome, cognome, email |
| contatti-da-espo | 6ad34a7f1b75d9805 | `{"bo": "Officina Del Porto"}` |
| lead-verso-portale | tre id | Marta, il lead `modulo-web:1`, Giulia, ciascuno con nome, cognome, email, chiave |

Delivery di `lead-verso-portale`: per ogni lead una riga `inviato` e una riga `ricevuto` sulla casella `portale-esterno`.

## Come si rilegge da soli

Dalla questa cartella, con i contenitori accesi:

```text
docker exec nessocrm-motore python -c "import sqlite3; c=sqlite3.connect('/data/motore.sqlite'); print(list(c.execute('SELECT id, name, direction, espo_entity, connection_id, last_status, last_detail FROM pipeline')))"
```

Espo, dopo il login `admin` / `locale-admin`: Lead, Account, Contatti. I record qui sopra sono quelli da cercare.
