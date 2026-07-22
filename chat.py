#!/usr/bin/env python3
"""Fasmagor — client TUI locale. GLM (Ollama) + Claude bridge."""

import re
import readline
import sys
from pathlib import Path

import requests
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from context import build_system_prompt
from bridge import process_markers

OLLAMA_URL    = "http://localhost:11434/api/chat"
GLM_MODEL     = "glm-5.2:cloud"
SYSTEM_PROMPT = build_system_prompt(fmt="tui")

console = Console()


def glm_call(history: list) -> str:
    resp = requests.post(
        OLLAMA_URL,
        json={"model": GLM_MODEL, "messages": history, "stream": False},
        timeout=300,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]


def print_header():
    console.print(Panel(
        "[bold cyan]Fasmagor[/] — chat locale\n"
        "[dim]GLM + Claude bridge  •  /reset  •  /quit  •  /img <path> <domanda>[/]",
        border_style="cyan",
        padding=(0, 2),
    ))


def print_user(text: str):
    console.print(Panel(
        Text(text, style="white"),
        title="[bold green]Tu[/]",
        title_align="right",
        border_style="green",
        padding=(0, 2),
    ))


def print_bot(text: str, thinking: bool = False):
    if thinking:
        console.print(Panel(
            "[dim italic]" + text + "[/]",
            title="[bold cyan]Fasmagor[/]",
            border_style="dim cyan",
            padding=(0, 2),
        ))
        return
    try:
        console.print(Panel(
            Markdown(text),
            title="[bold cyan]Fasmagor[/]",
            border_style="cyan",
            padding=(0, 2),
        ))
    except Exception:
        console.print(Panel(text, title="[bold cyan]Fasmagor[/]", border_style="cyan"))


def run():
    print_header()
    history = [{"role": "system", "content": SYSTEM_PROMPT}]

    while True:
        try:
            user_input = console.input("[bold green]>[/] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Arrivederci.[/]")
            sys.exit(0)

        if not user_input:
            continue

        if user_input.lower() in ("/quit", "/exit", "/q"):
            console.print("[dim]Arrivederci.[/]")
            sys.exit(0)

        if user_input.lower() == "/reset":
            history = [{"role": "system", "content": SYSTEM_PROMPT}]
            console.print("[dim]Conversazione resettata.[/]")
            continue

        # /img /percorso/foto.jpg [domanda opzionale]
        img_match = re.match(r"^/img\s+(\S+)\s*(.*)?$", user_input, re.IGNORECASE)
        if img_match:
            img_path = img_match.group(1)
            caption  = img_match.group(2) or "Descrivi e analizza questa immagine."
            print_user(f"[immagine: {img_path}] {caption}")
            user_input = (
                f"L'utente ha fornito un'immagine. "
                f"Usa [ASK_CLAUDE: --image {img_path} \"{caption}\"] "
                f"per analizzarla e rispondi con i dati."
            )
        else:
            print_user(user_input)

        history.append({"role": "user", "content": user_input})

        with console.status("[cyan]Fasmagor sta pensando...[/]", spinner="dots"):
            glm_reply = glm_call(history)

        # Intercetta marker — fino a 3 round
        for _ in range(3):
            def on_thinking(kind: str):
                label = "🔍 Analizzo con Claude..." if kind == "ASK_CLAUDE" else "⚙️ Claude sta eseguendo..."
                print_bot(label, thinking=True)

            bridge_result, found = process_markers(glm_reply, on_thinking=on_thinking)
            if not found:
                break
            history.append({"role": "assistant", "content": glm_reply})
            history.append({
                "role": "user",
                "content": (
                    f"[Sistema — risultato Claude]\n{bridge_result}\n\n"
                    "Rispondi all'utente con questi dati in formato Markdown strutturato."
                )
            })
            with console.status("[cyan]Elaboro risposta...[/]", spinner="dots"):
                glm_reply = glm_call(history)

        history.append({"role": "assistant", "content": glm_reply})
        print_bot(glm_reply)


if __name__ == "__main__":
    run()
