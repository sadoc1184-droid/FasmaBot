"""Dignita' essenziali e accidentali secondo la tabella tradizionale (Lilly).

Le tabelle e i punteggi replicano `docs/METODOLOGIA_ORARIA_ALBANO.md` di
tarshishbot, sezione "Passo 2: Valutazione della Forza".
"""

from __future__ import annotations

from dataclasses import dataclass

SIGNS = [
    "Ariete", "Toro", "Gemelli", "Cancro", "Leone", "Vergine",
    "Bilancia", "Scorpione", "Sagittario", "Capricorno", "Acquario", "Pesci",
]

PLANETS = ["Sole", "Luna", "Mercurio", "Venere", "Marte", "Giove", "Saturno"]

BENEFICS = {"Venere", "Giove"}
MALEFICS = {"Marte", "Saturno"}

# Domicilio: segno -> pianeta signore.
DOMICILE = {
    "Ariete": "Marte", "Toro": "Venere", "Gemelli": "Mercurio",
    "Cancro": "Luna", "Leone": "Sole", "Vergine": "Mercurio",
    "Bilancia": "Venere", "Scorpione": "Marte", "Sagittario": "Giove",
    "Capricorno": "Saturno", "Acquario": "Saturno", "Pesci": "Giove",
}

# Esaltazione: segno -> pianeta (il grado esatto non incide sul punteggio).
EXALTATION = {
    "Ariete": "Sole", "Toro": "Luna", "Cancro": "Giove", "Vergine": "Mercurio",
    "Bilancia": "Saturno", "Capricorno": "Marte", "Pesci": "Venere",
}

# Triplicita' dorotea: elemento -> (signore diurno, notturno, partecipante).
TRIPLICITY = {
    "fuoco": ("Sole", "Giove", "Saturno"),
    "terra": ("Venere", "Luna", "Marte"),
    "aria": ("Saturno", "Mercurio", "Giove"),
    "acqua": ("Venere", "Marte", "Luna"),
}

ELEMENT_OF_SIGN = {
    "Ariete": "fuoco", "Leone": "fuoco", "Sagittario": "fuoco",
    "Toro": "terra", "Vergine": "terra", "Capricorno": "terra",
    "Gemelli": "aria", "Bilancia": "aria", "Acquario": "aria",
    "Cancro": "acqua", "Scorpione": "acqua", "Pesci": "acqua",
}

# Termini egizi: segno -> lista (pianeta, grado di fine del termine).
TERMS = {
    "Ariete": [("Giove", 6), ("Venere", 12), ("Mercurio", 20), ("Marte", 25), ("Saturno", 30)],
    "Toro": [("Venere", 8), ("Mercurio", 14), ("Giove", 22), ("Saturno", 27), ("Marte", 30)],
    "Gemelli": [("Mercurio", 6), ("Giove", 12), ("Venere", 17), ("Marte", 24), ("Saturno", 30)],
    "Cancro": [("Marte", 7), ("Venere", 13), ("Mercurio", 19), ("Giove", 26), ("Saturno", 30)],
    "Leone": [("Giove", 6), ("Venere", 11), ("Saturno", 18), ("Mercurio", 24), ("Marte", 30)],
    "Vergine": [("Mercurio", 7), ("Venere", 17), ("Giove", 21), ("Marte", 28), ("Saturno", 30)],
    "Bilancia": [("Saturno", 6), ("Mercurio", 14), ("Giove", 21), ("Venere", 28), ("Marte", 30)],
    "Scorpione": [("Marte", 7), ("Venere", 11), ("Mercurio", 19), ("Giove", 24), ("Saturno", 30)],
    "Sagittario": [("Giove", 12), ("Venere", 17), ("Mercurio", 21), ("Saturno", 26), ("Marte", 30)],
    "Capricorno": [("Mercurio", 7), ("Giove", 14), ("Venere", 22), ("Saturno", 26), ("Marte", 30)],
    "Acquario": [("Mercurio", 7), ("Venere", 13), ("Giove", 20), ("Marte", 25), ("Saturno", 30)],
    "Pesci": [("Venere", 12), ("Giove", 16), ("Mercurio", 19), ("Marte", 28), ("Saturno", 30)],
}

# Facce (decani) in ordine caldeo: segno -> 3 pianeti da 0-10, 10-20, 20-30.
FACES = {
    "Ariete": ("Marte", "Sole", "Venere"),
    "Toro": ("Mercurio", "Luna", "Saturno"),
    "Gemelli": ("Giove", "Marte", "Sole"),
    "Cancro": ("Venere", "Mercurio", "Luna"),
    "Leone": ("Saturno", "Giove", "Marte"),
    "Vergine": ("Sole", "Venere", "Mercurio"),
    "Bilancia": ("Luna", "Saturno", "Giove"),
    "Scorpione": ("Marte", "Sole", "Venere"),
    "Sagittario": ("Mercurio", "Luna", "Saturno"),
    "Capricorno": ("Giove", "Marte", "Sole"),
    "Acquario": ("Venere", "Mercurio", "Luna"),
    "Pesci": ("Saturno", "Giove", "Marte"),
}

ANGULAR = {1, 4, 7, 10}
SUCCEDENT = {2, 5, 8, 11}
CADENT_WORST = {6, 12}

# Soglie relazione col Sole, in gradi.
CAZIMI_ORB = 17.0 / 60.0
COMBUST_ORB = 8.5
UNDER_BEAMS_ORB = 17.0


def sign_of(longitude: float) -> str:
    """Segno zodiacale che contiene la longitudine eclittica data."""
    return SIGNS[int(longitude % 360.0 // 30)]


def degree_in_sign(longitude: float) -> float:
    """Grado 0-30 all'interno del proprio segno."""
    return longitude % 30.0


def opposite_sign(sign: str) -> str:
    return SIGNS[(SIGNS.index(sign) + 6) % 12]


def _detriment_of(sign: str) -> str:
    """Pianeta in esilio nel segno: il signore del segno opposto."""
    return DOMICILE[opposite_sign(sign)]


def _fall_of(sign: str) -> str | None:
    """Pianeta in caduta nel segno: quello esaltato nel segno opposto."""
    return EXALTATION.get(opposite_sign(sign))


def term_ruler(longitude: float) -> str:
    sign = sign_of(longitude)
    deg = degree_in_sign(longitude)
    for planet, end in TERMS[sign]:
        if deg < end:
            return planet
    return TERMS[sign][-1][0]


def face_ruler(longitude: float) -> str:
    sign = sign_of(longitude)
    return FACES[sign][min(int(degree_in_sign(longitude) // 10), 2)]


def triplicity_ruler(longitude: float, is_day: bool) -> str:
    day_r, night_r, _ = TRIPLICITY[ELEMENT_OF_SIGN[sign_of(longitude)]]
    return day_r if is_day else night_r


@dataclass(frozen=True)
class EssentialDignity:
    """Scomposizione del punteggio essenziale di un pianeta."""

    score: int
    labels: tuple[str, ...]

    @property
    def is_peregrine(self) -> bool:
        return self.score == 0


def essential_dignity(planet: str, longitude: float, is_day: bool) -> EssentialDignity:
    """Punteggio essenziale secondo la tabella Albano (domicilio +5 ... faccia +1)."""
    sign = sign_of(longitude)
    score = 0
    labels: list[str] = []

    if DOMICILE[sign] == planet:
        score += 5
        labels.append("domicilio +5")
    if EXALTATION.get(sign) == planet:
        score += 4
        labels.append("esaltazione +4")
    if triplicity_ruler(longitude, is_day) == planet:
        score += 3
        labels.append("triplicita' +3")
    if term_ruler(longitude) == planet:
        score += 2
        labels.append("termine +2")
    if face_ruler(longitude) == planet:
        score += 1
        labels.append("faccia +1")

    if _detriment_of(sign) == planet:
        score -= 5
        labels.append("esilio -5")
    if _fall_of(sign) == planet:
        score -= 4
        labels.append("caduta -4")

    if not labels:
        labels.append("peregrino 0")
    return EssentialDignity(score=score, labels=tuple(labels))


def angular_score(house: int) -> tuple[int, str]:
    """Punteggio accidentale per posizione in casa."""
    if house in ANGULAR:
        return 4, f"angolare (casa {house}) +4"
    if house in SUCCEDENT:
        return 2, f"succedente (casa {house}) +2"
    if house in CADENT_WORST:
        return -4, f"cadente sfavorevole (casa {house}) -4"
    return -2, f"cadente (casa {house}) -2"


def solar_condition(planet: str, longitude: float, sun_longitude: float) -> tuple[int, str]:
    """Cazimi / combustione / sotto i raggi. Il Sole non e' valutato su se stesso."""
    if planet == "Sole":
        return 0, "n/a (e' il Sole)"
    sep = abs((longitude - sun_longitude + 180.0) % 360.0 - 180.0)
    if sep <= CAZIMI_ORB:
        return 5, "cazimi +5"
    if sep <= COMBUST_ORB:
        return -5, "combusto -5"
    if sep <= UNDER_BEAMS_ORB:
        return -3, "sotto i raggi -3"
    return 0, "libero dai raggi"


# Velocita' media giornaliera in gradi, per distinguere moto veloce da lento.
MEAN_SPEED = {
    "Sole": 0.9856, "Luna": 13.176, "Mercurio": 1.383, "Venere": 1.2,
    "Marte": 0.524, "Giove": 0.083, "Saturno": 0.034,
}

# Sotto questa velocita' assoluta un pianeta e' considerato stazionario.
STATION_THRESHOLD = {
    "Mercurio": 0.15, "Venere": 0.10, "Marte": 0.05,
    "Giove": 0.02, "Saturno": 0.01,
}


def motion_condition(planet: str, speed: float, speed_tomorrow: float) -> tuple[int, str]:
    """Moto: stazioni, velocita', lentezza.

    Le stazioni sono distinte usando il segno della velocita' di domani: se il
    pianeta e' quasi fermo e sta passando da diretto a retrogrado siamo alla
    prima stazione (-4), nel caso opposto alla seconda (+4).
    """
    if planet in ("Sole", "Luna"):
        return (2, "veloce +2") if abs(speed) > MEAN_SPEED[planet] else (-2, "lento -2")

    threshold = STATION_THRESHOLD[planet]
    if abs(speed) < threshold:
        if speed_tomorrow < speed:
            return -4, "prima stazione (verso retrogrado) -4"
        return 4, "seconda stazione (verso diretto) +4"

    if speed < 0:
        return -2, "retrogrado -2"
    return (2, "veloce +2") if abs(speed) > MEAN_SPEED[planet] else (-2, "lento -2")
