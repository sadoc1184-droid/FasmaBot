"""Calibrazione delle varianti del motore orario, con validazione fuori campione.

Questo modulo fa deliberatamente la cosa che tutti chiedono a un backtest:
cerca, tra molte varianti del sistema, quella che avrebbe funzionato meglio sul
passato. Poi fa la cosa che quasi nessuno fa: misura quella stessa variante su
un periodo che la ricerca non ha mai visto.

La distanza tra i due numeri e' il prodotto principale del modulo.

## Perche' la ricerca e' esaustiva e istantanea

Una variante e' definita da:
  - `sources`: 6 punti della carta scelti da un insieme di 14;
  - `offset`:  rotazione della mappatura zodiaco -> tabellone (0-89).

Sono C(14,6) x 90 = 270.270 varianti. Valutarle una a una su 4.000 estrazioni
sarebbe un miliardo di operazioni, ma non serve: i centri di una variante sono
la somma dei centri dei suoi 6 punti presi singolarmente. Basta tabulare
`H[punto][offset]` una volta (1.260 valori) e ogni variante diventa la somma di
sei numeri gia' pronti.

L'approssimazione: la somma per punto ignora le collisioni (due punti nello
stesso arco di 4°, che ridurrebbero i numeri distinti giocati). Le varianti
selezionate vengono quindi ri-verificate con il conteggio esatto.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import combinations
from math import log, sqrt
from pathlib import Path
from typing import Sequence

from .chart import Chart, erect_chart
from .data import Draw
from .mapping import DEGREES_PER_NUMBER, LOTTO_MAX
from .stats import expected_hits, hits_variance

# I 14 punti candidati: i 7 pianeti tradizionali, i due assi, la Parte di
# Fortuna e le cuspidi delle case che la tradizione lega a denaro, gioco,
# beni altrui e speranze.
SOURCES = (
    "Sole", "Luna", "Mercurio", "Venere", "Marte", "Giove", "Saturno",
    "ASC", "MC", "Fortuna", "cuspide2", "cuspide5", "cuspide8", "cuspide11",
)

PICK_SIZE = 6
N_OFFSETS = LOTTO_MAX


def source_longitudes(chart: Chart) -> dict[str, float]:
    """Longitudine eclittica di ognuno dei punti candidati."""
    values = {name: chart.planets[name].longitude for name in chart.planets}
    values["ASC"] = chart.asc
    values["MC"] = chart.mc
    values["Fortuna"] = chart.part_of_fortune()
    for house in (2, 5, 8, 11):
        values[f"cuspide{house}"] = chart.cusps[house - 1]
    return values


def base_number(longitude: float) -> int:
    """Indice 0-89 della mappatura, prima della rotazione."""
    return int((longitude % 360.0) // DEGREES_PER_NUMBER)


def rotated(base: int, offset: int) -> int:
    """Numero 1-90 dopo la rotazione della mappatura."""
    return (base + offset) % LOTTO_MAX + 1


@dataclass(frozen=True)
class Variant:
    """Una configurazione del motore: quali punti si leggono e con che rotazione."""

    sources: tuple[str, ...]
    offset: int

    def numbers_for(self, chart: Chart) -> tuple[int, ...]:
        """Sestina esatta, con risoluzione delle collisioni."""
        from .mapping import resolve_collisions

        longitudes = source_longitudes(chart)
        raw = [rotated(base_number(longitudes[s]), self.offset) for s in self.sources]
        return tuple(sorted(resolve_collisions(raw)))

    def label(self) -> str:
        return f"offset {self.offset:2d} | {'+'.join(self.sources)}"


@dataclass(frozen=True)
class Fold:
    """Un insieme di estrazioni gia' ridotto a tabella punto x offset."""

    name: str
    draws: int
    hits: dict[str, list[int]]      # punto -> centri totali per offset

    def variant_hits(self, variant: Variant) -> int:
        return sum(self.hits[s][variant.offset] for s in variant.sources)

    def mean_hits(self, variant: Variant) -> float:
        return self.variant_hits(variant) / self.draws if self.draws else 0.0

    def z_score(self, variant: Variant) -> float:
        if not self.draws:
            return 0.0
        sigma = sqrt(hits_variance() / self.draws)
        return (self.mean_hits(variant) - expected_hits()) / sigma


def build_fold(name: str, draws: Sequence[Draw]) -> Fold:
    """Tabula i centri di ogni punto a ogni rotazione, su un insieme di estrazioni.

    E' l'unico passaggio costoso: una carta oraria per estrazione.
    """
    hits: dict[str, list[int]] = {s: [0] * N_OFFSETS for s in SOURCES}

    for draw in draws:
        chart = erect_chart(draw.moment)
        longitudes = source_longitudes(chart)
        drawn = set(draw.numbers)
        for source in SOURCES:
            base = base_number(longitudes[source])
            row = hits[source]
            for offset in range(N_OFFSETS):
                if rotated(base, offset) in drawn:
                    row[offset] += 1

    return Fold(name=name, draws=len(draws), hits=hits)


def all_variants() -> list[Variant]:
    """Enumerazione completa dello spazio di ricerca."""
    return [
        Variant(sources=combo, offset=offset)
        for combo in combinations(SOURCES, PICK_SIZE)
        for offset in range(N_OFFSETS)
    ]


def expected_best_z(n_variants: int) -> float:
    """Massimo z atteso cercando fra n varianti indipendenti di puro rumore.

    Approssimazione classica del massimo di n normali standard: sqrt(2 ln n).
    Serve come metro di paragone: se il miglior z trovato e' vicino a questo
    valore, la ricerca non ha trovato un segnale, ha trovato il rumore piu'
    fortunato.
    """
    return sqrt(2.0 * log(n_variants)) if n_variants > 1 else 0.0


@dataclass(frozen=True)
class CalibrationResult:
    train: Fold
    test: Fold
    ranked: tuple[tuple[Variant, float], ...]   # (variante, z sul training)
    n_variants: int

    @property
    def best(self) -> Variant:
        return self.ranked[0][0]

    def report(self, top: int = 10) -> str:
        lines = [
            "CALIBRAZIONE CON VALIDAZIONE FUORI CAMPIONE",
            "=" * 78,
            "",
            f"Spazio di ricerca: {self.n_variants:,} varianti "
            f"(C(14,6) combinazioni di punti x {N_OFFSETS} rotazioni).",
            f"Training: {self.train.draws:,} estrazioni | "
            f"Test (mai visto dalla ricerca): {self.test.draws:,} estrazioni.",
            "",
            f"Massimo z atteso dal solo rumore su {self.n_variants:,} varianti: "
            f"{expected_best_z(self.n_variants):+.2f}",
            "",
            f"{'#':>3s} {'variante':52s} {'z train':>8s} {'z test':>8s}",
            "-" * 78,
        ]
        for rank, (variant, z_train) in enumerate(self.ranked[:top], start=1):
            lines.append(
                f"{rank:3d} {variant.label():52s} {z_train:+8.2f} "
                f"{self.test.z_score(variant):+8.2f}"
            )

        best_train = self.ranked[0][1]
        best_test = self.test.z_score(self.best)
        top_variants = [v for v, _ in self.ranked[:top]]
        mean_test = sum(self.test.z_score(v) for v in top_variants) / len(top_variants)

        lines += [
            "",
            "LETTURA",
            "-" * 78,
            f"Miglior z in campione: {best_train:+.2f}. "
            f"Atteso dal rumore: {expected_best_z(self.n_variants):+.2f}.",
            f"Stessa variante fuori campione: {best_test:+.2f}.",
            f"Media fuori campione delle prime {top}: {mean_test:+.2f}.",
            "",
        ]
        if best_train >= expected_best_z(self.n_variants) * 0.7:
            lines.append(
                "Il miglior risultato in campione e' dell'ordine di grandezza che il "
                "puro rumore produce cercando in uno spazio di questa dimensione: "
                "non e' una scoperta, e' il massimo di molti tentativi."
            )
        if abs(best_test) < 2.0:
            lines.append(
                "Fuori campione la variante selezionata rientra nell'attesa teorica: "
                "l'edge apparente non sopravvive ai dati che non ha visto."
            )
        return "\n".join(lines)


def save_calibration(result: CalibrationResult, path: str) -> None:
    """Serializza la classifica per riusarla in fase di previsione."""
    payload = {
        "n_variants": result.n_variants,
        "train_draws": result.train.draws,
        "test_draws": result.test.draws,
        "expected_best_z": expected_best_z(result.n_variants),
        "ranked": [
            {
                "sources": list(v.sources),
                "offset": v.offset,
                "z_train": z,
                "z_test": result.test.z_score(v),
            }
            for v, z in result.ranked
        ],
    }
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_calibration(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def variants_from_calibration(payload: dict, count: int) -> list[tuple[Variant, dict]]:
    """Prime `count` varianti della classifica, con le loro metriche."""
    out: list[tuple[Variant, dict]] = []
    for entry in payload["ranked"][:count]:
        out.append((Variant(sources=tuple(entry["sources"]), offset=entry["offset"]), entry))
    return out


def select_diverse(
    ranked: Sequence[tuple[Variant, dict]],
    chart: Chart,
    count: int,
    max_overlap: int = 1,
) -> list[tuple[Variant, dict]]:
    """Sceglie varianti che producono sestine poco sovrapposte fra loro.

    Le varianti in testa alla classifica tendono a condividere punti e offset,
    quindi generano quasi la stessa sestina. Il valore atteso non cambia — nessuna
    combinazione vale piu' di un'altra — ma giocare sestine sovrapposte copre meno
    numeri distinti, e a parita' di spesa riduce la probabilita' di prendere una
    vincita piccola. La selezione scorre la classifica in ordine e accetta una
    variante solo se la sua sestina non condivide piu' di `max_overlap` numeri con
    quelle gia' scelte, allargando la soglia se le candidate finiscono.
    """
    scelte: list[tuple[Variant, dict]] = []
    numeri_scelti: list[set[int]] = []

    for soglia in range(max_overlap, PICK_SIZE + 1):
        for variant, metrics in ranked:
            if len(scelte) >= count:
                return scelte
            if any(v.sources == variant.sources and v.offset == variant.offset
                   for v, _ in scelte):
                continue
            numeri = set(variant.numbers_for(chart))
            if all(len(numeri & altri) <= soglia for altri in numeri_scelti):
                scelte.append((variant, metrics))
                numeri_scelti.append(numeri)
        if len(scelte) >= count:
            break

    return scelte[:count]


def calibrate(
    draws: Sequence[Draw], train_ratio: float = 0.7, top: int = 50
) -> CalibrationResult:
    """Cerca la variante migliore sul training e la misura sul test.

    Lo split e' temporale, non casuale: il test e' il periodo piu' recente, come
    dovrebbe essere in qualunque backtest che pretenda di dire qualcosa sul
    futuro.
    """
    ordered = sorted(draws, key=lambda d: d.moment)
    cut = int(len(ordered) * train_ratio)
    train = build_fold("train", ordered[:cut])
    test = build_fold("test", ordered[cut:])

    variants = all_variants()
    scored = [(v, train.z_score(v)) for v in variants]
    scored.sort(key=lambda pair: pair[1], reverse=True)

    return CalibrationResult(
        train=train, test=test,
        ranked=tuple(scored[:top]), n_variants=len(variants),
    )
