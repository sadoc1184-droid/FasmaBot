"""Albano-Lotto — metodologia oraria Albano applicata al SuperEnalotto.

Progetto di ricerca metodologica, non uno strumento di gioco: vedi README.md.
"""

from .chart import Chart, erect_chart
from .engine import ASTIENITI, GIOCA, INCERTO, Pick, consult
from .validate import format_report, run_benchmark

__version__ = "0.1.0"

__all__ = [
    "Chart",
    "erect_chart",
    "consult",
    "Pick",
    "GIOCA",
    "ASTIENITI",
    "INCERTO",
    "run_benchmark",
    "format_report",
]
