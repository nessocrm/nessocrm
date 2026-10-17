# Modello dati del motore

Tutto lo stato del motore è un file SQLite: `/data/motore.sqlite` nel volume `motore-data`. Espo ha il proprio MariaDB. I due non condividono tabelle.

## pipeline

Una riga è un'integrazione.

| Colonna | Vincolo | Significato |
|---|---|---|
| `id` | chiave primaria | Slug |
| `name` | obbligatorio | Nome in pagina |
| `direction` | `in` o `out` | Verso Espo o da Espo |
| `espo_entity` | obbligatorio | Nome tecnico: `Lead`, `Account`, `Contact` |
| `external_id_field` | obbligatorio | Colonna esterna che identifica il record. In uscita, se manca, il server scrive `id` |
| `key_template` | obbligatorio | In ingresso `modulo-web:{id}`. In uscita stringa vuota |
| `mapping_json` | obbligatorio | Lista di `{from, to, transform}` |
| `key_field` | default `cExternalKey` | Campo Espo su cui si cerca e si scrive la chiave |
| `connection_id` | nullo ammesso | Collegamento. Nessuna foreign key: il valore è controllato in scrittura |
| `schedule_minutes` | default 0 | 0, 5, 15 o 60 |
| `last_run` | nullo | `YYYY-MM-DD HH:MM:SS` locale del contenitore |
| `last_status` | nullo | `ok` o `errore` |
| `last_detail` | nullo | Testo, tagliato a 500 caratteri |

Le sei colonne da `key_field` in poi non c'erano nella prima creazione. `init_db` le aggiunge con `ALTER` se `PRAGMA table_info` non le vede. Un file vecchio si apre ancora.

`/api/pull/{id}` scrive il cursore e il sink e non aggiorna `last_run`. Per questo un'integrazione può avere righe in `sink_item` e `last_status` vuoto. «Esegui ora» passa da `run_pipeline` e invece aggiorna i tre campi.

## connection

| Colonna | Significato |
|---|---|
| `id` | Slug |
| `name` | Nome in pagina |
| `kind` | `webhook`, `database`, `csv`, `http` |
| `config_json` | Vedi sotto. La password del database sta in chiaro in questo file, sul volume locale |
| `token` | Segreto URL-safe di 24 byte. Nasce alla creazione e non viene rigenerato da un aggiornamento |

`config_json` per tipo:

| kind | Contenuto |
|---|---|
| webhook | `{}` |
| csv | `{}` |
| http | `{"url": ""}` oppure `{"url": "https://..."}` |
| database | `host`, `port`, `database`, `user`, `password`, `query` |

La lettura verso la pagina toglie la password e mette `hasPassword: true`.

## queue_item

Memoria dell'ingresso. Una riga per coppia integrazione + id esterno (`UNIQUE`).

| Colonna | Significato |
|---|---|
| `external_id` | Valore della colonna identificativa, per esempio `WEB-77` |
| `payload_json` | Corpo arrivato dal sistema esterno |
| `mapped_json` | Corpo inviato a Espo, chiave inclusa |
| `hash` | SHA-256 esadecimale di `mapped_json` con chiavi ordinate |
| `status` | Oggi solo `synced`. Uno scarto non crea riga |
| `espo_id` | Id del record Espo |
| `detail` | `creato` o `aggiornato`, l'ultima azione che ha scritto |
| `updated_at` | Ora dell'ultima scrittura andata a buon fine |

Uno scarto (409 con un'altra chiave, campo mancante, Espo giù) non inserisce e non aggiorna la riga. Il record esterno resta «mai visto». Al giro dopo il motore riprova il POST.

`invariato` non è uno stato della tabella. È solo la risposta quando hash e `status = synced` coincidono. `detail` resta quello dell'ultima scrittura vera.

## sink_item

Appendice dell'uscita. Ogni record letto da Espo aggiunge una riga, anche se lo stesso record era già uscito in un giro precedente con un cursore resettato. Non c'è unicità. `espo_id` può essere vuoto se Espo non ha restituito `id`.

## cursor_state

Una riga per integrazione in uscita. `cursor_value` è l'ultimo `modifiedAt` osservato. Se nessun record letto contiene `modifiedAt`, il cursore non avanza e il giro successivo rilegge gli stessi record.

## delivery

Diario dell'uscita e della casella. Non ha unicità. Una esecuzione che invia tre lead scrive tre righe `inviato`. La casella, ricevendo quei POST, scrive tre righe `ricevuto` con `pipeline_id` nullo.

| status | Chi la scrive |
|---|---|
| `inviato` | il giro HTTP, dopo un POST andato a buon fine |
| `ricevuto` | `POST /inbox/{id}/{token}` |

Cancellare un'integrazione non cancella `delivery`. Cancellare un collegamento nemmeno. Le righe restano come diario.

## Slug

Il nome diventa id così: minuscolo, le lettere e le cifre restano, spazio trattino e underscore diventano `-`, i `--` si comprimono, taglio a 40 caratteri. Se il risultato è vuoto, l'id è `integrazione`. Se l'id esiste, si prova `{base}-2`, poi `-3`.

| Nome | Id |
|---|---|
| Clienti gestionale verso Account | `clienti-gestionale-verso-account` |
| File notturno | `file-notturno` |
| Lead verso portale | `lead-verso-portale` |

L'id entra nella chiave esterna. Rinominare creando una integrazione nuova cambia la chiave e quindi crea record Espo nuovi. Aggiornare la stessa riga via API, passando l'`id`, tiene la chiave.

## Seme

Solo a tabella `pipeline` vuota, tre righe:

| Id | Verso | Scheda | Note |
|---|---|---|---|
| `modulo-web` | in | Lead | `source` fisso `Web Site`, descrizione fissa. Senza collegamento |
| `anagrafica-clienti` | in | Account | scrive anche `cPartitaIva`. Senza collegamento |
| `uscita-lead` | out | Lead | mappa id, chiave, nome, email, source, `modifiedAt`. Senza collegamento |

Sono raggiungibili da `POST /api/ingest/modulo-web` e da `POST /api/pull/uscita-lead`. La pagina attuale, nel modulo «Nuova integrazione», pretende un collegamento: queste tre non si ricreano da lì.

## Cancellazioni

| Azione | Effetto |
|---|---|
| `DELETE /api/pipelines/{id}` | cancella la riga, `queue_item`, `sink_item`, `cursor_state` di quell'id. Non tocca Espo. I record creati nel CRM restano |
| `DELETE /api/connections/{id}` | mette `connection_id` a nullo sulle integrazioni che lo usavano, poi cancella il collegamento. Le integrazioni restano, senza canale. Un ingresso senza canale, alla prossima esecuzione, risponde che va collegato un sistema |

Non c'è conferma nella pagina. Il click su Elimina parte subito.
