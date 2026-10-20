# Esercizio

## Accendere

Dalla root del repository:

```text
docker compose up -d --build
```

La prima volta scarica `mariadb:11.4`, `espocrm/espocrm:10.0` e costruisce il motore (`python:3.12-slim`, pip di `pymysql`). Espo installa il CRM nel volume. Il motore aspetta il healthcheck.

| Controllo | Atteso |
|---|---|
| http://localhost:8088 | pagina di login Espo, italiano |
| `admin` / `locale-admin` | entra |
| http://localhost:8091 | primo ingresso, poi la pagina Inizio |
| http://localhost:8091/api/health | `espo` raggiungibile, `fields` pronti |

`docker compose ps` deve mostrare `nessocrm-db`, `nessocrm-espo`, `nessocrm-daemon`, `nessocrm-motore`.

Fermare senza perdere i dati: `docker compose stop`. Ripartire: `docker compose start`. Cancellare i volumi, e con essi Espo, lo stato e `gestionale`: `docker compose down -v`. La cartella `scambio` sull'host resta.

Una modifica a `motore/app.py` o `motore/index.html` richiede `docker compose up -d --build motore`. Il build copia i file nell'immagine. Montare la cartella del codice non è previsto.

## Ricreare il database di prova

Serve solo se il volume MariaDB è nuovo. `gestionale` non è nello script di init del compose. Dal PC, con il contenitore su:

```text
docker exec nessocrm-db mariadb -uroot -plocale-root -e "CREATE DATABASE IF NOT EXISTS gestionale; GRANT ALL ON gestionale.* TO 'espocrm'@'%'; FLUSH PRIVILEGES; CREATE TABLE IF NOT EXISTS gestionale.clienti (codice varchar(40) NOT NULL, ragione_sociale varchar(200), email varchar(200), piva varchar(20), PRIMARY KEY (codice)); INSERT IGNORE INTO gestionale.clienti VALUES ('CLI-100','Officina del Porto','porto@example.test','10000000001'), ('CLI-101','Studio Nord','nord@example.test','10000000002'), ('CLI-102','Panificio Rosa','rosa@example.test','10000000003');"
```

Poi, sulla pagina, collegamento database con host `db`, porta 3306, database `gestionale`, utente `espocrm`, password `locale-db`, e la SELECT sulle quattro colonne. Il salvataggio che elenca le colonne ha già eseguito la query.

## Provare i quattro canali a mano

Webhook. Dalla scheda si copia l'indirizzo. Un POST:

```text
curl -H "Content-Type: application/json" -d "{\"id\":\"WEB-200\",\"nome\":\"Prova\",\"cognome\":\"Canale\",\"email\":\"prova.canale@example.test\"}" http://localhost:8091/hook/{id}/{token}
```

La risposta `creato` e, in Espo, un lead nuovo. Lo stesso comando una seconda volta: `invariato`.

Database. Sulla integrazione appesa a quel collegamento, «Esegui ora». Il dettaglio riporta righe, create, aggiornate, scartate. Il secondo click, a dati fermi, porta a zero create e zero aggiornate.

CSV. Si mette un file in `scambio/{id}/`, intestazione uguale all'abbinamento, colonna identificativa valorizzata:

```text
codice,nome,cognome,email
CNT-30,Nino,Re,nino.re@example.test
```

«Esegui ora». Il file deve comparire in `elaborati/` con il prefisso data-ora. Il contatto è in Espo.

Uscita. Integrazione su un collegamento HTTP, «Esegui ora». Con URL vuoto, «Ultimi passaggi» mostra `inviato` e `ricevuto` per ogni record il cui `modifiedAt` è nuovo. Un secondo click a CRM fermo invia zero record.

## Dove si guarda un fallimento

| Sintomo | Dove |
|---|---|
| La pagina non elenca schede | Espo non è ancora su, oppure `/api/catalog` è 400. Health dice se l'admin risponde |
| Salva collegamento database fallisce | testo nel modulo: host, permesso, oppure «è ammessa una sola SELECT» |
| Esegui ora sul database segna scartate | `last_detail` ha il primo motivo. Il caso noto è il nome account già usato da un'altra chiave |
| Una riga CSV non entra | se la colonna c'è, il file è comunque in `elaborati/` e la riga è in Attività. Se manca una colonna obbligatoria, il file resta nella cartella e lo scarto è uno solo |
| Esegui ora dice che un'esecuzione è già in corso | un altro giro, o il pianificatore, tiene `RUN_LOCK` |
| L'uscita rimanda sempre gli stessi record | il cursore non avanza. Se manca `modifiedAt` il cursore segue l'id già consegnato; se continua a rimandare, il POST precedente non era riuscito |
| L'uscita non rimanda un record che in Espo c'è già | il suo `modifiedAt` è minore o uguale al cursore in `cursor_state` |
| Un campo non è nel menu | tipo non scrivibile, read only, scheda senza tab, oppure cache di 120 secondi appena dopo una creazione |
| Il build non cambia la pagina | l'immagine non è stata ricostruita |

Log del motore: `docker logs nessocrm-motore`. Ogni richiesta è una riga `[motore]`. Il pianificatore, in errore, stampa `[motore] pianificazione`.

## Porte già occupate

La scelta 8088 e 8091 è di questa macchina. Se una delle due è presa, Compose non pubblica il servizio. Non si cambia la porta nel CRM già installato senza allineare `ESPOCRM_SITE_URL` e `ESPO_PUBLIC_URL`: gli indirizzi dentro l'app sono quelli delle variabili, non quelli indovinati dal browser.

## Cosa non fare su questo PC pensando di toccare la produzione

I contenitori si chiamano `nessocrm-*`. I dump in `01-espocrm-database` e `03-dwh-database` non sono argomenti di alcun servizio. Importarli in `nessocrm-db` mescolerebbe i dati veri con la prova. Il manuale non descrive quel comando.

## Manuale

Il sito dei docs si costruisce da questa root.

```text
py -3 -m pip install -r requirements-docs.txt
py -3 -m mkdocs serve
```

Si apre su http://127.0.0.1:8000. Il controllo, senza avviare il server, è `py -3 -m mkdocs build --strict`. La configurazione è `mkdocs.yml`. I capitoli italiani stanno in `docs/` e gli stessi capitoli in inglese stanno in `docs/en/`, con lo stesso nome di file. Il menu del sito è la chiave `nav` di `mkdocs.yml`. Il cambio lingua sta nell'intestazione del sito.
