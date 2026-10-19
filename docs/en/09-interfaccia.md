# Interface

The app has several screens, served by `GET /` and chosen with the address after `#`. There is no login. The page language is Italian or English: the choice is in the menu, stays in the browser with the key `nesso-lang`, and the calls send `X-Nesso-Lang`. If a sentence does not have a translation yet, it stays in Italian. The manual is in Italian and in English. A journal row already written, and a badge already put on the record, do not change when the language changes: Nesso origin uses the language of the run, and the scheduler, which has no person in front of it, writes in Italian. The typeface is Inter. The colours are those of the trial Espo theme: page background `#f1f3f5`, menu `#f4f5f7`, active item `#dee1e7`, primary button `#5589ca`.

The menu is a bar on the left, 232 pixels wide, the same shape as the Espo side menu. At the top is the [mark](14-marchio.md) and the word Nesso. Then Home, the Espo group with Entities, the Integration group, Connections, Integrations, Activity. At the bottom, EspoCRM opens the CRM in another tab, and an arrow reduces the bar to icons only. The choice stays in the browser, key `nesso-nav`. Below 760 pixels the bar hides and opens again from the button at the top of the page.

| Address | Screen |
|---|---|
| `#/` | Home. Title, Espo status, accounts in sync, count tiles, button for the next step |
| `#/schede` | List of Espo entities, with the technical name and the integrations that touch them |
| `#/schede/nuova` | Creates an entity. Singular and plural are entered |
| `#/schede/{nome}` | Fields of the entity and a form to add one: label, type, values if it is a list, required |
| `#/collegamenti` | List of channels, one card per connection |
| `#/collegamenti/nuovo` | Form of a single connection. The type is chosen with radio buttons and only the fields of that type appear. PDF on the customer asks for a document folder and a team, both optional |
| `#/collegamenti/modifica/{id}` | The same form, already filled. An empty password does not clear the saved one |
| `#/integrazioni` | List of integrations, with entity, connection, cadence and result. From here you run, dry-run, edit, pause, download and upload the configuration, and download and upload the mapping sheet |
| `#/consegna` | Page to print: addresses, integrations that are on, schedule, owner of each field, how to stop writes. There are no passwords and no tokens |
| `#/integrazioni/nuova/1` … `/4` | Creation in four steps, one at a time |
| `#/integrazioni/modifica/{id}/1` … `/4` | The same four steps, on an integration that is already saved |
| `#/attivita` | Successful rows, rejected rows, latest runs, contrasts, proposed stages and the export of one person's data |

Every screen has a single `h1`, in the title band, with that screen's buttons on the right. Changing screen moves the focus to the title, with no outline. The "Skip to content" link is the first element of the page. Fields have a label. Errors sit in a `role="alert"`. Delete asks for confirmation in a dialog, with Cancel and Delete. The current menu item has `aria-current="page"`.

The four steps are: name and connection, Espo entity, mapping, cadence and review. Back returns to the previous step, including the browser back button. In the mapping each row is a group with its own legend: external column, then what we do with it.

| Choice | Effect |
|---|---|
| Write it to a field | The value goes into a writable field of the entity |
| Link an entity | The value identifies a record of another entity, and the link is one to one |
| Link several records | The cell holds several values, separated by a comma |
| It is an activity on an entity | The record is an activity whose parent is the named entity |
| This row belongs to a team and a person | The team and the assignee come from a column or from a fixed team. A user is not created |

Outbound, the row is shorter: an Espo field and the name the external system receives.

On the field you also choose the transform and the owner: the source, even when the cell is empty, or Espo. On the link you choose what to do if the record is missing. Next to the columns, three real values from the file or the query appear. Two buttons, inbound only, prepare the mapping without saving it: "Propose the mapping" reads the column names (in Italian or in English, following the page language) and proposes the Espo field, including VAT if the entity has a fiscal field; an unrecognised column stays empty, to be filled by hand. Next to it, if there is a real cell, you see how it would be read, date included. "Accounts recipe" fills a map for Account with code, company name, VAT, email, phone and city, on the fields Espo already has. "Contacts recipe" fills Contact and links the company by name. "Sites recipe" fills the Account shipping address, one site per company. "Price list recipe" fills Espo's Product with description, code, price and currency, only on the fields that are already there. It is not a certified connector for a named ERP. You review it and then save. Under the identity column there is "Other key columns": empty, the key stays one cell; with the company code, the key shown is the concatenation and, if the connection has rows, up to three calculated ones are shown. The last step has the cadence, the fixed time, the integration to run first, the database change column, the duplicate policy and the "integration on" box.

On home there is the writes switch and the accounts panel: a percent only if today's run toward Account succeeded, otherwise the sentence says there is no success yet or that today's run did not succeed. If the balance does not match, or an expected file has not been processed, the panel has a red border. On the integration the same numbers sit under the result. The last step also has "file expected by", for example 07:00, and, inbound, the offer column: if it is filled, the order proposes the stage and does not write it. In Activity you confirm it or leave it.

On the Espo record, Nesso origin appears: "updated from the ERP" with date and time, or "last edit by" followed by the name. It is not a column of the file.

On the integration: preview of the run, read mode, undo, confirmation of closes. At the bottom of the page are the switch-on plan and the quiet window. The plan lists up to three integrations already saved: a step is confirmed only after its preview, and the next one stays off until you resume it. The window has two dates and a reason, for one integration or for all. If a file arrived on those days, the card says it is waiting and offers confirm or discard. In Activity, the run summary, the review queue and the journal, including a missing file.

On the HTTP destination the form asks for authentication: none, Bearer, user and password, or a header.
