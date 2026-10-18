# Interfaccia

L'app ha più schermate, servite da `GET /` e scelte con l'indirizzo dopo il `#`. Non c'è login. La lingua è l'italiano. Il carattere è Inter. I colori sono quelli del tema Espo della prova: fondo pagina `#f1f3f5`, menu `#f4f5f7`, voce attiva `#dee1e7`, pulsante primario `#5589ca`.

Il menu è una barra a sinistra, larga 232 pixel, la stessa forma del menu laterale di Espo. In alto c'è il [marchio](14-marchio.md) e la parola Nesso. Poi Inizio, il gruppo Espo con Schede, il gruppo Integrazione, Collegamenti, Integrazioni, Attività. In fondo, EspoCRM apre il CRM in un'altra scheda, e una freccia riduce la barra alle sole icone. La scelta resta nel browser, chiave `nesso-nav`. Sotto i 760 pixel la barra si nasconde e si riapre dal pulsante in testa alla pagina.

| Indirizzo | Schermata |
|---|---|
| `#/` | Inizio. Titolo, stato di Espo, riquadri con i conteggi, pulsante per il passo successivo |
| `#/schede` | Elenco delle schede di Espo, con il nome tecnico e le integrazioni che le toccano |
| `#/schede/nuova` | Crea una scheda. Si indicano il singolare e il plurale |
| `#/schede/{nome}` | Campi della scheda e modulo per aggiungerne uno: etichetta, tipo, valori se è un elenco, obbligo |
| `#/collegamenti` | Elenco dei canali, una scheda per collegamento |
| `#/collegamenti/nuovo` | Modulo di un solo collegamento. Il tipo si sceglie con pulsanti radio e compaiono solo i campi di quel tipo |
| `#/collegamenti/modifica/{id}` | Lo stesso modulo, già compilato. Una password vuota non cancella quella salvata |
| `#/integrazioni` | Elenco delle integrazioni, con scheda, collegamento, cadenza ed esito. Da qui si esegue, si prova a secco, si modifica, si mette in pausa, si scarica e si carica la configurazione |
| `#/integrazioni/nuova/1` … `/4` | Creazione in quattro passi, uno alla volta |
| `#/integrazioni/modifica/{id}/1` … `/4` | Gli stessi quattro passi, su un'integrazione già salvata |
| `#/attivita` | Tre tabelle: passaggi riusciti, righe scartate, ultimi giri |

Ogni schermata ha un solo `h1`, nella fascia del titolo, con i pulsanti di quella schermata a destra. Cambiando schermata il focus va sul titolo, senza disegno intorno. Il link «Vai al contenuto» è il primo elemento della pagina. I campi hanno un'etichetta. Gli errori stanno in un `role="alert"`. Eliminare chiede conferma in una finestra di dialogo, con Annulla ed Elimina. Il passo corrente del menu ha `aria-current="page"`.

I quattro passi sono: nome e collegamento, scheda di Espo, abbinamento, cadenza e riepilogo. Indietro torna al passo precedente, anche con il tasto indietro del browser. Nell'abbinamento ogni riga è un gruppo con la sua legenda: colonna esterna, poi che cosa ne facciamo.

| Scelta | Effetto |
|---|---|
| Lo scriviamo in un campo | Il valore va in un campo scrivibile della scheda |
| Colleghiamo una scheda | Il valore identifica un record di un'altra scheda, e il legame è uno a uno |
| Colleghiamo più record | Nella cella ci sono più valori, separati da virgola |
| È un'attività appesa a una scheda | Il record è un'attività il cui padre è la scheda indicata |

In uscita la riga è più corta: un campo di Espo e il nome che riceve il sistema esterno.

Sul campo si sceglie anche la trasformazione: copia, prima parola, resto del testo, valore fisso, mappa dei valori. Sul collegamento si sceglie che cosa fare se il record non c'è. L'ultimo passo ha la cadenza, l'integrazione da eseguire prima, la colonna di variazione del database, la politica sul duplicato e la casella «integrazione attiva».

Sulla destinazione HTTP il modulo chiede l'autenticazione: nessuna, Bearer, utente e password, oppure un'intestazione.
