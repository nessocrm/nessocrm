# Espo catalog and fields

The app does not have a list of our entities. It asks Espo what exists.

## Which entities enter the menu

`GET /api/v1/Metadata?key=scopes`.

An item enters if it is an object with `entity` true, without `disabled`, and with `object` and `tab` true. Entities in `CATALOG_ALSO` also enter without a tab: Team, Role, DocumentFolder, KnowledgeBaseCategory, EmailTemplate, Template, TargetListCategory, EmailTemplateCategory, Report, BpmnFlowchart. The label is `Global.scopeNames` of I18n `it_IT`, otherwise the technical name.

For each entity, `GET /api/v1/Metadata?key=entityDefs.{Name}.fields` and the same for `links`.

A field enters if the type is one of:

`varchar`, `text`, `enum`, `email`, `phone`, `int`, `float`, `bool`, `date`, `datetime`, `datetimeOptional`, `url`, `wysiwyg`, `multiEnum`, `currency`, `password`

and if it is not `readOnly` and not `disabled`. The label is, in order: the entity fields in `it_IT`, `Global.fields`, the technical name. Contact.firstName in this language is "Nominativo" because it is in the global fields.

Links enter the catalog and not the menu of simple fields. The page uses them in the mapping step.

| Type in the catalog | Espo link | On the page |
|---|---|---|
| `link` | belongsTo | Link an entity |
| `linkMultiple` | hasMany | Link several records. If the link exists only among links and not among fields, it still enters |
| `linkParent` | linkParent | It is an activity on an entity |
| `file` | file | Stays among the fields. The file is uploaded as `data:...;base64,...` on `Attachment`, then the id is written |

`cExternalKey` and `externalKey`, if present, enter with the fixed label "Chiave esterna", even if I18n said something else.

The list is sorted by label. The whole catalog is in memory for 120 seconds (`CATALOG`). `GET /api/catalog` returns it together with `espoPublicUrl`.

`keyField` of the entity is `externalKey` if `module == Custom` or `isCustom`, otherwise `cExternalKey`. It is the field the integration will use as the key, whatever the user maps.

If `scopes.{entity}.customizable` is false, the field is not created. The key stays in the engine `chiave` table and the links resolve it from there. That is the case of Team, DocumentFolder, KnowledgeBaseCategory, Role, EmailTemplate.

From the Entities screen the new field is not only text. The type can be text, long text, integer, number, date, date and time, yes/no, list, currency, email, phone or web address. A list carries its values. Required is sent to Espo together with the field.

## Creating the key field

On standard entities, Espo prefixes `c` and capitalises the next letter. The body must therefore be named `externalKey`. The API field that comes out is `cExternalKey`. Sending `cExternalKey` would create `cCExternalKey`. That name was created once during development and at startup the engine deletes it on Lead with:

```
DELETE /api/v1/Admin/fieldManager/Lead/cCExternalKey
```

Creation:

```
POST /api/v1/Admin/fieldManager/{Entity}
{
  "name": "externalKey",
  "type": "varchar",
  "label": "Chiave esterna",
  "maxLength": 180
}
```

200 or 201: created. 409, or a message that contains "exists": already present, that is fine. Anything else: startup marks `fields: errore` and the detail; the HTTP server is already up. Integrations that write will fail until the field exists.

At startup this happens for Lead and Account. `partitaIva` on Account becomes `cPartitaIva`, length 32, label "Partita IVA". It is not the key. It is a trial field for the customer master. The other entities receive `externalKey` when an inbound integration is saved on them. Contact received it that way. Saving clears the catalog cache.

An outbound integration does not create the field. If you map `cExternalKey` and the field does not exist, the save refuses it because it is not in the catalog ("unrecognised Espo fields"). That is the error seen the first time on "Lead verso portale", before the field was included among the selectable ones.

## What the save checks

`save_pipeline`:

- name not empty
- direction `in` or `out`
- entity not empty and present in the catalog
- inbound, identity column not empty
- at least one from/to pair, both not empty
- every Espo field (`to` inbound, `from` outbound) belongs to the catalog fields of that entity
- cadence 0, 5, 15 or 60, or a fixed time `scheduleAt` in the form 02:10
- if there is a connection, it exists and the direction matches the kind

The save keeps `copy`, `split_first`, `split_last`, `const:…`, `map` and `file`. A value map sits in `valueMap`. A phone field receives `kind: phone` and the Italian number becomes `+39…`. A link has `onMiss`: `fail`, `skip` or `create`. Saving an integration again does not recreate the lookup if exactly one toward that entity already exists. The key `{id}:{column}` is not rewritten if the identity column does not change.

Inbound, `key_template` is always rewritten as `{id}:{field}`. Another format cannot be chosen from the API. The seed has its own formats (`anagrafica:{codice}`, `modulo-web:{id}`) only because it did not pass through `save_pipeline`.

## Names the user sees and names Espo receives

| On the page | In the JSON toward Espo | In the table |
|---|---|---|
| Nominativo, Cognome, Email | `firstName`, `lastName`, `emailAddress` | standard columns |
| Account name | `name` | `account.name` |
| Partita IVA | `cPartitaIva` | custom field |
| External key | `cExternalKey` | custom field, varchar 180 |

The engine does not translate enum values. If an enum is mapped, the external string leaves as it is. If Espo does not recognise it, Espo's response becomes the record error. The `modulo-web` seed writes `source` with the constant `Web Site`, which is the internal value of that enum, not the Italian label.

## Authentication used for the metadata

The same `Espo-Authorization` of the local admin. The catalog sees what that user sees, and in this installation that user is an administrator. There is no user dedicated to the engine.
