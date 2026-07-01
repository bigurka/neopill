<p align="center">
  <img src="logo.svg" alt="NeoPill" width="480">
</p>

# NeoPill

Integrazione custom per Home Assistant (compatibile [HACS](https://hacs.xyz)) per la gestione dei farmaci
di uno o più pazienti: assunzioni, scorte, rifornimenti e promemoria dose, con un calendario nativo HA per
paziente e un dispositivo HA per ogni farmaco.

> Stato: in sviluppo (v0.1.0). Le funzionalità descritte qui sotto sono il target della v1.

## Funzionalità

- Gestione multi-paziente, ciascuno con il proprio calendario HA nativo (assunzioni, rifornimenti, dosi
  non assunte, scorta esaurita).
- Ogni farmaco è un dispositivo HA con entità per scorta, prossima assunzione, giorni di scorta rimanenti,
  stato "da assumere" e stato "scorta in esaurimento".
- Dosaggio a orari fissi o a intervallo dall'ultima assunzione, con dose anche frazionaria (es. 1/2, 1/4).
- Rifornimento per quantità diretta o per numero di confezioni.
- Tutta la gestione (pazienti, farmaci, assunzioni, rifornimenti) avviene da un pannello dedicato nella
  sidebar di Home Assistant, separato da Lovelace.
- Servizi Home Assistant (`neopill.assumi_farmaco`, `neopill.segna_non_assunta`, `neopill.rifornisci_farmaco`)
  per l'uso da automazioni.

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

Dopo l'installazione, l'integrazione aggiunge una voce **NeoPill** nella sidebar: da lì si creano/gestiscono
pazienti e farmaci. Le azioni quotidiane (assumi ora, segna come non assunta, rifornisci) sono disponibili
sia dal pannello sia come entità/servizi standard di Home Assistant.

## Permessi

Qualsiasi utente Home Assistant autenticato può registrare un'assunzione, una dose "non assunta" o un
rifornimento (dal pannello, da un pulsante o da un servizio). Solo gli utenti amministratori possono
creare, modificare o eliminare pazienti e farmaci.

## Sviluppo

Il pannello (`custom_components/neopill/panel_dist/`) è scritto in JavaScript nativo (Web Component, moduli
ES standard, nessuna dipendenza esterna): non è previsto alcuno step di build, i file in `panel_dist/` sono
i sorgenti stessi e vengono serviti così come sono.

## Stato del progetto

v0.1.0: prima versione funzionale (backend + pannello). Non ancora testata su un'istanza Home Assistant
reale/dev container: prima di un uso in produzione, verificare l'installazione secondo i passi in
[Installazione](#installazione) e provare i flussi principali (creazione paziente/farmaco, assunzione,
rifornimento, promemoria dose) su un ambiente di test.

## Licenza

MIT
