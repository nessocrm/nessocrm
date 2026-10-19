# Adozione

Funzioni che farebbero scegliere Nesso a un'azienda. Non sono l'elenco tecnico: quello sta in [Progetto](00-progetto.md), fra le voci aperte. Qui c'è solo ciò che toglie una paura vera: perdere un cliente, sovrascrivere una nota, non fidarsi del numero, non sapere se spegnere tutto.

Niente di questo è nel motore, salvo ciò che è già archiviato nel capitolo Progetto. Una voce esce da qui quando è costruita.

## Chi deve dire sì

| Chi | Paura | Che cosa lo convince |
|---|---|---|
| Titolare | Il CRM e il gestionale non tornano | Un numero solo: anagrafiche allineate, e la quadratura dei totali |
| Commerciale | Il giro di notte cancella quello che ha scritto ieri | Il campo ha un padrone, e si vede chi ha scritto per ultimo |
| Amministrazione | Un file storto chiude clienti o ne crea doppi | L'anteprima, la partita IVA già presente, l'annullamento del giro |
| Chi installa Espo dal cliente | Ci mette settimane e poi non sa consegnare | Una ricetta, un piano di accensione, una pagina di consegna |

Il numero in home, la quadratura, il file atteso, il badge sul record, la proposta di abbinamento e la ricetta di anagrafiche sono già nel motore.

## Accendere senza un progetto

- **Ricette di sedi e contatti.** L'anagrafica clienti c'è già. Restano i layout che i gestionali producono per sedi e contatti: un abbinamento pronto da rivedere, non un connettore certificato.
- **Più società nello stesso file.** La chiave è codice società più codice cliente. Un gruppo con tre ragioni sociali non mescola i clienti.
- **Piano di accensione.** Prima solo lettura sulle anagrafiche. Poi scrittura delle anagrafiche. Poi i contatti. Ogni gradino ha la sua anteprima e si accende da solo solo se il precedente è stato confermato.
- **Finestra di silenzio.** Un calendario: non scrivere durante la chiusura contabile, un inventario, una fiera. Il file che arriva in quei giorni resta in attesa.

## Il commerciale ci crede

- **Il listino è il Product di Espo.** Codice, descrizione, prezzo, valuta. Nessuna scheda inventata. L'offerta legge prezzi che esistono già in Espo.
- **L'ordine propone la fase.** Se nel gestionale compare un ordine per quell'offerta, Nesso propone «chiusa vinta». La persona conferma. La fase non scatta da sola.
- **Il PDF col codice cliente si attacca da solo.** Un file il cui nome contiene la chiave dell'azienda finisce sul cliente giusto, nella cartella giusta, visibile al team giusto.

## Chi installa e poi se ne va

- **Pagina di consegna.** Indirizzi di Nesso e di Espo, elenco delle integrazioni accese, padrone di ogni campo, come si ferma ogni scrittura, a che ora parte il giro. Si stampa e si lascia al cliente.
- **Foglio al posto del JSON.** L'abbinamento si scarica in un foglio che l'amministrazione sa leggere e si ricarica. Il JSON resta per chi sposta la configurazione fra prova e esercizio.
- **Esporta i dati di una persona.** Su richiesta, un file con ciò che Nesso ha scritto su quel contatto e su quell'azienda. È il gesto per il responsabile della privacy. Non è la chiusura del record sparito dalla sorgente: quella lascia lo storico.

## In che ordine, se l'obiettivo è l'adozione

1. Piano di accensione, finestra di silenzio, più società nello stesso file. Poi le ricette di sedi e contatti.
2. Pagina di consegna e foglio di abbinamento.
3. Listino, PDF sul cliente, fase proposta dall'ordine, export per la privacy.
