# Catalogo Espo e campi

L'app non ha una lista di schede Enostra. Chiede a Espo che cosa esiste.

## Quali schede entrano nel menu

`GET /api/v1/Metadata?key=scopes`.

Una voce entra se è un oggetto con `entity` vero, senza `disabled`, e con `object` e `tab` veri. Entrano anche senza tab le schede di `CATALOG_ALSO`: Team, Role, DocumentFolder, KnowledgeBaseCategory, EmailTemplate, Template, TargetListCategory, EmailTemplateCategory, Report, BpmnFlowchart. L'etichetta è `Global.scopeNames` di I18n `it_IT`, altrimenti il nome tecnico.

Per ogni scheda, `GET /api/v1/Metadata?key=entityDefs.{Nome}.fields` e lo stesso per `links`.

Un campo entra se il tipo è uno di:

`varchar`, `text`, `enum`, `email`, `phone`, `int`, `float`, `bool`, `date`, `datetime`, `datetimeOptional`, `url`, `wysiwyg`, `multiEnum`, `currency`, `password`

e se non è `readOnly` e non è `disabled`. L'etichetta è, in ordine: campi della scheda in `it_IT`, campi `Global.fields`, nome tecnico. Contact.firstName in questa lingua è «Nominativo» perché sta nei campi globali.

I collegamenti entrano nel catalogo e non nel menu dei campi semplici. La pagina li usa nel passo di abbinamento.

| Tipo nel catalogo | Legame Espo | Nella pagina |
|---|---|---|
| `link` | belongsTo | Colleghiamo una scheda |
| `linkMultiple` | hasMany | Colleghiamo più record. Se il collegamento c'è solo fra i link e non fra i campi, entra lo stesso |
| `linkParent` | linkParent | È un'attività appesa a una scheda |
| `file` | file | Resta fra i campi. Il file si carica come `data:...;base64,...` su `Attachment`, poi si scrive l'id |

`cExternalKey` e `externalKey`, se presenti, entrano con l'etichetta fissa «Chiave esterna», anche se I18n dicesse altro.

L'elenco è ordinato per etichetta. Il catalogo intero è in memoria 120 secondi (`CATALOG`). `GET /api/catalog` lo restituisce insieme a `espoPublicUrl`.

`keyField` della scheda è `externalKey` se `module == Custom` o `isCustom`, altrimenti `cExternalKey`. È il campo che l'integrazione userà come chiave, indipendentemente da ciò che l'utente abbina.

Se `scopes.{scheda}.customizable` è falso, il campo non si crea. La chiave resta nella tabella `chiave` del motore e i collegamenti la risolvono da lì. È il caso di Team, DocumentFolder, KnowledgeBaseCategory, Role, EmailTemplate.

Dalla schermata Schede il campo nuovo non è solo testo. Il tipo può essere testo, testo lungo, intero, numero, data, data e ora, sì/no, elenco, valuta, email, telefono o indirizzo web. L'elenco porta i suoi valori. L'obbligo si manda a Espo insieme al campo.

## Creare il campo chiave

Espo, sulle schede standard, antepone `c` e mette in maiuscolo la lettera successiva. Il body deve quindi chiamarsi `externalKey`. Il campo API che ne esce è `cExternalKey`. Mandare `cExternalKey` farebbe creare `cCExternalKey`. Quel nome è stato creato una volta durante lo sviluppo e all'avvio il motore lo cancella su Lead con:

```
DELETE /api/v1/Admin/fieldManager/Lead/cCExternalKey
```

Creazione:

```
POST /api/v1/Admin/fieldManager/{Scheda}
{
  "name": "externalKey",
  "type": "varchar",
  "label": "Chiave esterna",
  "maxLength": 180
}
```

200 o 201: creato. 409, oppure un messaggio che contiene «exists»: già presente, va bene. Altro: l'avvio segna `fields: errore` e il dettaglio; il server HTTP però è già su. Le integrazioni che scrivono falliranno finché il campo non c'è.

All'avvio questo avviene per Lead e Account. `partitaIva` su Account diventa `cPartitaIva`, lunghezza 32, etichetta «Partita IVA». Non è la chiave. È un campo di prova per l'anagrafica. Le altre schede ricevono `externalKey` al momento in cui si salva un'integrazione in ingresso su di loro. Contact l'ha ricevuto così. Il salvataggio azzera la cache del catalogo.

Un'integrazione in uscita non crea il campo. Se si abbina `cExternalKey` e il campo non esiste, il salvataggio lo rifiuta perché non è nel catalogo («campi Espo non riconosciuti»). È l'errore visto la prima volta su «Lead verso portale», prima che il campo fosse incluso fra i selezionabili.

## Che cosa il salvataggio controlla

`save_pipeline`:

- nome non vuoto
- direzione `in` o `out`
- scheda non vuota e presente nel catalogo
- in ingresso, colonna identificativa non vuota
- almeno una coppia from/to entrambi non vuoti
- ogni campo Espo (`to` in ingresso, `from` in uscita) appartiene ai campi del catalogo per quella scheda
- cadenza 0, 5, 15 o 60, oppure un orario fisso `scheduleAt` nel formato 02:10
- se c'è un collegamento, esiste e il verso coincide col kind

Il salvataggio conserva `copy`, `split_first`, `split_last`, `const:…`, `map` e `file`. Una mappa valori sta in `valueMap`. Un campo telefono riceve `kind: phone` e il numero italiano diventa `+39…`. Un collegamento ha `onMiss`: `fail`, `skip` o `create`. Risalvare un'integrazione non ricrea il lookup se verso quella scheda ne esiste già uno solo. La chiave `{id}:{colonna}` non viene riscritta se la colonna identità non cambia.

In ingresso il `key_template` viene sempre riscritto come `{id}:{campo}`. Non si può scegliere un altro formato dalla API. Il seme ha formati propri (`anagrafica:{codice}`, `modulo-web:{id}`) solo perché non è passato da `save_pipeline`.

## Nomi che l'utente vede e nomi che Espo riceve

| In pagina | Nel JSON verso Espo | In tabella |
|---|---|---|
| Nominativo, Cognome, Email | `firstName`, `lastName`, `emailAddress` | colonne standard |
| Nome account | `name` | `account.name` |
| Partita IVA | `cPartitaIva` | campo custom |
| Chiave esterna | `cExternalKey` | campo custom, varchar 180 |

Il motore non traduce i valori degli enum. Se si abbina un enum, parte la stringa esterna così com'è. Se Espo non la riconosce, la risposta di Espo diventa l'errore del record. Il seme `modulo-web` scrive `source` con la costante `Web Site`, che è il valore interno di quell'enum, non l'etichetta italiana.

## Autenticazione usata per il metadata

La stessa `Espo-Authorization` dell'admin locale. Il catalogo vede quello che vede quell'utente, che in questa installazione è amministratore. Non c'è un utente dedicato al motore.
