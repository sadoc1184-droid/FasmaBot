"""Diagnostica: per ogni (data, ticker) quale condizione fallisce nella checklist."""

from collections import Counter
import pandas as pd

import paperbook as pb
from stock import load_watchlist

PERIOD = "2y"
SIM_DAYS = 130


def main() -> None:
    tickers = load_watchlist()
    symbols = tickers + [pb.SPY_TICKER, pb.FX_TICKER]
    bars = pb.fetch_bars(symbols, period=PERIOD)
    spy = bars.get(pb.SPY_TICKER)
    dates = spy.index[-SIM_DAYS:]

    reasons = Counter()
    per_ticker = Counter()
    samples = {}
    n_checks = 0
    for date in dates:
        spy_sub = spy.loc[:date]
        for sym in tickers:
            df = bars.get(sym)
            if df is None or df.empty:
                continue
            sub = df.loc[:date]
            if sub is None or sub.empty:
                continue
            bd = pb.setup_breakdown(sym, sub, spy_sub)
            n_checks += 1
            reasons[bd["reason"]] += 1
            if bd["reason"] != "ok":
                per_ticker[(sym, bd["reason"])] += 1
            if bd["reason"] == "ok":
                samples.setdefault(sym, []).append((date.strftime("%Y-%m-%d"), bd["metrics"]))

    print(f"Check totali: {n_checks} | setup OK: {reasons.get('ok', 0)}\n")
    print("Distribuzione ragioni di fallimento:")
    for r, c in reasons.most_common():
        print(f"  {c:5d}  {r}")
    print("\nTop combinazioni ticker+ragione:")
    for (s, r), c in per_ticker.most_common(15):
        print(f"  {c:4d}  {s:6s} {r}")
    if samples:
        print("\nSetup OK trovati (esempi):")
        for s, lst in list(samples.items())[:5]:
            d, m = lst[0]
            print(f"  {s} @ {d}: close={m['close']:.2f} res={m['res']:.2f} "
                  f"vol={m['vol_ratio']:.2f}x base_range={m.get('base_range', 0):.3f}")


if __name__ == "__main__":
    main()