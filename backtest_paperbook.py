"""Backtest di paperbook.py sui ticker della watchlist, su dati reali.

Simula giorno per giorno gli ultimi N mesi e stampa ogni evento (signal/entry/exit)
con i numeri, per validare che l'engine genera operazioni e che i conti tornano.
Non tocca lo stato di produzione (usa uno stato in memoria).
"""

from datetime import datetime
import pandas as pd

import paperbook as pb
from stock import load_watchlist

PERIOD = "2y"          # storico da scaricare
SIM_DAYS = 130         # ~6 mesi di sedute da simulare


def main() -> None:
    tickers = load_watchlist()
    symbols = tickers + [pb.SPY_TICKER, pb.FX_TICKER]
    print(f"Scarico dati per {len(symbols)} symbol ...")
    bars = pb.fetch_bars(symbols, period=PERIOD)

    fx_df = bars.get(pb.FX_TICKER)
    if fx_df is None or fx_df.empty:
        print("ERRORE: EURUSD=X non disponibile")
        return

    # date di simulazione = sedute di SPY (indice di mercato)
    spy = bars.get(pb.SPY_TICKER)
    dates = spy.index[-SIM_DAYS:]

    # stato in memoria (non tocca paperbook_state.json)
    first_fx = float(pb._row_asof(fx_df, dates[0])["Close"])
    state = pb.init_state(first_fx)
    print(f"Capitale iniziale: {pb.INITIAL_EUR} EUR -> {state['cash_usd']:.2f} USD "
          f"(fx {first_fx:.4f}, cambio fee {state['fx_fee_usd']:.2f} $)\n")

    n_events = 0
    for date in dates:
        events = pb.run_day(state, date, bars, fx_df)
        for ev in events:
            n_events += 1
            fx = float(pb._row_asof(fx_df, date)["Close"])
            # prezzi alla data dell'evento (non di oggi) per reporting coerente
            last_px = {}
            for s, df in bars.items():
                r = pb._row_asof(df, date)
                if r is not None:
                    last_px[s] = float(r["Close"])
            print(f"--- {ev['date']} ({ev['kind']}) ---")
            print(pb.build_event_report(state, ev, fx, last_px))
            print()

    # stato finale
    fx_end = pb._fx_now(fx_df)
    last_px = {s: float(df["Close"].iloc[-1]) for s, df in bars.items()
               if df is not None and not df.empty}
    tot, inv = pb.equity_eur(state, fx_end, last_px)
    print("=" * 60)
    print(pb.build_status(state, fx_end, last_px))
    print("=" * 60)
    print(f"\nEventi totali: {n_events} | Trade chiusi: {len(state.get('closed', []))}")
    ret = (tot - pb.INITIAL_EUR) / pb.INITIAL_EUR * 100
    print(f"Rendimento simulato: {'+' if ret>=0 else ''}{ret:.2f}% "
          f"({tot - pb.INITIAL_EUR:+.2f} €)")
    # breakdown per stile (standard vs micro)
    from collections import Counter
    styles = Counter(t.get("setup", {}).get("style", "?") for t in state.get("closed", []))
    sig_styles = Counter(s.get("style", "?") for s in state.get("signals", []))
    print(f"Trade chiusi per stile: {dict(styles)}")
    print(f"Signal per stile: {dict(sig_styles)}")


if __name__ == "__main__":
    main()