"""Motore Albano adattato alla domanda oraria sul SuperEnalotto.

Trasposizione delle regole di `METODOLOGIA_ORARIA_ALBANO.md` dal dominio
"come andra' il titolo X" al dominio "come andra' la giocata".

Differenza dottrinale rispetto al bot di trading: nell'oraria tradizionale la
speculazione e i giochi d'azzardo appartengono alla **quinta casa**, mentre la
seconda resta la casa del denaro guadagnato. Il significatore primario qui e'
quindi il Signore della 5a (l'esito del gioco), e il Signore della 2a diventa
il significatore del guadagno: la testimonianza classica di vincita e' un
aspetto applicativo tra i due.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .chart import (
    Chart,
    erect_chart,
    find_aspect,
    moon_is_void_of_course,
)
from .dignities import (
    BENEFICS,
    MALEFICS,
    angular_score,
    essential_dignity,
    motion_condition,
    solar_condition,
)
from .mapping import longitude_to_number, resolve_collisions

# Il verdetto sostituisce LONG/SHORT/HOLD del bot di trading.
GIOCA = "GIOCA"
ASTIENITI = "ASTIENITI"
INCERTO = "INCERTO"


@dataclass(frozen=True)
class PlanetStrength:
    """Forza complessiva di un significatore, essenziale + accidentale."""

    planet: str
    essential: int
    accidental: int
    labels: tuple[str, ...]

    @property
    def total(self) -> int:
        return self.essential + self.accidental


@dataclass(frozen=True)
class Pick:
    """Esito completo di una consultazione."""

    moment_local: datetime
    verdict: str
    numbers: tuple[int, ...]
    jolly: int
    superstar: int
    significators: dict[str, str]
    strengths: tuple[PlanetStrength, ...]
    reasoning: tuple[str, ...] = field(default=())

    def format_report(self) -> str:
        lines = [
            f"Estrazione del {self.moment_local:%d/%m/%Y %H:%M} (Roma)",
            f"Verdetto orario: {self.verdict}",
            "",
            "Significatori:",
        ]
        lines += [f"  {role:28s} {planet}" for role, planet in self.significators.items()]
        lines += ["", "Forze:"]
        for s in self.strengths:
            lines.append(
                f"  {s.planet:9s} essenziale {s.essential:+3d}  accidentale {s.accidental:+3d}"
                f"  totale {s.total:+3d}   [{', '.join(s.labels)}]"
            )
        lines += [
            "",
            f"Numeri:    {'  '.join(f'{n:2d}' for n in self.numbers)}",
            f"Jolly:     {self.jolly}",
            f"SuperStar: {self.superstar}",
            "",
            "Giudizio:",
        ]
        lines += [f"  - {r}" for r in self.reasoning]
        return "\n".join(lines)


def compute_strength(chart: Chart, planet_name: str) -> PlanetStrength:
    """Somma dignita' essenziali e accidentali secondo la tabella Albano."""
    planet = chart.planets[planet_name]
    ess = essential_dignity(planet.name, planet.longitude, chart.is_day)

    house_pts, house_label = angular_score(planet.house)
    solar_pts, solar_label = solar_condition(
        planet.name, planet.longitude, chart.planets["Sole"].longitude
    )
    motion_pts, motion_label = motion_condition(
        planet.name, planet.speed, planet.speed_tomorrow
    )

    return PlanetStrength(
        planet=planet_name,
        essential=ess.score,
        accidental=house_pts + solar_pts + motion_pts,
        labels=ess.labels + (house_label, solar_label, motion_label),
    )


def identify_significators(chart: Chart) -> dict[str, str]:
    """Gerarchia dei significatori per la domanda sul gioco.

    L'ordine del dizionario e' la gerarchia: determina l'ordine con cui i
    numeri vengono estratti e quindi la precedenza in caso di collisione.
    """
    lord_5 = chart.lord_of_house(5)
    lord_2 = chart.lord_of_house(2)
    lord_1 = chart.lord_of_house(1)
    assigned = {lord_5, lord_2, lord_1, "Luna", "Giove"}

    return {
        "Signore della 5a (gioco)": lord_5,
        "Signore della 2a (guadagno)": lord_2,
        "Luna (flusso)": "Luna",
        "Signore dell'Asc (giocatore)": lord_1,
        "Giove (fortuna)": "Giove",
        "Almuten (piu' dignificato)": chart.most_dignified(exclude=assigned),
    }


def judge(chart: Chart, significators: dict[str, str]) -> tuple[str, list[str]]:
    """Applica il Passo 4 di Albano: sintesi gerarchica in un verdetto."""
    lord_5 = significators["Signore della 5a (gioco)"]
    lord_2 = significators["Signore della 2a (guadagno)"]
    reasoning: list[str] = []

    if moon_is_void_of_course(chart):
        reasoning.append(
            "Luna in corsa a vuoto: nessun aspetto applicativo prima di cambiare "
            "segno. Nella dottrina oraria significa 'non accadra' nulla'."
        )
        return ASTIENITI, reasoning

    strength_5 = compute_strength(chart, lord_5)
    strength_2 = compute_strength(chart, lord_2)
    reasoning.append(
        f"Signore della 5a = {lord_5} (forza {strength_5.total:+d}); "
        f"Signore della 2a = {lord_2} (forza {strength_2.total:+d})."
    )

    positives = 0
    negatives = 0

    if lord_5 == lord_2:
        positives += 1
        reasoning.append(
            f"{lord_5} governa sia la 5a sia la 2a: gioco e guadagno hanno un "
            "unico significatore, testimonianza di collegamento diretto."
        )
    else:
        aspect = find_aspect(chart, lord_5, lord_2)
        if aspect is None:
            reasoning.append(
                f"Nessun aspetto maggiore tra {lord_5} e {lord_2}: i significatori "
                "di gioco e guadagno non si parlano."
            )
        elif not aspect.applying:
            reasoning.append(
                f"Aspetto di {aspect.kind} tra {lord_5} e {lord_2} separativo "
                f"(orbita {aspect.orb:.2f}°): appartiene al passato, non all'esito."
            )
        elif aspect.is_harmonic:
            positives += 2
            reasoning.append(
                f"Aspetto applicativo armonico ({aspect.kind}, orbita "
                f"{aspect.orb:.2f}°) tra {lord_5} e {lord_2}: testimonianza positiva."
            )
        elif aspect.is_disharmonic:
            negatives += 2
            reasoning.append(
                f"Aspetto applicativo disarmonico ({aspect.kind}, orbita "
                f"{aspect.orb:.2f}°) tra {lord_5} e {lord_2} senza ricezione."
            )
        else:
            target = lord_2 if aspect.first == lord_5 else lord_5
            if target in BENEFICS:
                positives += 1
                reasoning.append(f"Congiunzione con benefico ({target}): esito migliorato.")
            elif target in MALEFICS:
                negatives += 1
                reasoning.append(f"Congiunzione con malefico ({target}): esito peggiorato.")

    for label, strength in (("5a", strength_5), ("2a", strength_2)):
        if "combusto" in " ".join(strength.labels):
            negatives += 1
            reasoning.append(f"Signore della {label} ({strength.planet}) combusto: accecato.")
        if "prima stazione" in " ".join(strength.labels):
            negatives += 1
            reasoning.append(
                f"Signore della {label} ({strength.planet}) alla prima stazione: "
                "peggioramento imminente."
            )
        if "seconda stazione" in " ".join(strength.labels):
            positives += 1
            reasoning.append(
                f"Signore della {label} ({strength.planet}) alla seconda stazione: "
                "miglioramento imminente."
            )
        if strength.total <= -6:
            negatives += 1
            reasoning.append(
                f"Signore della {label} ({strength.planet}) gravemente debilitato "
                f"(forza {strength.total:+d})."
            )

    if positives > negatives:
        return GIOCA, reasoning
    if negatives > positives:
        return ASTIENITI, reasoning
    reasoning.append("Testimonianze equamente contraddittorie.")
    return INCERTO, reasoning


def consult(
    moment_local: datetime,
    latitude: float | None = None,
    longitude: float | None = None,
) -> Pick:
    """Consultazione completa: erige la carta, giudica, estrae i numeri."""
    kwargs = {}
    if latitude is not None:
        kwargs["latitude"] = latitude
    if longitude is not None:
        kwargs["longitude"] = longitude
    chart = erect_chart(moment_local, **kwargs)

    significators = identify_significators(chart)
    verdict, reasoning = judge(chart, significators)

    raw_numbers = [
        longitude_to_number(chart.planets[planet].longitude)
        for planet in significators.values()
    ]
    numbers = resolve_collisions(raw_numbers)

    jolly = longitude_to_number(chart.part_of_fortune())
    superstar = longitude_to_number(chart.mc)

    strengths = tuple(
        compute_strength(chart, planet) for planet in dict.fromkeys(significators.values())
    )

    return Pick(
        moment_local=chart.moment_local,
        verdict=verdict,
        numbers=tuple(sorted(numbers)),
        jolly=jolly,
        superstar=superstar,
        significators=significators,
        strengths=strengths,
        reasoning=tuple(reasoning),
    )
