"""Stock monitor — data and report logic."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytz
import yfinance as yf

WATCHLIST_FILE = Path(__file__).parent / "watchlist.json"
STATE_FILE     = Path(__file__).parent / "monitor_state.json"
HISTORY_FILE   = Path(__file__).parent / "report_history.json"
HISTORY_MAX_DAYS = 30
ET_TZ          = pytz.timezone("America/New_York")


# ── Watchlist ─────────────────────────────────────────────────────────────────

def load_watchlist() -> list[str]:
    if not WATCHLIST_FILE.exists():
        return []
    return json.loads(WATCHLIST_FILE.read_text(encoding="utf-8")).get("tickers", [])


def save_watchlist(tickers: list[str]) -> None:
    WATCHLIST_FILE.write_text(
        json.dumps({"tickers": tickers}, indent=2),
        encoding="utf-8",
    )


# ── Monitor state ─────────────────────────────────────────────────────────────

def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"paused": False}
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, indent=2),
        encoding="utf-8",
    )


# ── Report history ────────────────────────────────────────────────────────────

def load_history() -> list:
    if not HISTORY_FILE.exists():
        return []
    return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))


def save_history(history: list) -> None:
    HISTORY_FILE.write_text(
        json.dumps(history, indent=2),
        encoding="utf-8",
    )


def _prune_history(history: list) -> list:
    """Drop snapshots older than HISTORY_MAX_DAYS.

    Parses each timestamp with fromisoformat so malformed entries (missing or
    non-ISO ts) are dropped rather than kept by accident. Aware-of-DST
    comparison via real datetime objects.
    """
    cutoff = datetime.now(ET_TZ) - timedelta(days=HISTORY_MAX_DAYS)
    kept = []
    for e in history:
        ts = e.get("ts")
        if not ts:
            continue
        try:
            when = datetime.fromisoformat(ts)
        except ValueError:
            continue
        if when.tzinfo is None:
            when = ET_TZ.localize(when)
        if when >= cutoff:
            kept.append(e)
    return kept


# ── Price data ────────────────────────────────────────────────────────────────

def validate_ticker(symbol: str) -> bool:
    try:
        t = yf.Ticker(symbol)
        price = t.fast_info.last_price
        if price and float(price) > 0:
            return True
        return not t.history(period="5d").empty
    except Exception:
        return False


def get_price_data(symbol: str) -> dict | None:
    try:
        t  = yf.Ticker(symbol)
        fi = t.fast_info
        prev    = round(float(fi.previous_close), 2)
        current = round(float(fi.last_price), 2)
        pct     = round((current - prev) / prev * 100, 2)
        return {"symbol": symbol, "prev": prev, "current": current, "pct": pct}
    except Exception:
        return None


# ── Breakout detection ────────────────────────────────────────────────────────

def _breakout_metrics(data: dict) -> dict | None:
    """20-day-high + volume breakout heuristic.

    Returns {"label": "VB"|"FB", "score": float} when the last close breaks the
    20-day high with volume > 1.5x the 20-day average, else None. VB (vero
    breakout) requires the stronger confirmation of volume >= 2x and daily pct
    >= +3%; anything else above the 1.5x attention threshold is FB (falso
    breakout). score is used only to order candidates in the report.
    """
    try:
        hist = yf.Ticker(data["symbol"]).history(period="25d")
        if len(hist) < 21:
            return None
        high_20  = float(hist["High"].iloc[-21:-1].max())
        avg_vol  = float(hist["Volume"].iloc[-21:-1].mean())
        last_vol = float(hist["Volume"].iloc[-1])
    except Exception:
        return None
    if avg_vol <= 0 or data["current"] <= high_20:
        return None
    vol_ratio = last_vol / avg_vol
    if vol_ratio <= 1.5:
        return None
    label = "VB" if vol_ratio >= 2.0 and data["pct"] >= 3.0 else "FB"
    return {"label": label, "score": vol_ratio + data["pct"] / 100}


# ── Formatting ────────────────────────────────────────────────────────────────

def _format_line(data: dict) -> str:
    sign = "+" if data["pct"] >= 0 else ""
    return f"*{data['symbol']}*: ${data['prev']:.2f} → ${data['current']:.2f} ({sign}{data['pct']:.2f}%)"


def build_report() -> str:
    tickers = load_watchlist()
    if not tickers:
        return "⚠️ Watchlist vuota."

    rows   = []
    valid  = []
    errors = []
    for sym in tickers:
        data = get_price_data(sym)
        if data is None:
            errors.append(sym)
            continue
        valid.append(data)
        bm   = _breakout_metrics(data)
        line = _format_line(data)
        if bm:
            tag = " — VB ✅" if bm["label"] == "VB" else " — FB ⚠️"
            line += tag
            sort_key = (0, -bm["score"])
        else:
            sort_key = (1, -data["pct"])
        rows.append((sort_key, line))

    now    = datetime.now(ET_TZ)
    header = f"📊 *Report {now.strftime('%H:%M ET')}*\n\n"
    footer = f"\n\n⚠️ Errore dati: {', '.join(errors)}" if errors else ""

    if not rows:
        return header + "Nessun Ticker che rispetta le condizioni." + footer

    rows.sort(key=lambda r: r[0])
    lines = [line for _, line in rows]

    history = load_history()
    history = _prune_history(history)
    history.append({"ts": now.isoformat(), "tickers": valid})
    save_history(history)

    return header + "\n".join(lines) + footer


def build_compare() -> str:
    tickers = load_watchlist()
    if not tickers:
        return "⚠️ Watchlist vuota."

    history = _prune_history(load_history())
    pct_by_sym: dict[str, list[float]] = {sym: [] for sym in tickers}
    for snap in history:
        for entry in snap.get("tickers", []):
            sym = entry.get("symbol")
            if sym in pct_by_sym:
                pct_by_sym[sym].append(float(entry["pct"]))

    lines = []
    for sym in tickers:
        vals = pct_by_sym[sym]
        if not vals:
            lines.append(f"*{sym}*: nessun dato storico")
            continue
        avg  = sum(vals) / len(vals)
        sign = "+" if avg >= 0 else ""
        lines.append(f"*{sym}*: media {sign}{avg:.2f}% ({len(vals)} report)")

    return "📊 *Confronto storico*\n\n" + "\n".join(lines)


def format_single(symbol: str) -> str:
    data = get_price_data(symbol.upper())
    if data is None:
        return f"❌ Impossibile recuperare dati per *{symbol.upper()}*."
    sign = "+" if data["pct"] >= 0 else ""
    return f"*{data['symbol']}*: ${data['prev']:.2f} → ${data['current']:.2f} ({sign}{data['pct']:.2f}%)"
