# Interfaccia

L'app ha più schermate, servite da `GET /` e scelte con l'indirizzo dopo il `#`. Non c'è login. La lingua è l'italiano. Il menu in alto è sempre lo stesso: Inizio, Collegamenti, Integrazioni, Attività, Apri Espo.

| Indirizzo | Schermata |
|---|---|
| `#/` | Inizio. Due frasi, il conteggio, il passo successivo |
| `#/collegamenti` | Elenco dei canali, una scheda per collegamento |
| `#/collegamenti/nuovo` | Modulo di un solo collegamento. Il tipo si sceglie con pulsanti radio e compaiono solo i campi di quel tipo |
| `#/integrazioni` | Elenco delle integrazioni, con scheda, collegamento, cadenza ed esito scritti per esteso |
| `#/integrazioni/nuova/1` … `/4` | Creazione in quattro passi, uno alla volta |
| `#/attivita` | Tabella degli ultimi passaggi, con didascalia |

Ogni schermata ha un solo `h1`. Cambiando schermata il focus va sul titolo. Il link «Vai al contenuto» è il primo elemento della pagina. I campi hanno un'etichetta. Gli errori stanno in un `role="alert"`. Eliminare chiede conferma in una finestra di dialogo, con Annulla ed Elimina. Il passo corrente del menu ha `aria-current="page"` e un fondo bianco.

I quattro passi sono: nome e collegamento, scheda di Espo, abbinamento, cadenza e riepilogo. Indietro torna al passo precedente, anche con il tasto indietro del browser. Nell'abbinamento ogni riga è un gruppo con la sua legenda: colonna esterna, scelta fra «scrivere in un campo» e «collegare un'altra scheda», poi i campi di quella scelta.
