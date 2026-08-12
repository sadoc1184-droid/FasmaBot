# Astrosoldi in FasmaBot

Report della prossima estrazione SuperEnalotto consegnato su Telegram.

## Da dove viene il motore

`albano_lotto/` e' una copia vendorizzata dello studio **albano-lotto /
Astrosoldi**, che vive in `DioNanos/TarshishTradingSystem` sotto
`studies/albano-lotto/` (branch `claude/repository-study-fetby3`).

E' vendorizzato e non installato da pip perche' il repository di origine e'
privato: `pip install git+...` chiederebbe credenziali sulla macchina del bot ad
ogni ricostruzione del venv. La calibrazione di serie
(`albano_lotto/dati/calibrazione-2009-2026.json`, 2.900 estrazioni reali
2009-2026) viaggia col pacchetto, quindi il primo report funziona senza
scaricare niente: nessuno scraping, nessuna calibrazione preliminare.

Per aggiornare la copia, dal repo di origine:

```bash
git archive <branch> studies/albano-lotto/albano_lotto | tar -x --strip-components=2 -C ~/Dev/FasmaBot
```

Se in futuro Astrosoldi diventa un repository suo, la copia va sostituita con
`pip install "git+https://github.com/<owner>/Astrosoldi.git@main"` e
`albano_lotto/` va cancellata: `astro.py` non cambia, importa gli stessi moduli.

## Cosa esce

| Verdetto orario | Messaggio |
|---|---|
| `ASTIENITI` | solo la parola **ASTIENITI**, maiuscola, in grassetto, nient'altro |
| `GIOCA` | le combinazioni da giocare + Jolly/SuperStar + avvertenza |
| `INCERTO` | come `GIOCA`, ma con il verdetto marcato `INCERTO` |

Telegram non offre ne' colore ne' corpo del testo nei messaggi: "bianco e
grosso" si ottiene col grassetto Markdown — che rende nel colore di default del
tema, bianco su tema scuro — e con le lettere spaziate, che allargano la parola
sulla riga. Per un vero controllo di dimensione e colore servirebbe generare
un'immagine e mandarla come foto.

L'avvertenza e il numero verde restano attaccati ai messaggi che propongono una
giocata (e' la richiesta esplicita dello studio, vedi il suo `INTEGRAZIONE.md`).
Sul messaggio `ASTIENITI` non ci sono: li' nessuna giocata viene proposta.

## Quando e a chi

- **Job `astro_report`**: ogni giorno alle **09:00 Europe/Rome**; invia solo se
  il giorno e' di estrazione (mar/gio/ven/sab, estrazione alle 20:00).
- **Comando `/astro`** (admin): report immediato, on-demand.
- **Destinatari**: `ASTRO_USER_IDS`, e se vuota `ADMIN_USER_IDS` — cioe' solo
  Sadoc. Volutamente **non** `ALLOWED_USER_IDS`, che include gli utenti
  stock-only.

### Limite noto

`is_draw_day` conosce solo la cadenza settimanale ordinaria: i posticipi per
festivita' (es. Ferragosto) non sono gestiti. Nei giorni spostati il report esce
comunque, riferito al giorno sbagliato. Le due soluzioni possibili (confronto con
l'archivio scaricato, oppure lista di eccezioni in configurazione) non sono
implementate.

## Configurazione

```
ASTRO_USER_IDS=791708038   # vuoto → ADMIN_USER_IDS
ASTRO_COMBINAZIONI=5       # quante combinazioni quando il verdetto e' di giocare
```

Dipendenza runtime aggiunta: `pyswisseph==2.10.3.2` (vedi `requirements.txt`).

```bash
~/Dev/FasmaBot/venv/bin/pip install -r requirements.txt
sudo systemctl restart fasmagor
```

## Report di mercato sospesi

I report automatici sui ticker (09:30 / 12:45 / 16:00 ET) sono **sospesi
temporaneamente**: `MARKET_REPORTS_ENABLED = False` in cima a `bot.py`. Con il
flag a `False` i tre job non vengono nemmeno registrati e `job_report` esce
subito. Per riattivarli: rimettere `True` e riavviare il servizio. Restano
attivi `/report` e `/confronta` manuali; la simulazione breakout e' un'altra cosa
e si spegne con `/sim_off`.
