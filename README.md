<p align="center">
  <img src="logo.svg" alt="NeoPill" width="480">
</p>

# NeoPill

Integrazione custom per Home Assistant (compatibile [HACS](https://hacs.xyz)) per la gestione dei farmaci
di uno o più pazienti: assunzioni, scorte, rifornimenti e promemoria dose, con un calendario nativo HA per
paziente e un dispositivo HA per ogni farmaco.

> Stato: in sviluppo (v0.1.0). Le funzionalità descritte qui sotto sono il target della v1.

## Funzionalità

- Gestione multi-paziente. Ogni paziente ha un device hub **"‹Nome› NeoPill"** che raccoglie le entità
  trasversali (calendario, sensore farmaci-da-rifornire, pulsanti raggruppati per ora di assunzione) ed è
  il "genitore" (via_device) dei device dei suoi farmaci.
- Ogni farmaco è un dispositivo HA a sé, nominato `"‹Farmaco› (‹Paziente›)"`, con entità per scorta,
  prossima assunzione, giorni di scorta rimanenti, stato "da assumere" e stato "scorta in esaurimento". Due
  pazienti diversi con un farmaco dallo stesso nome restano completamente indipendenti (scorte, orari,
  storico separati, device ed entity_id distinti).
- **entity_id sempre prefissati con il paziente** (prime 3 consonanti del nome, es. `mrr` per "Mario
  Rossi", con gestione automatica delle collisioni) — calcolati una sola volta alla creazione del paziente
  e stabili nel tempo anche se lo rinomini dopo, per non rompere automazioni/dashboard.
- Eliminando un paziente vengono rimossi automaticamente tutti i suoi farmaci, il calendario e le altre
  entità collegate (cancellazione a cascata tramite il device hub del paziente).
- Dosaggio a orari fissi al giorno, a giorni della settimana con orari indipendenti giorno per giorno (es.
  martedì e venerdì, con orari diversi tra loro), oppure a intervallo dall'ultima assunzione — con dose
  anche frazionaria (es. 1/2, 1/4).
- Rifornimento per quantità diretta o per numero di confezioni.
- **Pulsanti raggruppati per ora di assunzione**: per ogni orario fisso in comune tra i farmaci di un
  paziente vengono creati automaticamente due pulsanti — "Assumi tutti ore HH:MM" e "Segna tutti non
  assunti ore HH:MM" — che agiscono in un colpo solo su tutti i farmaci di quel paziente previsti a
  quell'orario. Creati/rimossi automaticamente quando aggiungi, modifichi o elimini un farmaco.
- Tutta la gestione (pazienti, farmaci, assunzioni, rifornimenti) avviene da un pannello dedicato nella
  sidebar di Home Assistant, separato da Lovelace.
- Servizi Home Assistant (`neopill.assumi_farmaco`, `neopill.segna_non_assunta`, `neopill.rifornisci_farmaco`)
  per l'uso da automazioni.
- **Finestra ideale di riordino, per paziente**: due soglie (giorni minimi/massimi) editabili direttamente
  dalla toolbar del pannello, pensate per raggruppare più farmaci possibile in un'unica commissione —
  minimi = non aspettare oltre (rischio di rimanere senza), massimi = non troppo presto (rischio di
  rifiuto del medico per prescrizione anticipata). Il sensore per paziente
  `sensor.‹slug›_restock_reminder` elenca i farmaci il cui "giorni rimanenti" rientra in quella
  finestra, con un testo già formattato pronto per una notifica/email (vedi sotto) e, per ciascun farmaco,
  la data di esaurimento prevista.

## Installazione

### Tramite HACS (repository personalizzata)

1. HACS → menu (⋮) → **Repository personalizzate** → aggiungi l'URL di questo repository, categoria
   "Integrazione".
2. Installa "NeoPill" dall'elenco HACS.
3. Riavvia Home Assistant.
4. Impostazioni → Dispositivi e servizi → Aggiungi integrazione → **NeoPill**.

### Manuale

Copia la cartella `custom_components/neopill` nella cartella `config/custom_components/` della tua
installazione Home Assistant, poi riavvia.

## Utilizzo

Dopo l'installazione, l'integrazione aggiunge una voce **NeoPill** nella sidebar. In alto nel pannello c'è
una toolbar con: icona per aggiungere un paziente, selettore del paziente attivo, i campi "Giorni minimi"/
"Giorni massimi" della finestra di riordino di quel paziente (si salvano da soli quando esci dal campo),
icona per aggiungere un farmaco e icona per eliminare il paziente selezionato. Sotto, le card dei farmaci
del paziente con tutte le azioni quotidiane (assumi ora, segna come non assunta, rifornisci, modifica,
elimina) — disponibili anche come entità/servizi standard di Home Assistant.

## Promemoria rifornimento via email

NeoPill non gestisce l'invio di email direttamente (niente credenziali SMTP dentro l'integrazione): prepara
solo i dati, tramite un sensore per paziente `sensor.‹slug_paziente›_restock_reminder` (es.
`sensor.mrr_restock_reminder` per "Mario Rossi"). L'invio vero e proprio va fatto con un'automazione HA
che usa un servizio `notify.*` email già configurato (es. l'integrazione nativa `smtp`, oppure Gmail/altri).
Esempio (sostituisci l'entity_id con quello del tuo paziente):

```yaml
automation:
  - alias: "NeoPill - promemoria rifornimento farmaci"
    trigger:
      - platform: time
        at: "08:00:00"
    condition:
      - condition: numeric_state
        entity_id: sensor.mrr_restock_reminder
        above: 0
    action:
      - service: notify.smtp   # sostituisci con il tuo servizio notify email
        data:
          title: "NeoPill: farmaci da rifornire"
          message: "{{ state_attr('sensor.mrr_restock_reminder', 'testo') }}"
```

L'attributo `farmaci` del sensore contiene anche la lista strutturata (nome, giorni rimanenti, scorta) se
preferisci costruire un messaggio personalizzato invece di usare il testo già pronto. Se hai più pazienti,
duplica l'automazione (o il trigger) per ciascun sensore.

## Permessi

Qualsiasi utente Home Assistant autenticato può registrare un'assunzione, una dose "non assunta" o un
rifornimento (dal pannello, da un pulsante o da un servizio). Solo gli utenti amministratori possono
creare, modificare o eliminare pazienti e farmaci.

## Sviluppo

Il pannello (`custom_components/neopill/panel_dist/`) è scritto in JavaScript nativo (Web Component, moduli
ES standard, nessuna dipendenza esterna): non è previsto alcuno step di build, i file in `panel_dist/` sono
i sorgenti stessi e vengono serviti così come sono.

## Icona (brand)

L'icona/logo che compare in Impostazioni → Dispositivi e servizi viene letta da
`custom_components/neopill/brand/` (icon.png, icon@2x.png, logo.png, logo@2x.png) — funzionalità
disponibile da Home Assistant 2026.3 in poi, che permette a un'integrazione custom di fornire le proprie
immagini di brand senza passare da una PR al repository esterno `home-assistant/brands`. Su versioni di HA
precedenti alla 2026.3 questa cartella viene ignorata e resta il placeholder generico.

Le stesse immagini (più le versioni SVG sorgente `icon.svg`/`logo.svg`) sono presenti anche nella radice del
repository: servono per la scheda HACS e per il badge in cima a questo README, che sono cose distinte
dall'icona nella lista integrazioni.

## Stato del progetto

v0.5.0: backend + pannello, con device/entity_id organizzati per paziente (vedi Funzionalità). Non ancora
del tutto testata su un'istanza Home Assistant reale: prima di un uso in produzione, verificare
l'installazione secondo i passi in [Installazione](#installazione) e provare i flussi principali
(creazione paziente/farmaco, assunzione, rifornimento, promemoria dose, cancellazione paziente) su un
ambiente di test.

**Entity_id in inglese, nomi visualizzati localizzati**: gli identificatori tecnici (`sensor.mrr_stock`,
`button.mrr_take_dose`, ecc.) sono in inglese e stabili; i nomi mostrati nell'interfaccia ("Scorta",
"Assumi ora", ...) seguono invece la lingua configurata in Home Assistant (italiano/inglese per ora),
tramite il meccanismo nativo di traduzione delle entità — non serve nessuna configurazione, cambia da solo
in base alla lingua del tuo utente HA.

**Nota su questo specifico cambio**: a differenza del prefisso-paziente (dato calcolato una volta alla
creazione del paziente, quindi serve ricreare per applicarlo ai vecchi dati), il passaggio a chiavi inglesi
è puramente lato codice: al primo riavvio dopo l'aggiornamento, farmaci e pazienti già esistenti ottengono
automaticamente i nuovi entity_id/nomi, e le vecchie voci nel registro entità (con lo schema italiano)
vengono ripulite in automatico invece di restare "fantasmi" non disponibili.

## Licenza

MIT
