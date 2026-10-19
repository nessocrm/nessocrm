# Adoption

Functions that would make a company choose Nesso. This is not the technical list: that is in [Project](00-progetto.md), among the open items. Here there is only what removes a real fear: losing a customer, overwriting a note, not trusting the number, not knowing how to switch everything off.

None of this is in the engine, except what is already archived in the Project chapter. An item leaves this page when it is built.

## Who has to say yes

| Who | Fear | What convinces them |
|---|---|---|
| Owner | The CRM and the ERP do not match | One number: accounts in sync, and the balance of the totals |
| Sales | The night run deletes what they wrote yesterday | The field has an owner, and you can see who wrote last |
| Finance | A bad file closes customers or creates duplicates | The preview, a VAT number already present, undoing the run |
| Whoever installs Espo at the customer | It takes weeks and then they cannot hand it over | A recipe, a switch-on plan, a handover page |

The home number, the balance, the expected file, the badge on the record, the mapping proposal and the accounts recipe are already in the engine.

## Switch on without a project

- **Site and contact recipes.** The customer master is already there. What remains are the layouts ERPs already produce for sites and contacts: a ready mapping to review, not a certified connector.
- **Several companies in the same file.** The key is company code plus customer code. A group with three legal names does not mix its customers.
- **Switch-on plan.** First read-only on the accounts. Then writing the accounts. Then the contacts. Each step has its own preview and turns itself on only if the previous one was confirmed.
- **Quiet window.** A calendar: do not write during the books close, an inventory, a fair. A file that arrives on those days waits.

## Sales believes it

- **The price list is Espo's Product.** Code, description, price, currency. No invented entity. The quote reads prices that already exist in Espo.
- **The order proposes the stage.** If the ERP shows an order for that quote, Nesso proposes "closed won". The person confirms. The stage does not move on its own.
- **The PDF with the customer code attaches itself.** A file whose name contains the company key lands on the right customer, in the right folder, visible to the right team.

## Whoever installs and then leaves

- **Handover page.** Addresses of Nesso and of Espo, the list of integrations that are on, the owner of each field, how to stop every write, what time the run starts. It is printed and left with the customer.
- **A sheet instead of JSON.** The mapping is downloaded as a sheet the office can read, and uploaded again. JSON stays for whoever moves the configuration between trial and production.
- **Export one person's data.** On request, a file of what Nesso wrote on that contact and that company. It is the gesture for the privacy owner. It is not the close of a record that disappeared from the source: that close keeps the history.

## Order, if the goal is adoption

1. Switch-on plan, quiet window, several companies in the same file. Then the site and contact recipes.
2. Handover page and mapping sheet.
3. Price list, PDF on the customer, stage proposed by the order, export for privacy.
