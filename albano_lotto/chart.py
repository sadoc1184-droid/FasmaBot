"""Erezione della carta oraria con Swiss Ephemeris.

Stessa libreria usata da `projects/tarshishbot` (pyswisseph), non `ephem`:
la velocita' e' restituita direttamente dalle effemeridi, quindi stazioni e
retrogradazioni sono esatte e non stimate per differenza tra due giorni.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import swisseph as swe

from .dignities import (
    ANGULAR,
    DOMICILE,
    PLANETS,
    degree_in_sign,
    essential_dignity,
    sign_of,
)

# Luogo di riferimento: Roma, sede dell'estrazione SuperEnalotto.
ROME_LAT = 41.9028
ROME_LON = 12.4964
ROME_TZ = ZoneInfo("Europe/Rome")

_SWE_IDS = {
    "Sole": swe.SUN, "Luna": swe.MOON, "Mercurio": swe.MERCURY,
    "Venere": swe.VENUS, "Marte": swe.MARS, "Giove": swe.JUPITER,
    "Saturno": swe.SATURN,
}

_FLAGS = swe.FLG_SWIEPH | swe.FLG_SPEED

# Orbite tradizionali usate per gli aspetti applicativi tra significatori.
ASPECTS = {
    "congiunzione": 0.0,
    "sestile": 60.0,
    "quadrato": 90.0,
    "trigono": 120.0,
    "opposizione": 180.0,
}
HARMONIC = {"sestile", "trigono"}
DISHARMONIC = {"quadrato", "opposizione"}
ASPECT_ORB = 6.0


@dataclass(frozen=True)
class Planet:
    name: str
    longitude: float
    speed: float
    speed_tomorrow: float
    house: int

    @property
    def sign(self) -> str:
        return sign_of(self.longitude)

    @property
    def degree(self) -> float:
        return degree_in_sign(self.longitude)

    @property
    def is_retrograde(self) -> bool:
        return self.speed < 0

    def __str__(self) -> str:
        mark = " R" if self.is_retrograde else ""
        return f"{self.name} {self.degree:.2f}° {self.sign} (casa {self.house}){mark}"


@dataclass(frozen=True)
class Aspect:
    """Aspetto tra due pianeti, con distinzione applicativo/separativo."""

    first: str
    second: str
    kind: str
    orb: float
    applying: bool

    @property
    def is_harmonic(self) -> bool:
        return self.kind in HARMONIC

    @property
    def is_disharmonic(self) -> bool:
        return self.kind in DISHARMONIC


@dataclass(frozen=True)
class Chart:
    """Carta oraria completa per un istante e un luogo."""

    moment_utc: datetime
    moment_local: datetime
    latitude: float
    longitude: float
    cusps: tuple[float, ...]          # 12 cuspidi, indice 0 = casa 1
    asc: float
    mc: float
    planets: dict[str, Planet]
    is_day: bool

    def house_of(self, longitude: float) -> int:
        """Casa che contiene una longitudine, con cuspidi in ordine ciclico."""
        for i in range(12):
            start = self.cusps[i]
            end = self.cusps[(i + 1) % 12]
            span = (end - start) % 360.0
            offset = (longitude - start) % 360.0
            if offset < span:
                return i + 1
        return 12

    def lord_of_house(self, house: int) -> str:
        """Signore della casa: pianeta che governa il segno sulla cuspide."""
        return DOMICILE[sign_of(self.cusps[house - 1])]

    def part_of_fortune(self) -> float:
        """Parte di Fortuna, con la formula invertita nelle carte notturne."""
        sun = self.planets["Sole"].longitude
        moon = self.planets["Luna"].longitude
        if self.is_day:
            return (self.asc + moon - sun) % 360.0
        return (self.asc + sun - moon) % 360.0

    def essential_score(self, planet_name: str) -> int:
        p = self.planets[planet_name]
        return essential_dignity(p.name, p.longitude, self.is_day).score

    def most_dignified(self, exclude: set[str] | None = None) -> str:
        """Pianeta con la maggiore dignita' essenziale (ties sciolti per ordine caldeo)."""
        skip = exclude or set()
        candidates = [p for p in PLANETS if p not in skip]
        return max(candidates, key=lambda p: (self.essential_score(p), -PLANETS.index(p)))


def _julian_day(moment_utc: datetime) -> float:
    hour = moment_utc.hour + moment_utc.minute / 60.0 + moment_utc.second / 3600.0
    return swe.julday(moment_utc.year, moment_utc.month, moment_utc.day, hour)


def erect_chart(
    moment_local: datetime,
    latitude: float = ROME_LAT,
    longitude: float = ROME_LON,
) -> Chart:
    """Costruisce la carta oraria per un momento locale (default: Roma, Placidus)."""
    if moment_local.tzinfo is None:
        moment_local = moment_local.replace(tzinfo=ROME_TZ)
    moment_utc = moment_local.astimezone(timezone.utc)

    jd = _julian_day(moment_utc)
    jd_tomorrow = _julian_day(moment_utc + timedelta(days=1))

    swe.set_ephe_path(None)
    cusps, ascmc = swe.houses(jd, latitude, longitude, b"P")
    asc, mc = ascmc[0], ascmc[1]

    raw: dict[str, tuple[float, float, float]] = {}
    for name, pid in _SWE_IDS.items():
        pos, _ = swe.calc_ut(jd, pid, _FLAGS)
        pos_next, _ = swe.calc_ut(jd_tomorrow, pid, _FLAGS)
        raw[name] = (pos[0] % 360.0, pos[3], pos_next[3])

    # La carta e' diurna se il Sole e' sopra l'orizzonte (case 7-12).
    skeleton = Chart(
        moment_utc=moment_utc, moment_local=moment_local,
        latitude=latitude, longitude=longitude,
        cusps=tuple(cusps[:12]), asc=asc, mc=mc, planets={}, is_day=True,
    )
    sun_house = skeleton.house_of(raw["Sole"][0])
    is_day = 7 <= sun_house <= 12

    planets = {
        name: Planet(
            name=name, longitude=lon, speed=spd, speed_tomorrow=spd_next,
            house=skeleton.house_of(lon),
        )
        for name, (lon, spd, spd_next) in raw.items()
    }

    return Chart(
        moment_utc=moment_utc, moment_local=moment_local,
        latitude=latitude, longitude=longitude,
        cusps=tuple(cusps[:12]), asc=asc, mc=mc,
        planets=planets, is_day=is_day,
    )


def find_aspect(chart: Chart, first: str, second: str) -> Aspect | None:
    """Primo aspetto maggiore entro l'orbita tra due pianeti, se esiste.

    Applicativo = la separazione angolare si sta riducendo, cioe' l'aspetto si
    perfeziona nel futuro (Albano, Passo 3).
    """
    a, b = chart.planets[first], chart.planets[second]
    diff = abs((a.longitude - b.longitude + 180.0) % 360.0 - 180.0)

    for kind, exact in ASPECTS.items():
        orb = abs(diff - exact)
        if orb > ASPECT_ORB:
            continue
        # Proiezione a breve termine per capire se l'orbita si stringe.
        step = 0.05
        a_next = a.longitude + a.speed * step
        b_next = b.longitude + b.speed * step
        diff_next = abs((a_next - b_next + 180.0) % 360.0 - 180.0)
        applying = abs(diff_next - exact) < orb
        return Aspect(first=first, second=second, kind=kind, orb=orb, applying=applying)
    return None


def moon_is_void_of_course(chart: Chart) -> bool:
    """Luna in corsa a vuoto: nessun aspetto applicativo prima di cambiare segno.

    Condizione di HOLD nella metodologia Albano (Passo 4).
    """
    moon = chart.planets["Luna"]
    for other in PLANETS:
        if other == "Luna":
            continue
        aspect = find_aspect(chart, "Luna", other)
        if aspect is not None and aspect.applying:
            return False
    return True


def is_angular(chart: Chart, planet_name: str) -> bool:
    return chart.planets[planet_name].house in ANGULAR
