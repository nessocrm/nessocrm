# Interfaccia

L'app ha più schermate, servite da `GET /` e scelte con l'indirizzo dopo il `#`. All'apertura, se non c'è ancora un ingresso, si crea chi cambia le integrazioni. Poi si entra con nome e password. Da Inizio, chi cambia aggiunge chi lancia i giri: quello vede «Esegui ora» e l'esito, e non vede Salva, Modifica, il foglio da caricare né l'interruttore delle scritture. Esci sta in fondo al menu. La lingua della pagina è l'italiano oppure l'inglese: la scelta sta nel menu, resta nel browser con la chiave `nesso-lang`, e le chiamate mandano `X-Nesso-Lang`. Se una frase non ha ancora la traduzione, resta in italiano. Il manuale è in italiano e in inglese. Il giornale già scritto e il badge già messo sul record non cambiano quando si cambia lingua: Origine Nesso usa la lingua del giro, e il pianificatore, che non ha una persona davanti, scrive in italiano. Il carattere è Inter. I colori sono quelli del tema Espo della prova: fondo pagina `#f1f3f5`, menu `#f4f5f7`, voce attiva `#dee1e7`, pulsante primario `#5589ca`.

Il menu è una barra a sinistra, larga 232 pixel, la stessa forma del menu laterale di Espo. In alto c'è il [marchio](14-marchio.md) e la parola Nesso. Poi Inizio, il gruppo Espo con Schede, il gruppo Integrazione, Collegamenti, Integrazioni, Attività. In fondo, EspoCRM apre il CRM in un'altra scheda, e una freccia riduce la barra alle sole icone. La scelta resta nel browser, chiave `nesso-nav`. Sotto i 760 pixel la barra si nasconde e si riapre dal pulsante in testa alla pagina.

| Indirizzo | Schermata |
|---|---|
| `#/` | Inizio. Titolo, stato di Espo, anagrafiche allineate, riquadri con i conteggi, pulsante per il passo successivo |
| `#/schede` | Elenco delle schede di Espo, con il nome tecnico e le integrazioni che le toccano |
| `#/schede/nuova` | Crea una scheda. Si indicano il singolare e il plurale |
| `#/schede/{nome}` | Campi della scheda e modulo per aggiungerne uno: etichetta, tipo, valori se è un elenco, obbligo |
| `#/collegamenti` | Elenco dei canali, una scheda per collegamento |
| `#/collegamenti/nuovo` | Modulo di un solo collegamento. Il tipo si sceglie con pulsanti radio e compaiono solo i campi di quel tipo. Il PDF sul cliente e il documento chiedono cartella documenti e team, entrambi facoltativi. Sull'HTTP in uscita c'è la consegna facoltativa della casella a un'altra integrazione |
| `#/collegamenti/modifica/{id}` | Lo stesso modulo, già compilato. Una password vuota non cancella quella salvata |
| `#/integrazioni` | Elenco delle integrazioni, con scheda, collegamento, cadenza ed esito. Da qui si esegue, si prova a secco, si modifica, si mette in pausa, si scarica e si carica la configurazione, e si scarica e si carica il foglio di abbinamento |
| `#/consegna` | Pagina da stampare: indirizzi, integrazioni accese, orario, padrone di ogni campo, come si ferma la scrittura. Non ci sono password né token |
| `#/integrazioni/nuova/1` … `/4` | Creazione in quattro passi, uno alla volta |
| `#/integrazioni/modifica/{id}/1` … `/4` | Gli stessi quattro passi, su un'integrazione già salvata |
| `#/attivita` | Passaggi riusciti, righe scartate, ultimi giri, contrasti, fasi proposte e l'export dei dati di una persona |

Ogni schermata ha un solo `h1`, nella fascia del titolo, con i pulsanti di quella schermata a destra. Cambiando schermata il focus va sul titolo, senza disegno intorno. Il link «Vai al contenuto» è il primo elemento della pagina. I campi hanno un'etichetta. Gli errori stanno in un `role="alert"`. Eliminare chiede conferma in una finestra di dialogo, con Annulla ed Elimina. Il passo corrente del menu ha `aria-current="page"`.

I quattro passi sono: nome e collegamento, scheda di Espo, abbinamento, cadenza e riepilogo. Indietro torna al passo precedente, anche con il tasto indietro del browser. Nell'abbinamento ogni riga è un gruppo con la sua legenda: colonna esterna, poi che cosa ne facciamo.

| Scelta | Effetto |
|---|---|
| Lo scriviamo in un campo | Il valore va in un campo scrivibile della scheda |
| Colleghiamo una scheda | Il valore identifica un record di un'altra scheda, e il legame è uno a uno |
| Colleghiamo più record | Nella cella ci sono più valori, separati da virgola |
| È un'attività appesa a una scheda | Il record è un'attività il cui padre è la scheda indicata |
| Questa riga è di un team e di una persona | Il team e l'assegnatario arrivano da una colonna o da un team fisso. Un utente non si crea |

In uscita la riga è più corta: un campo di Espo e il nome che riceve il sistema esterno.

Sul campo si sceglie anche la trasformazione e il padrone: la sorgente, anche se la cella è vuota, oppure Espo. Sul collegamento si sceglie che cosa fare se il record non c'è. Accanto alle colonne compaiono tre valori veri del file o della query. Due pulsanti, solo in ingresso, preparano l'abbinamento senza salvarlo: «Proponi l'abbinamento» legge i nomi delle colonne (in italiano o in inglese, secondo la lingua della pagina) e propone il campo Espo, compresa la partita IVA se la scheda ha un campo fiscale; una colonna non riconosciuta resta vuota, da compilare a mano. Accanto, se c'è una cella vera, si vede come verrebbe letta, data compresa. «Ricetta anagrafiche» compila una mappa per Account con codice, ragione sociale, partita IVA, email, telefono e città, sui campi che Espo ha già. «Ricetta contatti» compila Contact e collega l'azienda per nome. «Ricetta sedi» compila l'indirizzo di spedizione dell'Account, una sede per azienda. «Ricetta listino» compila il Product di Espo con descrizione, codice, prezzo e valuta, solo sui campi che ci sono già. Non è un connettore certificato con un gestionale. Si rivede e poi si salva. Sotto la colonna identità c'è «Altre colonne della chiave»: vuoto, la chiave resta una cella; con il codice società, la chiave mostrata è la concatenazione e, se il collegamento ha righe, se ne vedono fino a tre calcolate. L'ultimo passo ha la cadenza, l'orario fisso, l'integrazione da eseguire prima, la colonna di variazione del database, la politica sul duplicato e la casella «integrazione attiva».

Nell'elenco di ogni integrazione si legge il prossimo giro, l'ultimo successo insieme a da quanto tace, e l'ultimo errore. Il silenzio parte dall'ultimo successo.

In home c'è l'interruttore delle scritture e il riquadro delle anagrafiche: percentuale solo se il giro di oggi verso Account è riuscito, altrimenti la frase dice che non c'è ancora un successo oppure che quello di oggi non è riuscito. Se la quadratura non torna, o un file atteso non è stato elaborato, il riquadro ha il bordo rosso. Sull'integrazione gli stessi numeri stanno sotto l'esito. L'ultimo passo ha anche «file atteso entro», per esempio 07:00, «avvisa se tace da più di» un numero di minuti, e, in ingresso, la colonna dell'offerta: se è compilata, l'ordine propone la fase e non la scrive. In Attività si conferma o si lascia. Un giro fallito, o un silenzio oltre quei minuti, accende una riga in home, una volta, con il nome dell'integrazione.

Sulla scheda Espo compare Origine Nesso: «aggiornato dal gestionale» con data e ora, oppure «ultimo ritocco di» seguito dal nome. Non è una colonna del file.

Sull'integrazione: anteprima del giro, modalità lettura, annullamento, conferma delle chiusure. In fondo alla pagina ci sono il piano di accensione e la finestra di silenzio. Il piano elenca fino a tre integrazioni già salvate: si conferma un gradino solo dopo la sua anteprima, e il successivo resta spento finché non lo si riattiva. La finestra ha due date e un motivo, per una integrazione o per tutte. Se un file è arrivato in quei giorni, la scheda dice che è in attesa e offre conferma o scarto. In Attività il riepilogo del giro, la coda da guardare e il giornale, compresa l'assenza del file.

Sulla destinazione HTTP il modulo chiede l'autenticazione: nessuna, Bearer, utente e password, un'intestazione, oppure OAuth a credenziali client. Sul webhook il segreto della firma è facoltativo: vuoto, resta il token nell'indirizzo. La prova a secco di un webhook ha una casella per incollare un esempio. In Attività una riga scartata ha «Ripeti». Sulla scheda, l'etichetta di un campo creato da Nesso si cambia e il nome tecnico resta.
