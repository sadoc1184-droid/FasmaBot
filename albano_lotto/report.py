"""Report giornaliero: dieci combinazioni per la prossima estrazione utile.

Progettato per essere consumato da un bot (Telegram, Discord, mail, qualunque
cosa): produce lo stesso contenuto in tre formati — testo, Markdown e JSON —
cosi' l'integrazione non deve reimplementare niente, solo scegliere il formato.

Il report porta sempre con se' l'avvertenza. Non e' un ornamento: e' l'unica
informazione del documento che ha valore economico dimostrabile.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .calibrate import load_calibration, select_diverse, variants_from_calibration
from .chart import ROME_TZ, erect_chart
from .data import next_draw_day
from .engine import ASTIENITI, consult
from .stats import expected_hits

COMBINAZIONI_DEFAULT = 10

# Calibrazione di serie, prodotta su 2.900 estrazioni reali (2009-2026). Viaggia
# col package cosi' `build_report()` funziona senza scaricare nulla: un bot che
# importa la libreria non deve prima fare scraping e calibrazione.
CALIBRAZIONE_DEFAULT = Path(__file__).parent / "dati" / "calibrazione-2009-2026.json"

AVVERTENZA = (
    "Le estrazioni del SuperEnalotto sono eventi indipendenti e uniformi. "
    "Queste combinazioni non valgono piu' di sei numeri scelti a caso: la "
    "probabilita' di centrare il 6 resta 1 su 622.614.630 e il valore atteso "
    "della giocata resta negativo. Report a scopo di studio, non un metodo di gioco."
)

NUMERO_VERDE = "800 558 822"

# Nomi espliciti: `%A` seguirebbe il locale del sistema, che su un server e'
# quasi sempre inglese e non e' garantito da una macchina all'altra.
GIORNI = (
    "lunedi'", "martedi'", "mercoledi'", "giovedi'",
    "venerdi'", "sabato", "domenica",
)
MESI = (
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
)


def giorno_esteso(momento: datetime) -> str:
    """Data in italiano, indipendente dal locale della macchina."""
    return (
        f"{GIORNI[momento.weekday()]} {momento.day} "
        f"{MESI[momento.month - 1]} {momento.year}"
    )


@dataclass(frozen=True)
class Combinazione:
    rank: int
    numeri: tuple[int, ...]
    z_train: float
    z_test: float
    variante: str


@dataclass(frozen=True)
class Report:
    """Contenuto del report, indipendente dal formato di uscita."""

    momento: datetime
    generato: datetime
    verdetto: str
    combinazioni: tuple[Combinazione, ...]
    jolly: int
    superstar: int
    n_variants: int
    expected_best_z: float
    motivazione: tuple[str, ...] = field(default=())

    @property
    def z_test_medio(self) -> float:
        if not self.combinazioni:
            return 0.0
        return sum(c.z_test for c in self.combinazioni) / len(self.combinazioni)

    def as_text(self) -> str:
        righe = [
            f"ASTROSOLDI — estrazione di {giorno_esteso(self.momento)} "
            f"ore {self.momento:%H:%M}",
            f"Generato il {self.generato:%d/%m/%Y %H:%M}",
            "",
            f"Verdetto orario Albano: {self.verdetto}",
        ]
        if self.verdetto == ASTIENITI:
            righe.append("  (la dottrina oraria sconsiglia la giocata per questa carta)")
        righe += ["", "Combinazioni:"]
        for c in self.combinazioni:
            righe.append(f"  {c.rank:2d}.  " + "  ".join(f"{n:2d}" for n in c.numeri))
        righe += [
            "",
            f"Jolly suggerito: {self.jolly}    SuperStar: {self.superstar}",
            "",
            f"Attesa teorica: {expected_hits():.1f} numeri indovinati per combinazione.",
            f"z medio fuori campione delle varianti usate: {self.z_test_medio:+.2f} "
            "(indistinguibile da zero).",
            "",
            AVVERTENZA,
            f"Gioco d'azzardo problematico: numero verde {NUMERO_VERDE}.",
        ]
        return "\n".join(righe)

    def as_markdown(self) -> str:
        righe = [
            f"# Astrosoldi — {self.momento:%d/%m/%Y}",
            "",
            f"**Estrazione**: {giorno_esteso(self.momento)}, ore {self.momento:%H:%M}  ",
            f"**Verdetto orario Albano**: `{self.verdetto}`",
            "",
            "## Combinazioni",
            "",
            "| # | numeri | z train | z test |",
            "|---:|---|---:|---:|",
        ]
        for c in self.combinazioni:
            numeri = " · ".join(f"{n}" for n in c.numeri)
            righe.append(f"| {c.rank} | {numeri} | {c.z_train:+.2f} | {c.z_test:+.2f} |")
        righe += [
            "",
            f"**Jolly**: {self.jolly} — **SuperStar**: {self.superstar}",
            "",
            "## Lettura onesta",
            "",
            f"- Attesa teorica: **{expected_hits():.1f}** numeri indovinati per combinazione.",
            f"- z medio fuori campione delle varianti usate: **{self.z_test_medio:+.2f}**.",
            f"- Le varianti provengono da una ricerca su **{self.n_variants:,}** "
            f"configurazioni, dove il solo rumore raggiunge z = "
            f"**{self.expected_best_z:+.2f}**.",
            "",
            f"> {AVVERTENZA}",
            f">",
            f"> Gioco d'azzardo problematico: numero verde **{NUMERO_VERDE}**.",
        ]
        return "\n".join(righe)

    def as_json(self) -> str:
        return json.dumps(
            {
                "estrazione": self.momento.isoformat(),
                "generato": self.generato.isoformat(),
                "verdetto": self.verdetto,
                "combinazioni": [
                    {
                        "rank": c.rank,
                        "numeri": list(c.numeri),
                        "z_train": c.z_train,
                        "z_test": c.z_test,
                        "variante": c.variante,
                    }
                    for c in self.combinazioni
                ],
                "jolly": self.jolly,
                "superstar": self.superstar,
                "attesa_teorica_centri": expected_hits(),
                "z_test_medio": self.z_test_medio,
                "n_variants": self.n_variants,
                "expected_best_z": self.expected_best_z,
                "avvertenza": AVVERTENZA,
                "numero_verde_gioco_azzardo": NUMERO_VERDE,
            },
            ensure_ascii=False,
            indent=2,
        )


def build_report(
    calibrazione: str | Path | None = None,
    momento: datetime | None = None,
    quante: int = COMBINAZIONI_DEFAULT,
    diversifica: bool = True,
) -> Report:
    """Costruisce il report per la prossima estrazione utile (o per una data data)."""
    if calibrazione is None:
        calibrazione = CALIBRAZIONE_DEFAULT
    if momento is None:
        momento = next_draw_day(datetime.now(tz=ROME_TZ))

    chart = erect_chart(momento)
    pick = consult(momento)
    payload = load_calibration(str(calibrazione))

    if diversifica:
        candidate = variants_from_calibration(payload, len(payload["ranked"]))
        scelte = select_diverse(candidate, chart, quante)
    else:
        scelte = variants_from_calibration(payload, quante)

    combinazioni = tuple(
        Combinazione(
            rank=rank,
            numeri=variant.numbers_for(chart),
            z_train=metrics["z_train"],
            z_test=metrics["z_test"],
            variante=variant.label(),
        )
        for rank, (variant, metrics) in enumerate(scelte, start=1)
    )

    return Report(
        momento=momento,
        generato=datetime.now(tz=ROME_TZ),
        verdetto=pick.verdict,
        combinazioni=combinazioni,
        jolly=pick.jolly,
        superstar=pick.superstar,
        n_variants=payload["n_variants"],
        expected_best_z=payload["expected_best_z"],
        motivazione=pick.reasoning,
    )


def render(report: Report, formato: str) -> str:
    match formato:
        case "testo":
            return report.as_text()
        case "markdown":
            return report.as_markdown()
        case "json":
            return report.as_json()
        case _:
            raise ValueError(f"formato non riconosciuto: {formato}")
