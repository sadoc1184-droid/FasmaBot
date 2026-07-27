#!/usr/bin/env python3
"""Fasmagor — Telegram bot: GLM (Ollama) + Claude bridge + stock monitor."""

import logging
import os
import tempfile
from datetime import time as dt_time
from pathlib import Path

import pytz
import requests
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

WAITING_TICKER     = 1
WAITING_TICKER_ADD = 2
WAITING_TICKER_REM = 3
from context import build_system_prompt
from bridge import process_markers
from stock import (
    build_compare,
    build_report,
    format_single,
    load_state,
    load_watchlist,
    save_state,
    save_watchlist,
    validate_ticker,
    ET_TZ,
)
from paperbook import (
    build_event_report,
    build_status,
    equity_eur,
    init_state,
    live_step,
    load_state as pb_load_state,
    save_state as pb_save_state,
    set_enabled,
    STATE_FILE as PB_STATE_FILE,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
ALLOWED_USER_IDS = {
    int(uid.strip())
    for uid in os.environ.get("ALLOWED_USER_IDS", "").split(",")
    if uid.strip()
}
ADMIN_USER_IDS = {
    int(uid.strip())
    for uid in os.environ.get("ADMIN_USER_IDS", "").split(",")
    if uid.strip()
}
OLLAMA_URL    = "http://localhost:11434/api/chat"
GLM_MODEL     = "glm-5.2:cloud"
SYSTEM_PROMPT = build_system_prompt(fmt="bot")


# ── GLM ───────────────────────────────────────────────────────────────────────

def glm_call(history: list) -> str:
    resp = requests.post(
        OLLAMA_URL,
        json={"model": GLM_MODEL, "messages": history, "stream": False},
        timeout=300,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def _check_user(update: Update) -> bool:
    return update.effective_user and update.effective_user.id in ALLOWED_USER_IDS

def _check_admin(update: Update) -> bool:
    return update.effective_user and update.effective_user.id in ADMIN_USER_IDS


def _get_history(context: ContextTypes.DEFAULT_TYPE) -> list:
    if "history" not in context.user_data:
        context.user_data["history"] = [{"role": "system", "content": SYSTEM_PROMPT}]
    return context.user_data["history"]


# ── Base commands ─────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_user(update):
        return
    context.user_data["history"] = [{"role": "system", "content": SYSTEM_PROMPT}]
    await update.message.reply_text(
        "🤖 *Fasmagor avviato*\n\n"
        "Parla normalmente — GLM risponde.\n"
        "Manda una foto → Claude la analizza in automatico.\n\n"
        "/help — comandi disponibili",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_user(update):
        return
    context.user_data["history"] = [{"role": "system", "content": SYSTEM_PROMPT}]
    await update.message.reply_text("🔄 Conversazione resettata.")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_user(update):
        return
    await update.message.reply_text(
        "*Comandi Fasmagor*\n\n"
        "/start — avvia e resetta\n"
        "/reset — nuova conversazione\n"
        "/help — questa lista\n\n"
        "*Stock monitor:*\n"
        "/watchlist — lista ticker monitorati\n"
        "/aggiungi TICKER... — aggiunge uno o più ticker\n"
        "/rimuovi TICKER — rimuove un ticker\n"
        "/prezzo TICKER — prezzo e variazione % on-demand\n"
        "/report — report manuale immediato\n"
        "/confronta — media storica per ticker\n"
        "/stato — stato del monitor\n"
        "/pausa — sospende i report automatici\n"
        "/riprendi — riattiva i report automatici\n\n"
        "*Simulazione breakout (admin):*\n"
        "/sim — stato simulazione (capitale, posizione, P&L)\n"
        "/sim_on — attiva la simulazione (500 € su IBKR simulato)\n"
        "/sim_off — disattiva\n"
        "/sim_reset — azzera stato simulazione\n\n"
        "*Capacità chat:*\n"
        "• Testo → GLM risponde\n"
        "• Foto → Claude analizza, GLM usa i dati\n"
        "• Richieste di codice/file → Claude le esegue",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── Stock commands ────────────────────────────────────────────────────────────

async def _do_aggiungi(update: Update, args: list[str]) -> None:
    await update.message.reply_text("⏳ Verifico i ticker...")
    watchlist = load_watchlist()
    added, already, invalid = [], [], []
    for sym in args:
        if sym in watchlist:
            already.append(sym)
        elif validate_ticker(sym):
            watchlist.append(sym)
            added.append(sym)
        else:
            invalid.append(sym)
    if added:
        save_watchlist(watchlist)
    parts = []
    if added:
        parts.append(f"✅ Aggiunti: {', '.join(added)}")
    if already:
        parts.append(f"ℹ️ Già presenti: {', '.join(already)}")
    if invalid:
        parts.append(f"❌ Non trovati: {', '.join(invalid)}")
    await update.message.reply_text("\n".join(parts))


async def cmd_aggiungi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_user(update):
        return
    if context.args:
        await _do_aggiungi(update, [a.upper() for a in context.args])
        return ConversationHandler.END
    await update.message.reply_text("Scrivi il ticker (o più ticker separati da spazio):")
    return WAITING_TICKER_ADD


async def cmd_aggiungi_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_user(update):
        return ConversationHandler.END
    args = [a.upper() for a in update.message.text.strip().split()]
    await _do_aggiungi(update, args)
    return ConversationHandler.END


async def _do_rimuovi(update: Update, args: list[str]) -> None:
    watchlist = load_watchlist()
    removed, not_found = [], []
    for sym in args:
        if sym in watchlist:
            watchlist.remove(sym)
            removed.append(sym)
        else:
            not_found.append(sym)
    if removed:
        save_watchlist(watchlist)
    parts = []
    if removed:
        parts.append(f"✅ Rimossi: {', '.join(removed)}")
    if not_found:
        parts.append(f"❌ Non in lista: {', '.join(not_found)}")
    await update.message.reply_text("\n".join(parts))


async def cmd_rimuovi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_user(update):
        return
    if context.args:
        await _do_rimuovi(update, [a.upper() for a in context.args])
        return ConversationHandler.END
    await update.message.reply_text("Scrivi il ticker da rimuovere:")
    return WAITING_TICKER_REM


async def cmd_rimuovi_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_user(update):
        return ConversationHandler.END
    args = [a.upper() for a in update.message.text.strip().split()]
    await _do_rimuovi(update, args)
    return ConversationHandler.END


async def cmd_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_user(update):
        return
    tickers = load_watchlist()
    if not tickers:
        await update.message.reply_text("Watchlist vuota. Usa /aggiungi TICKER per iniziare.")
        return
    await update.message.reply_text(
        "📋 *Watchlist*\n\n" + "\n".join(f"• {t}" for t in tickers),
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_prezzo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_user(update):
        return
    if context.args:
        sym = context.args[0].upper()
        await update.message.reply_text("⏳ Recupero dati...")
        await update.message.reply_text(format_single(sym), parse_mode=ParseMode.MARKDOWN)
        return ConversationHandler.END
    await update.message.reply_text("Scrivi il ticker:")
    return WAITING_TICKER


async def cmd_prezzo_ticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_user(update):
        return ConversationHandler.END
    sym = update.message.text.strip().upper()
    await update.message.reply_text("⏳ Recupero dati...")
    await update.message.reply_text(format_single(sym), parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END


async def cmd_prezzo_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Annullato.")
    return ConversationHandler.END


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_user(update):
        return
    await update.message.reply_text("⏳ Genero report...")
    await update.message.reply_text(build_report(), parse_mode=ParseMode.MARKDOWN)


async def cmd_confronta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_user(update):
        return
    await update.message.reply_text("⏳ Calcolo confronto...")
    await update.message.reply_text(build_compare(), parse_mode=ParseMode.MARKDOWN)


async def cmd_stato(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_user(update):
        return
    state    = load_state()
    tickers  = load_watchlist()
    paused   = state.get("paused", False)
    status   = "⏸ In pausa" if paused else "✅ Attivo"
    await update.message.reply_text(
        f"*Stock monitor*\n\n"
        f"Stato: {status}\n"
        f"Ticker monitorati: {len(tickers)}\n"
        f"Report automatici: 09:30, 12:45 e 16:00 ET",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_pausa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_user(update):
        return
    state = load_state()
    state["paused"] = True
    save_state(state)
    await update.message.reply_text("⏸ Report automatici sospesi.")


async def cmd_riprendi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_user(update):
        return
    state = load_state()
    state["paused"] = False
    save_state(state)
    await update.message.reply_text("▶️ Report automatici riattivati.")


# ── Simulazione breakout (paperbook) ──────────────────────────────────────────

def _sim_state() -> dict:
    return pb_load_state()


async def cmd_sim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_admin(update):
        return
    state = _sim_state()
    if not state:
        await update.message.reply_text(
            "📈 Simulazione non inizializzata. Usa /sim_on per attivarla (capitale 500 €).",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    # prezzi live per lo stato
    import yfinance as yf
    fx = float(yf.Ticker("EURUSD=X").fast_info.last_price)
    pos = state.get("position")
    last_px = {}
    if pos:
        last_px[pos["symbol"]] = float(yf.Ticker(pos["symbol"]).fast_info.last_price)
    enabled = "✅ attiva" if state.get("enabled") else "⏸ in pausa"
    text = build_status(state, fx, last_px) + f"\n\nStato: {enabled}"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_sim_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_admin(update):
        return
    state = _sim_state()
    if not state:
        import yfinance as yf
        fx = float(yf.Ticker("EURUSD=X").fast_info.last_price)
        state = init_state(fx)
        pb_save_state(state)
    set_enabled(state, True)
    await update.message.reply_text(
        "📈 Simulazione breakout ATTIVA.\n"
        "Valutazione entry alle 09:35 ET, exit/checklist alle 16:10 ET.\n"
        "Report arrivano solo su operazione. Capitale 500 € su IBKR simulato.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_sim_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_admin(update):
        return
    state = _sim_state()
    if state:
        set_enabled(state, False)
    await update.message.reply_text("⏸ Simulazione breakout disattivata.")


async def cmd_sim_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_admin(update):
        return
    PB_STATE_FILE.unlink(missing_ok=True)
    await update.message.reply_text("🔄 Stato simulazione azzerato. Usa /sim_on per ripartire.")


# ── Scheduled report ──────────────────────────────────────────────────────────

async def job_report(context: ContextTypes.DEFAULT_TYPE):
    state = load_state()
    if state.get("paused"):
        return
    text = build_report()
    for uid in ALLOWED_USER_IDS:
        try:
            await context.bot.send_message(chat_id=uid, text=text, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            log.error("job_report → %s fallito: %s", uid, e)


async def _job_sim(context: ContextTypes.DEFAULT_TYPE, phase: str) -> None:
    state = _sim_state()
    if not state or not state.get("enabled"):
        return
    try:
        events, fx, last_px = live_step(phase, state)
    except Exception as e:
        log.error("job_sim %s → live_step fallito: %s", phase, e)
        return
    # report solo per operazioni eseguite (entry/exit), non per i signal
    for ev in events:
        if ev["kind"] not in ("entry", "exit"):
            continue
        text = build_event_report(state, ev, fx, last_px)
        for uid in ALLOWED_USER_IDS:
            try:
                await context.bot.send_message(chat_id=uid, text=text, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                log.error("job_sim → %s fallito: %s", uid, e)


async def job_sim_open(context: ContextTypes.DEFAULT_TYPE):
    await _job_sim(context, "open")


async def job_sim_close(context: ContextTypes.DEFAULT_TYPE):
    await _job_sim(context, "close")


# ── Message handler ───────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_admin(update):
        return

    history    = _get_history(context)
    user_text  = update.message.text or ""
    photo_path = None

    if update.message.photo:
        await update.message.reply_text(
            "🔍 *Analizzo con Claude...*", parse_mode=ParseMode.MARKDOWN
        )
        photo      = update.message.photo[-1]
        photo_file = await photo.get_file()
        tmp        = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        await photo_file.download_to_drive(custom_path=tmp.name)
        photo_path = tmp.name
        caption    = update.message.caption or "Descrivi e analizza questa immagine in dettaglio."
        user_text  = (
            f"L'utente ha mandato una foto. "
            f"Usa [ASK_CLAUDE: --image {photo_path} \"{caption}\"] "
            f"per analizzarla e poi rispondi con i dati."
        )

    if not user_text:
        return

    history.append({"role": "user", "content": user_text})
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    glm_reply = glm_call(history)

    thinking_msg = None

    async def on_thinking(kind: str):
        nonlocal thinking_msg
        label = "🔍 *Analizzo con Claude...*" if kind == "ASK_CLAUDE" else "⚙️ *Claude sta eseguendo...*"
        thinking_msg = await update.message.reply_text(label, parse_mode=ParseMode.MARKDOWN)
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)

    for _ in range(3):
        import asyncio
        bridge_result, found = process_markers(
            glm_reply,
            on_thinking=lambda k: asyncio.get_event_loop().run_until_complete(on_thinking(k))
        )
        if not found:
            break
        history.append({"role": "assistant", "content": glm_reply})
        history.append({
            "role": "user",
            "content": (
                f"[Sistema — risultato Claude]\n{bridge_result}\n\n"
                "Ora rispondi all'utente con questi dati in formato strutturato."
            )
        })
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        glm_reply = glm_call(history)

    history.append({"role": "assistant", "content": glm_reply})
    context.user_data["history"] = history

    if photo_path:
        Path(photo_path).unlink(missing_ok=True)

    try:
        await update.message.reply_text(glm_reply, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await update.message.reply_text(glm_reply)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("reset",    cmd_reset))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CommandHandler("watchlist", cmd_watchlist))
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("aggiungi", cmd_aggiungi)],
        states={WAITING_TICKER_ADD: [MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_aggiungi_input)]},
        fallbacks=[CommandHandler("annulla", cmd_prezzo_cancel)],
    ))
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("rimuovi", cmd_rimuovi)],
        states={WAITING_TICKER_REM: [MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_rimuovi_input)]},
        fallbacks=[CommandHandler("annulla", cmd_prezzo_cancel)],
    ))
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("prezzo", cmd_prezzo)],
        states={WAITING_TICKER: [MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_prezzo_ticker)]},
        fallbacks=[CommandHandler("annulla", cmd_prezzo_cancel)],
    ))
    app.add_handler(CommandHandler("report",   cmd_report))
    app.add_handler(CommandHandler("confronta", cmd_confronta))
    app.add_handler(CommandHandler("stato",    cmd_stato))
    app.add_handler(CommandHandler("pausa",    cmd_pausa))
    app.add_handler(CommandHandler("riprendi", cmd_riprendi))
    app.add_handler(CommandHandler("sim",      cmd_sim))
    app.add_handler(CommandHandler("sim_on",   cmd_sim_on))
    app.add_handler(CommandHandler("sim_off",  cmd_sim_off))
    app.add_handler(CommandHandler("sim_reset",cmd_sim_reset))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_message))

    app.job_queue.run_daily(job_report, time=dt_time(9, 30, tzinfo=ET_TZ),  name="report_open")
    app.job_queue.run_daily(job_report, time=dt_time(12, 45, tzinfo=ET_TZ), name="report_mid")
    app.job_queue.run_daily(job_report, time=dt_time(16, 0, tzinfo=ET_TZ), name="report_close")
    app.job_queue.run_daily(job_sim_open,  time=dt_time(9, 35, tzinfo=ET_TZ), name="sim_open")
    app.job_queue.run_daily(job_sim_close, time=dt_time(16, 10, tzinfo=ET_TZ), name="sim_close")

    log.info("Fasmagor avviato. In ascolto...")
    app.run_polling()


if __name__ == "__main__":
    main()
