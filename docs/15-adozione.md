# Adozione

Funzioni che farebbero scegliere Nesso a un'azienda. Non sono l'elenco tecnico: quello sta in [Progetto](00-progetto.md), fra le voci aperte. Qui c'è solo ciò che toglie una paura vera: perdere un cliente, sovrascrivere una nota, non fidarsi del numero, non sapere se spegnere tutto.

Niente di questo è nel motore. Una voce esce da qui quando è costruita, e si archivia nel capitolo Progetto.

## Chi deve dire sì

| Chi | Paura | Che cosa lo convince |
|---|---|---|
| Titolare | Il CRM e il gestionale non tornano | Un numero solo: anagrafiche allineate, e la quadratura dei totali |
| Commerciale | Il giro di notte cancella quello che ha scritto ieri | Il campo ha un padrone, e si vede chi ha scritto per ultimo |
| Amministrazione | Un file storto chiude clienti o ne crea doppi | L'anteprima, la partita IVA già presente, l'annullamento del giro |
| Chi installa Espo dal cliente | Ci mette settimane e poi non sa consegnare | Una ricetta, un piano di accensione, una pagina di consegna |

## Fiducia prima della scrittura

- **Anagrafiche allineate, in home.** Una percentuale e l'ora dell'ultimo giro riuscito. È il numero che il titolare guarda la mattina.
- **Quadratura.** Conteggio clienti e totale importi, lato sorgente e lato Espo, affiancati. Se non tornano, il giro si vede rosso prima che qualcuno lo scopra in riunione.
- **Diff della riga pericolosa.** Oltre al conteggio di create, aggiornate e chiuse: le righe che toccherebbero un campo compilato a mano, con il valore di oggi e quello in arrivo.
- **Annulla il giro.** Un giro delle 02:10 si può disfare. Si ripristinano solo i campi che quel giro ha scritto. Le note scritte dopo, dalle persone, restano.
- **Storico dei valori scritti da Nesso.** È la base dell'annullamento: per ogni campo toccato, il valore precedente e l'ora.
- **Coda «da guardare».** Se il padrone del campo è Espo e la sorgente porta un valore diverso, la riga non si sovrascrive in silenzio. Finisce in un elenco, con i due valori, e una persona sceglie.
- **Partita IVA già presente.** Lo stesso codice fiscale o la stessa partita IVA è già un'azienda in Espo, con un'altra chiave. Nesso non crea il secondo cliente. Lo segnala.
- **Modalità lettura.** Per un periodo scelto, per esempio 48 ore, Nesso calcola tutto e non scrive. Si esce dalla modalità con un gesto esplicito.

## Accendere senza un progetto

- **Proposta di abbinamento.** Dai nomi delle colonne, in italiano: ragione sociale, partita IVA, email, telefono, città. Nesso propone il campo Espo. La persona conferma. Non scrive da sola.
- **Tre formati di data riconosciuti in proposta.** `18/10/2026`, `2026-10-18`, `18-10-2026`. La proposta mostra come verrebbe letta la cella, sulla riga vera.
- **Ricette di export.** Layout di file che i gestionali già sanno produrre: anagrafiche, sedi, contatti. Una ricetta è un abbinamento pronto da rivedere, non un connettore certificato con quel gestionale.
- **Più società nello stesso file.** La chiave è codice società più codice cliente. Un gruppo con tre ragioni sociali non mescola i clienti.
- **Piano di accensione.** Prima solo lettura sulle anagrafiche. Poi scrittura delle anagrafiche. Poi i contatti. Ogni gradino ha la sua anteprima e si accende da solo solo se il precedente è stato confermato.
- **Finestra di silenzio.** Un calendario: non scrivere durante la chiusura contabile, un inventario, una fiera. Il file che arriva in quei giorni resta in attesa.
- **File atteso che non arriva.** Se alle 07:00 il file della notte non c'è, la home è rossa. Non si scopre a mezzogiorno che le anagrafiche sono quelle di ieri.

## Il commerciale ci crede

- **Badge sul record.** In Espo, sulla scheda: «aggiornato dal gestionale il 18/10 alle 02:12» oppure «ultimo ritocco di Chiara». Senza questo, il commerciale non si fida e si tiene il foglio.
- **Il listino è il Product di Espo.** Codice, descrizione, prezzo, valuta. Nessuna scheda inventata. L'offerta legge prezzi che esistono già in Espo.
- **L'ordine propone la fase.** Se nel gestionale compare un ordine per quell'offerta, Nesso propone «chiusa vinta». La persona conferma. La fase non scatta da sola.
- **Il PDF col codice cliente si attacca da solo.** Un file il cui nome contiene la chiave dell'azienda finisce sul cliente giusto, nella cartella giusta, visibile al team giusto.

## Chi installa e poi se ne va

- **Pagina di consegna.** Indirizzi di Nesso e di Espo, elenco delle integrazioni accese, padrone di ogni campo, come si ferma ogni scrittura, a che ora parte il giro. Si stampa e si lascia al cliente.
- **Foglio al posto del JSON.** L'abbinamento si scarica in un foglio che l'amministrazione sa leggere e si ricarica. Il JSON resta per chi sposta la configurazione fra prova e esercizio.
- **Esporta i dati di una persona.** Su richiesta, un file con ciò che Nesso ha scritto su quel contatto e su quell'azienda. È il gesto per il responsabile della privacy. Non è la chiusura del record sparito dalla sorgente: quella lascia lo storico.

## In che ordine, se l'obiettivo è l'adozione

1. Modalità lettura, diff della riga pericolosa, partita IVA già presente, annulla il giro.
2. Numero in home, quadratura, file atteso che non arriva, badge sul record.
3. Proposta di abbinamento e una ricetta di anagrafiche.
4. Piano di accensione, finestra di silenzio, più società nello stesso file.
5. Pagina di consegna e foglio di abbinamento.
6. Listino, PDF sul cliente, fase proposta dall'ordine, export per la privacy.
