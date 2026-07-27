"""Paper-trading engine for the 'Breakout Semplice' strategy.

Simula la strategia del documento omonimo sui ticker della watchlist, su dati
reali Yahoo Finance, con un conto IBKR multivaluta (capitale iniziale 500 EUR,
operato in USD). Genera report event-driven (solo quando c'è un evento di
trading: entry o exit). Stato persistente in JSON, come il resto del bot.

Decisioni di modellazione (dichiarate):
  • Conto multivaluta: 500 EUR -> USD una tantum (costo cambio IBKR min 2 $),
    poi si opera in USD. Equity mostrata in EUR al cambio del giorno.
  • Commissioni IBKR tiered: max(0,35 $; 0,005 $/azione) + 0,015 $ per ordine.
  • Tasse IT 26% sulla plusvalenza netta realizzata, accorpate sull'uscita.
  • Una posizione alla volta (regola micro del PDF).
  • Checklist 5/5: trend (SMA50>SMA200), base 3-8 sett, close>resistenza +0,5%,
    volume >=1,5x media 50gg, SPY > propria SMA50.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

from stock import load_watchlist, ET_TZ

STATE_FILE    = Path(__file__).parent / "paperbook_state.json"
INITIAL_EUR   = 500.0
TAX_PCT       = 0.26          # plusvalenze IT
COMMISSION_MIN_USD  = 0.35
COMMISSION_PER_SH   = 0.005
COMMISSION_FIXED_USD = 0.015
FX_FEE_MIN_USD = 2.0          # costo cambio IBKR (minimo 2 $)
FX_FEE_RATE    = 0.00002      # 0,002%
SPY_TICKER     = "SPY"
FX_TICKER      = "EURUSD=X"   # 1 EUR = X USD

# Parametri per regime di prezzo. Strategia 1 (Standard) per ticker > 5 $,
# "Micro-Breakout" (1-5 $) per penny/small-cap. Stessa architettura, soglie
# adattate alla volatilità più alta. Sotto 1 $ escluso (micro-cap illiquida).
STANDARD = {
    "name": "standard", "price_min": 5.0, "price_max": 150.0,
    "avg_vol_min": 500_000, "vol_ratio_min": 1.5,
    "base_window": 30, "base_range_max": 0.15, "high_52w_factor": 0.88,
    "stop_max": 0.08, "risk_pct": 0.02, "cap_pos": 0.50,
    "target_r": 2.0, "time_stop_days": 5, "require_sma200": True,
}
MICRO = {
    "name": "micro", "price_min": 1.0, "price_max": 5.0,
    "avg_vol_min": 300_000, "vol_ratio_min": 2.0,
    "base_window": 40, "base_range_max": 0.25, "high_52w_factor": 0.80,
    "stop_max": 0.12, "risk_pct": 0.01, "cap_pos": 0.25,
    "target_r": 1.5, "time_stop_days": 3, "require_sma200": False,
}


def style_for_price(close: float) -> str:
    """Regime di strategia in base al prezzo di chiusura."""
    if 1.0 <= close < 5.0:
        return "micro"
    return "standard"


def params_for(style: str) -> dict:
    return MICRO if style == "micro" else STANDARD


# ── Stato persistente ─────────────────────────────────────────────────────────

def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def init_state(fx_open: float) -> dict:
    """Primo avvio: converte 500 EUR in USD una tantum."""
    gross_usd = INITIAL_EUR * fx_open
    fee = max(FX_FEE_MIN_USD, gross_usd * FX_FEE_RATE)
    return {
        "initial_eur": INITIAL_EUR,
        "cash_usd": round(gross_usd - fee, 4),
        "fx_fee_usd": round(fee, 4),
        "position": None,
        "pending_entry": None,
        "closed": [],
        "signals": [],          # storico di tutti i signal (memoria)
        "last_date": None,
        "enabled": False,       # simulazione live attiva solo su OK esplicito
    }


def set_enabled(state: dict, on: bool) -> None:
    state["enabled"] = bool(on)
    save_state(state)


# ── Dati di mercato ───────────────────────────────────────────────────────────

def _row_asof(df: pd.DataFrame, date: pd.Timestamp) -> pd.Series | None:
    """Riga <= date più recente (gestisce festività/mancanze)."""
    if df is None or df.empty:
        return None
    try:
        loc = df.index.get_indexer([date], method="ffill")[0]
    except (KeyError, ValueError):
        return None
    if loc < 0:
        return None
    return df.iloc[loc]


def fetch_bars(symbols: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
    out = {}
    for s in symbols:
        try:
            out[s] = yf.Ticker(s).history(period=period, interval="1d")
        except Exception:
            out[s] = pd.DataFrame()
    return out


# ── Indicatori / checklist ────────────────────────────────────────────────────

def _sma(series: pd.Series, n: int) -> float | None:
    if len(series) < n:
        return None
    return float(series.iloc[-n:].mean())


def setup_breakdown(symbol: str, df: pd.DataFrame, spy_df: pd.DataFrame) -> dict:
    """Valuta ogni condizione separatamente. Ritorna dict di bool + metriche.

    I parametri (soglie, risk, target, time-stop) sono dinamici in base al
    prezzo: regime 'micro' per 1-5 $, 'standard' per > 5 $.
    """
    out = {"ok": False, "reason": "no-data", "metrics": {}}
    if df is None or len(df) < 51:
        return out
    today = df.iloc[-1]
    prior = df.iloc[:-1]
    close = float(today["Close"])
    low   = float(today["Low"])
    vol   = float(today["Volume"])
    avg_vol_50 = float(prior["Volume"].iloc[-50:].mean()) if len(prior) >= 50 else 0

    # selezione regime in base al prezzo
    if close < 1.0:
        out["reason"] = "price-too-low"; return out
    if close > 150.0:
        out["reason"] = "price-out"; return out
    style = style_for_price(close)
    P = params_for(style)
    out["metrics"] = {"close": close, "avg_vol_50": avg_vol_50, "style": style}

    # Filtro liquidità
    if avg_vol_50 < P["avg_vol_min"]:
        out["reason"] = "low-volume"; return out

    # 1) trend
    closes_inc = pd.concat([prior["Close"], pd.Series([close])])
    sma50  = _sma(closes_inc, 50)
    sma200 = _sma(closes_inc, 200) if len(df) >= 200 else None
    if sma50 is None or close <= sma50:
        out["reason"] = "no-trend-close"; return out
    if P["require_sma200"] and sma200 is not None and sma50 <= sma200:
        out["reason"] = "no-trend-sma"; return out

    # 2) base
    bw = P["base_window"]
    base_hi = prior["High"].iloc[-bw:] if len(prior) >= bw else prior["High"]
    base_lo = prior["Low"].loc[base_hi.index]
    if base_lo.min() <= 0:
        out["reason"] = "base-data"; return out
    base_range = (base_hi.max() - base_lo.min()) / base_lo.min()
    high_52w = float(prior["High"].iloc[-252:].max()) if len(prior) >= 10 else float(prior["High"].max())
    out["metrics"]["base_range"] = base_range
    out["metrics"]["high_52w"] = high_52w
    if base_range >= P["base_range_max"]:
        out["reason"] = "base-wide"; return out
    if close < high_52w * P["high_52w_factor"]:
        out["reason"] = "far-from-highs"; return out

    # 3) chiusura sopra resistenza
    res = float(prior["High"].iloc[-bw:].max()) if len(prior) >= bw else float(prior["High"].max())
    out["metrics"]["res"] = res
    if close < res * 1.005:
        out["reason"] = "no-breakout"; return out

    # 4) volume
    vol_ratio = vol / avg_vol_50 if avg_vol_50 > 0 else 0
    out["metrics"]["vol_ratio"] = vol_ratio
    if vol_ratio < P["vol_ratio_min"]:
        out["reason"] = "low-volume-day"; return out

    # 5) SPY
    spy_sma50 = _sma(spy_df["Close"].iloc[-51:], 50) if spy_df is not None and len(spy_df) >= 50 else None
    if spy_sma50 is None or float(spy_df["Close"].iloc[-1]) <= spy_sma50:
        out["reason"] = "spy-bear"; return out

    # stop largo
    stop_hint = low - 0.05
    stop_pct = (close - stop_hint) / close
    out["metrics"]["stop_pct"] = stop_pct
    if stop_pct > P["stop_max"]:
        out["reason"] = "stop-too-wide"; return out

    out["ok"] = True
    out["reason"] = "ok"
    return out


def check_setup(symbol: str, df: pd.DataFrame, spy_df: pd.DataFrame) -> dict | None:
    """Checklist 5/5 sul candle di oggi (ultima riga di df). Usa setup_breakdown."""
    bd = setup_breakdown(symbol, df, spy_df)
    if not bd["ok"]:
        return None
    m = bd["metrics"]
    res, close = m["res"], m["close"]
    style = m["style"]
    P = params_for(style)
    real_low = float(df.iloc[-1]["Low"])
    stop = real_low - 0.05
    target = close + P["target_r"] * (close - stop)
    return {
        "symbol": symbol, "res": round(res, 4), "close": round(close, 4),
        "stop_hint": round(stop, 4), "target_hint": round(target, 4),
        "vol_ratio": round(m["vol_ratio"], 2), "stop_pct": round(m["stop_pct"], 4),
        "score": round(m["vol_ratio"] + (close - res) / res * 100, 2),
        "style": style, "target_r": P["target_r"], "risk_pct": P["risk_pct"],
        "cap_pos": P["cap_pos"], "time_stop_days": P["time_stop_days"],
    }


# ── Costi IBKR ────────────────────────────────────────────────────────────────

def _commission(shares: float) -> float:
    return round(max(COMMISSION_MIN_USD, COMMISSION_PER_SH * shares) + COMMISSION_FIXED_USD, 4)


# ── Eventi di trading ─────────────────────────────────────────────────────────

def _equity_usd(state: dict, price: float | None) -> float:
    cash = state["cash_usd"]
    pos = state["position"]
    if pos and price is not None:
        return cash + pos["shares"] * price
    return cash


def _entry(state: dict, setup: dict, open_price: float, fx: float, date: str) -> dict | None:
    # Anti-inseguimento: open oltre +3% sopra la resistenza -> salta
    if open_price > setup["res"] * 1.03:
        return None
    P = params_for(setup.get("style", "standard"))
    equity_usd = _equity_usd(state, None)
    risk_eur = P["risk_pct"] * (equity_usd / fx)        # equity EUR -> rischio (1% micro / 2% standard)
    risk_usd = risk_eur * fx
    stop = setup["stop_hint"]
    risk_pct = (open_price - stop) / open_price
    if risk_pct <= 0 or risk_pct > P["stop_max"]:
        return None
    target_usd = risk_usd / risk_pct
    max_usd = equity_usd * P["cap_pos"]
    invest_usd = min(target_usd, max_usd)
    shares = invest_usd / open_price
    comm = _commission(shares)
    cost = shares * open_price + comm
    if cost > state["cash_usd"]:
        shares = (state["cash_usd"] - comm) / open_price
        cost = shares * open_price + comm
        if shares <= 0:
            return None
    state["cash_usd"] = round(state["cash_usd"] - cost, 4)
    state["position"] = {
        "symbol": setup["symbol"], "shares": round(shares, 6),
        "entry": round(open_price, 4), "stop": round(stop, 4),
        "target": round(open_price + P["target_r"] * (open_price - stop), 4),
        "res": setup["res"], "entry_date": date, "entry_fx": fx,
        "comm_usd": comm, "cost_basis": round(cost, 4),
        "risk_eur": round(risk_eur, 2),
        "style": setup.get("style", "standard"),
        "target_r": P["target_r"], "time_stop_days": P["time_stop_days"],
        # setup che ha generato l'operazione (memoria storica)
        "setup": {
            "signal_close": setup["close"], "res": setup["res"],
            "vol_ratio": setup["vol_ratio"], "stop_pct": setup["stop_pct"],
            "score": setup["score"], "signal_date": setup.get("signal_date", date),
            "style": setup.get("style", "standard"),
        },
    }
    return {"kind": "entry", "date": date, "position": state["position"]}


def _exit(state: dict, exit_price: float, fx: float, date: str, reason: str) -> dict:
    pos = state["position"]
    shares = pos["shares"]
    comm = _commission(shares)
    gross = (exit_price - pos["entry"]) * shares
    net = gross - pos["comm_usd"] - comm
    tax_usd = TAX_PCT * max(0.0, net)
    real = net - tax_usd
    state["cash_usd"] = round(state["cash_usd"] + shares * exit_price - comm - tax_usd, 4)
    pnl_eur = real / fx
    pct = real / pos["cost_basis"] * 100 if pos["cost_basis"] else 0.0
    held = _trading_days_between(pos["entry_date"], date)
    record = {
        "symbol": pos["symbol"], "entry_date": pos["entry_date"], "exit_date": date,
        "entry": pos["entry"], "exit": round(exit_price, 4), "shares": shares,
        "reason": reason, "gross_usd": round(gross, 2), "comm_usd": round(pos["comm_usd"] + comm, 2),
        "tax_usd": round(tax_usd, 2), "pnl_usd": round(real, 2), "pnl_eur": round(pnl_eur, 2),
        "pnl_pct": round(pct, 2), "held_days": held,
        "setup": pos.get("setup", {}), "entry_fx": pos.get("entry_fx"), "exit_fx": fx,
    }
    state["closed"].append(record)
    state["position"] = None
    return {"kind": "exit", "date": date, "trade": record}


def _trading_days_between(d0: str, d1: str) -> int:
    try:
        a = datetime.fromisoformat(d0); b = datetime.fromisoformat(d1)
        return max(1, int((b - a).days))
    except Exception:
        return 1


def _evaluate_exit(pos: dict, row: pd.Series, date: str) -> tuple[float, str] | None:
    low  = float(row["Low"])
    high = float(row["High"])
    close = float(row["Close"])
    # Stop / target intraday (conservativo: se entrambi toccati, stop prima)
    if low <= pos["stop"]:
        return pos["stop"], "stop"
    if high >= pos["target"]:
        return pos["target"], "target"
    # Uscita di emergenza: close sotto il livello rotto
    if close < pos["res"]:
        return close, "fakeout"
    # Time stop: N sedute senza progresso (close ancora sotto l'entry)
    held = _trading_days_between(pos["entry_date"], date)
    if held >= pos.get("time_stop_days", 5) and close < pos["entry"]:
        return close, "time-stop"
    return None


# ── Step giornaliero ──────────────────────────────────────────────────────────

def step_open(state: dict, date: pd.Timestamp, bars: dict, fx_df: pd.DataFrame) -> list[dict]:
    """Apertura: esegue eventuali pending entry all'open di oggi."""
    events: list[dict] = []
    ds = date.strftime("%Y-%m-%d")
    fx_row = _row_asof(fx_df, date)
    fx = float(fx_row["Close"]) if fx_row is not None else 1.0

    pend = state.get("pending_entry")
    if pend and state.get("position") is None:
        df = bars.get(pend["symbol"])
        row = _row_asof(df, date)
        if row is not None:
            ev = _entry(state, pend, float(row["Open"]), fx, ds)
            if ev:
                events.append(ev)
        state["pending_entry"] = None
    return events


def step_close(state: dict, date: pd.Timestamp, bars: dict, fx_df: pd.DataFrame) -> list[dict]:
    """Chiusura: exit intraday su posizione aperta + checklist per domani."""
    events: list[dict] = []
    ds = date.strftime("%Y-%m-%d")
    fx_row = _row_asof(fx_df, date)
    fx = float(fx_row["Close"]) if fx_row is not None else 1.0

    pos = state.get("position")
    if pos:
        df = bars.get(pos["symbol"])
        row = _row_asof(df, date)
        if row is not None:
            ex = _evaluate_exit(pos, row, ds)
            if ex:
                price, reason = ex
                events.append(_exit(state, price, fx, ds, reason))

    if state.get("position") is None and state.get("pending_entry") is None:
        spy_full = bars.get(SPY_TICKER)
        spy_sub = spy_full.loc[:date] if spy_full is not None and not spy_full.empty else spy_full
        best = None
        for sym, df in bars.items():
            if sym == SPY_TICKER or sym == FX_TICKER:
                continue
            sub = df.loc[:date] if df is not None and not df.empty else df
            if sub is None or sub.empty:
                continue
            setup = check_setup(sym, sub, spy_sub)
            if setup and (best is None or setup["score"] > best["score"]):
                best = setup
        if best:
            best["signal_date"] = ds
            state["pending_entry"] = best
            state.setdefault("signals", []).append({
                "date": ds, "symbol": best["symbol"], "res": best["res"],
                "close": best["close"], "vol_ratio": best["vol_ratio"],
                "stop_hint": best["stop_hint"], "score": best["score"],
                "style": best.get("style", "standard"),
            })
            events.append({"kind": "signal", "date": ds, "setup": best})

    state["last_date"] = ds
    return events


def run_day(state: dict, date: pd.Timestamp, bars: dict, fx_df: pd.DataFrame) -> list[dict]:
    """Backtest: compose step_open + step_close sulla stessa giornata."""
    return step_open(state, date, bars, fx_df) + step_close(state, date, bars, fx_df)


def live_step(phase: str, state: dict) -> tuple[list[dict], float, dict]:
    """Uno step live: scarica i dati al volo, esegue step_open/step_close,
    salva lo stato. Ritorna (events, fx, last_prices) per i report.

    phase = 'open' (09:30 ET, esegue pending entry) o 'close' (16:00 ET,
    exit + checklist). Usa l'ultima seduta disponibile nei dati.
    """
    tickers = load_watchlist()
    symbols = list(tickers)
    # include sempre il ticker di una posizione aperta, anche se rimosso dalla watchlist
    pos = state.get("position")
    if pos and pos["symbol"] not in symbols:
        symbols.append(pos["symbol"])
    pend = state.get("pending_entry")
    if pend and pend["symbol"] not in symbols:
        symbols.append(pend["symbol"])
    symbols += [SPY_TICKER, FX_TICKER]
    bars = fetch_bars(symbols, period="1y")
    fx_df = bars.get(FX_TICKER)
    spy = bars.get(SPY_TICKER)
    if spy is None or spy.empty or fx_df is None or fx_df.empty:
        return [], 1.0, {}

    date = spy.index[-1]  # ultima seduta disponibile
    fn = step_open if phase == "open" else step_close
    events = fn(state, date, bars, fx_df)
    save_state(state)

    fx = float(fx_df["Close"].iloc[-1])
    last_px = {s: float(df["Close"].iloc[-1]) for s, df in bars.items()
               if df is not None and not df.empty}
    return events, fx, last_px


# ── Report event-driven ───────────────────────────────────────────────────────

def _fx_now(fx_df: pd.DataFrame) -> float:
    if fx_df is None or fx_df.empty:
        return 1.0
    return float(fx_df["Close"].iloc[-1])


def equity_eur(state: dict, fx: float, last_prices: dict[str, float]) -> tuple[float, float]:
    """Ritorna (tot_cap_eur, cap_investito_eur)."""
    pos = state.get("position")
    invested = 0.0
    if pos:
        px = last_prices.get(pos["symbol"], pos["entry"])
        invested = pos["shares"] * px
    tot = (state["cash_usd"] + invested) / fx
    return tot, invested / fx


def build_event_report(state: dict, event: dict, fx: float, last_prices: dict[str, float]) -> str:
    tot, inv = equity_eur(state, fx, last_prices)
    header = f"📈 *Sim Breakout*\n\nTot Cap: {tot:.2f} €\nCap.Invst: {inv:.2f} €\n\n"

    if event["kind"] == "entry":
        p = event["position"]
        style_tag = " · MICRO" if p.get("style") == "micro" else ""
        tr = p.get("target_r", 2.0)
        body = (f"🟢 LONG{style_tag} {p['symbol']} @ ${p['entry']:.2f}\n"
                f"Stop: ${p['stop']:.2f} · Target: ${p['target']:.2f} (+{tr}R)\n"
                f"Size: {p['shares']:.2f} az · Rischio: {p['risk_eur']:.2f} €\n"
                f"Commissione: {p['comm_usd']:.2f} $")
        return header + body

    if event["kind"] == "exit":
        t = event["trade"]
        sign = "+" if t["pnl_eur"] >= 0 else ""
        body = (f"🔴 EXIT {t['symbol']} @ ${t['exit']:.2f} ({t['reason']})\n"
                f"Tenuto: {t['held_days']} gg\n\n"
                f"P&L: {sign}{t['pnl_eur']:.2f} € ({sign}{t['pnl_pct']:.2f}%)")
        return header + body

    if event["kind"] == "signal":
        s = event["setup"]
        body = (f"📡 Segnale {s['symbol']} (checklist 5/5)\n"
                f"Resistenza: ${s['res']:.2f} · Close: ${s['close']:.2f}\n"
                f"Vol: {s['vol_ratio']}x · Stop hint: ${s['stop_hint']:.2f}\n"
                f"Entry programmata all'open di domani")
        return header + body

    return header


def build_status(state: dict, fx: float, last_prices: dict[str, float]) -> str:
    tot, inv = equity_eur(state, fx, last_prices)
    lines = [f"📈 *Sim Breakout — stato*", "",
             f"Tot Cap: {tot:.2f} €", f"Cap.Invst: {inv:.2f} €",
             f"Cash USD: {state['cash_usd']:.2f} $",
             f"Trade chiusi: {len(state.get('closed', []))}"]
    pos = state.get("position")
    if pos:
        px = last_prices.get(pos["symbol"], pos["entry"])
        upnl = (px - pos["entry"]) * pos["shares"] / fx
        lines += ["", f"Posizione: {pos['symbol']} @ ${pos['entry']:.2f}",
                  f"Stop ${pos['stop']:.2f} · Target ${pos['target']:.2f}",
                  f"P&L non realizzato: {'+' if upnl>=0 else ''}{upnl:.2f} €"]
    pend = state.get("pending_entry")
    if pend:
        lines += ["", f"Pending entry: {pend['symbol']} (domani all'open)"]
    return "\n".join(lines)