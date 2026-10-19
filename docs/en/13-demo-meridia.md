# Gruppo Meridia demo

Gruppo Meridia is an invented industrial company. It designs, installs and maintains automation plants for factories. It has manufacturing customers, a partner network and the work that goes from the customer master to collection and support. It is not a real customer and it does not use data from a backup.

`docker compose up -d --build` installs an empty Espo and, when Espo is ready, loads this demo. The database integrations and the outbound run toward the portal repeat every 15 minutes. Requests from a file and from the site start once, at startup.

Espo: http://localhost:8088 (`admin` / `locale-admin`). Nesso: http://localhost:8091.

## The processes

| Process | Where it comes from | Entity |
|---|---|---|
| Customer masters | ERP, database | Account, type Customer |
| Suppliers and partners | ERP, database | Account, type Partner |
| People who decide and people who work on the shop floor | ERP, database | Contact, linked to the company |
| Sites and departments | ERP, database | Site, linked to the company |
| Requests from a fair, phone, email, partner | CSV file | Lead |
| Requests from the site configurator | Webhook | Lead |
| Open quotes | Sales, database | Opportunity (`COfferta`, Base Plus type), linked to company and contact |
| Framework contracts | ERP, database | Contract, linked to company and quote |
| Work orders | Job management, database | Job, linked to company and contract |
| Technician visits | Planning, database | Intervention, linked to job and contact |
| Invoices issued, paid, overdue | Finance, database | Invoice, linked to company and job |
| Support tickets | Helpdesk, database | Case, linked to company and contact |
| Visits and surveys | Calendar, CSV file | Meeting, linked to the company |
| Quotes published to the partner portal | HTTP outbound | the same Opportunity, toward the local inbox |

General accounting, the physical warehouse and payroll stay outside the CRM. In Meridia you see sales, the contract, the work, the invoice and the fault.

## Base Plus opportunity

Quotes do not stay on the standard Opportunity entity. At startup `demo/promuovi_offerta.py` creates `COfferta`, type Base Plus, labelled Opportunity. It has stage, amount, probability, close date, company, contact and documents, and the Activities, History and Tasks panels. Contracts point at this entity. The Opportunity item disappears from the menu.

## Management home

The admin preferences have the Direction dashboard: open pipeline by stage, open tickets by priority, quotes to close, visits on the calendar. They are Advanced Pack reports. Quote amounts are in euro.

## Organisation

After the processes, the same startup loads teams, people and documents. The roles are Sales, Support, Finance and Direction. Direction reads everything; on users it can edit only its own, because Espo does not allow "edit all" on User.

| Team | Who is in it | Sees |
|---|---|---|
| North-east sales | Chiara Fabbri | Customers and quotes of the north-east |
| Lombardy and south sales | Marco Pellizzari | Customers and quotes of Lombardy |
| Plant support | Elena Sartori | Tickets, interventions, articles |
| Finance | Davide Rinaldi | Contracts and invoices of their own team |
| Direction | Laura Merli, and also the admin | The whole set |

The five people sign in to Espo with password `locale-utente`. Chiara does not open a Lombardy customer: reading that record returns zero rows.

The eight PDFs are in `demo/documenti/`. They land on Document, in a folder (Quotes, Contracts, Data sheets), linked to the company and, when there is one, to the opportunity. There are also tasks on quotes and tickets, four calls, three knowledge articles, the MECSPE invitation list and the campaign of the same name, two email templates. Contacts of the list are attached after creation: Espo refuses the contact list in the body of the list.

Teams, folders, categories and email templates do not accept a key field. The key of those records lives in the engine `chiave` table.

## Where the data is

The `meridia_erp` database is created on the same MariaDB as the trial. The schema and the process rows are in `demo/meridia.sql`. Teams, users and documents are in `demo/meridia-organizzazione.sql`. The CSV files are in `demo/csv/`. The PDFs are in `demo/documenti/`. The site body is in `demo/webhook/richieste-sito.json`.

To rebuild the demo from scratch, stop the containers and delete the volumes of this compose, then start again. The volumes keep Espo and the configuration that was already loaded.
