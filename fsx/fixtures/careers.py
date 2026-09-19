"""Hand-entered careers for validating the engine before any API key exists.

IMPORTANT: every figure here is an approximation typed by hand - rounded budgets
and grosses, remembered review scores, a representative rather than exhaustive
award list, and a block of "filler" credits standing in for the long tail of a
filmography. It is good enough to answer the Phase 0 question, which is whether
the engine ORDERS people sensibly and lands each tier in the right price band.
It is not good enough to publish a price. Run the real backfill once TMDB and
OMDb keys are in place; these fixtures exist so the engine can be judged today.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from ..models import Award, Credit, Person

# Ceremony dates are approximated to a fixed day in the year after release.
OSCAR_DAY = (3, 10)
GLOBE_DAY = (1, 10)


@dataclass
class H:
    """One headline credit. Money in millions of dollars."""
    title: str
    year: int
    tier: str
    rt: Optional[float]
    meta: Optional[float]
    imdb: Optional[float]
    votes: Optional[int]
    budget_m: Optional[float]
    gross_m: Optional[float]
    voice: bool = False


@dataclass
class Filler:
    """The long tail of a filmography, as a block."""
    count: int
    tier: str
    from_year: int
    to_year: int
    rt: float = 62
    meta: float = 57
    imdb: float = 6.5
    votes: int = 40_000
    budget_m: float = 30
    gross_m: float = 90


def _credit(h: H, is_director: bool = False) -> Credit:
    return Credit(
        title=h.title,
        release_date=date(h.year, 7, 1),
        is_director=is_director,
        role_weight_override=None if is_director else None,
        rt_critics=h.rt,
        metascore=h.meta,
        imdb=h.imdb,
        imdb_votes=h.votes,
        budget=(h.budget_m or 0) * 1e6 or None,
        worldwide_gross=(h.gross_m or 0) * 1e6 or None,
        is_voice=h.voice,
    )


def build(name: str, headline: list[H], awards: list[tuple] = (),
          filler: Filler | None = None, is_director: bool = False,
          next_release: Optional[date] = None) -> Person:
    person = Person(name=name, is_director=is_director, next_release=next_release)

    for h in headline:
        credit = _credit(h, is_director)
        # Fixtures name the role tier directly rather than guessing from billing.
        if not is_director:
            from ..constants import ROLE_WEIGHTS
            credit.role_weight_override = ROLE_WEIGHTS[h.tier]
        person.credits.append(credit)

    if filler and filler.count > 0:
        from ..constants import ROLE_WEIGHTS
        span = max(1, filler.to_year - filler.from_year)
        for i in range(filler.count):
            year = filler.from_year + round(i * span / max(filler.count - 1, 1))
            credit = Credit(
                placeholder=True,
                title=f"{name} filler {i + 1}",
                release_date=date(int(year), 7, 1),
                is_director=is_director,
                rt_critics=filler.rt, metascore=filler.meta,
                imdb=filler.imdb, imdb_votes=filler.votes,
                budget=filler.budget_m * 1e6, worldwide_gross=filler.gross_m * 1e6,
            )
            if not is_director:
                credit.role_weight_override = ROLE_WEIGHTS[filler.tier]
            person.credits.append(credit)

    for key, year, won in awards:
        month, day = OSCAR_DAY if key.startswith("oscar") else GLOBE_DAY
        person.awards.append(
            Award(key=key, year=year, awarded_on=date(year + 1, month, day), won=won))

    return person


def noms(key: str, years: list[int]) -> list[tuple]:
    return [(key, y, False) for y in years]


# ---------------------------------------------------------------- the roster
def roster() -> list[Person]:
    people: list[Person] = []
    add = people.append

    add(build("Meryl Streep", [
        H("Kramer vs. Kramer", 1979, "supporting", 89, 77, 7.8, 170_000, 8, 106),
        H("Sophie's Choice", 1982, "sole_lead", 88, 68, 7.5, 60_000, 12, 30),
        H("The Devil Wears Prada", 2006, "co_lead", 75, 62, 6.9, 470_000, 35, 327),
        H("Mamma Mia!", 2008, "co_lead", 54, 51, 6.5, 250_000, 52, 611),
        H("The Iron Lady", 2011, "sole_lead", 52, 54, 6.4, 110_000, 13, 115),
        H("Little Women", 2019, "supporting", 95, 91, 7.8, 250_000, 40, 218),
    ], awards=[
        ("oscar_supporting", 1979, True), ("oscar_lead", 1982, True),
        ("oscar_lead", 2011, True),
        *noms("oscar_lead", [1981, 1983, 1985, 1987, 1988, 1990, 1995, 1998,
                             1999, 2002, 2006, 2008, 2009, 2013, 2016, 2017]),
        *noms("oscar_supporting", [2002, 2014]),
        *noms("globe", [1979, 1982, 2006, 2008, 2011, 2019]),
    ], filler=Filler(42, "co_lead", 1980, 2024)))

    add(build("Tom Cruise", [
        H("Top Gun", 1986, "sole_lead", 58, 50, 6.9, 430_000, 15, 357),
        H("Rain Man", 1988, "co_lead", 89, 65, 8.0, 530_000, 25, 354),
        H("Jerry Maguire", 1996, "sole_lead", 84, 77, 7.3, 300_000, 50, 274),
        H("Magnolia", 1999, "ensemble_lead", 83, 77, 8.0, 340_000, 37, 48),
        H("Mission: Impossible - Fallout", 2018, "sole_lead", 98, 86, 7.7, 400_000, 178, 792),
        H("Top Gun: Maverick", 2022, "sole_lead", 96, 78, 8.2, 700_000, 170, 1496),
    ], awards=[
        *noms("oscar_lead", [1989, 1996]), *noms("oscar_supporting", [1999]),
        ("globe", 1989, True), ("globe", 1996, True), ("globe", 1999, True),
    ], filler=Filler(34, "sole_lead", 1983, 2024, rt=66, meta=60, imdb=6.8,
                     votes=200_000, budget_m=90, gross_m=310)))

    add(build("Denzel Washington", [
        H("Glory", 1989, "supporting", 93, 78, 7.8, 140_000, 18, 27),
        H("Malcolm X", 1992, "sole_lead", 88, 73, 7.7, 100_000, 34, 73),
        H("Training Day", 2001, "co_lead", 73, 68, 7.7, 430_000, 45, 105),
        H("American Gangster", 2007, "co_lead", 80, 76, 7.8, 460_000, 100, 266),
        H("The Equalizer", 2014, "sole_lead", 61, 57, 7.2, 400_000, 55, 192),
        H("Fences", 2016, "sole_lead", 92, 79, 7.2, 110_000, 24, 64),
    ], awards=[
        ("oscar_supporting", 1989, True), ("oscar_lead", 2001, True),
        *noms("oscar_lead", [1992, 1999, 2012, 2016, 2017, 2021]),
        *noms("oscar_supporting", [1987]),
        *noms("globe", [1989, 1992, 2001, 2016]),
    ], filler=Filler(36, "sole_lead", 1990, 2024, rt=68, meta=61, imdb=7.0,
                     votes=150_000, budget_m=55, gross_m=160)))

    add(build("Leonardo DiCaprio", [
        H("Titanic", 1997, "co_lead", 88, 75, 7.9, 1_200_000, 200, 2200),
        H("The Departed", 2006, "co_lead", 90, 85, 8.5, 1_400_000, 90, 291),
        H("Inception", 2010, "sole_lead", 87, 74, 8.8, 2_500_000, 160, 837),
        H("The Wolf of Wall Street", 2013, "sole_lead", 80, 75, 8.2, 1_500_000, 100, 392),
        H("The Revenant", 2015, "sole_lead", 78, 76, 8.0, 830_000, 135, 533),
        H("Once Upon a Time in Hollywood", 2019, "co_lead", 85, 83, 7.6, 800_000, 90, 377),
    ], awards=[
        ("oscar_lead", 2015, True),
        *noms("oscar_lead", [1993, 2004, 2006, 2013, 2019, 2023]),
        *noms("oscar_supporting", [1993]),
        *noms("globe", [2004, 2006, 2013, 2015, 2019]),
    ], filler=Filler(24, "sole_lead", 1995, 2024, rt=76, meta=70, imdb=7.4,
                     votes=400_000, budget_m=70, gross_m=220)))

    add(build("Cate Blanchett", [
        H("Elizabeth", 1998, "sole_lead", 82, 75, 7.4, 90_000, 30, 82),
        H("The Aviator", 2004, "supporting", 86, 77, 7.5, 350_000, 110, 214),
        H("Blue Jasmine", 2013, "sole_lead", 91, 78, 7.2, 200_000, 18, 99),
        H("Carol", 2015, "co_lead", 94, 95, 7.2, 130_000, 12, 40),
        H("Thor: Ragnarok", 2017, "supporting", 93, 74, 7.9, 800_000, 180, 854),
        H("Tar", 2022, "sole_lead", 91, 92, 7.4, 100_000, 35, 29),
    ], awards=[
        ("oscar_supporting", 2004, True), ("oscar_lead", 2013, True),
        *noms("oscar_lead", [1998, 2007, 2015, 2022]),
        *noms("oscar_supporting", [2006, 2007]),
        *noms("globe", [1998, 2004, 2013, 2015, 2022]),
    ], filler=Filler(46, "co_lead", 1999, 2024, rt=70, meta=66, imdb=6.9,
                     votes=90_000, budget_m=35, gross_m=95)))

    add(build("Christopher Nolan", [
        H("Memento", 2000, "sole_lead", 94, 83, 8.4, 1_300_000, 9, 40),
        H("The Dark Knight", 2008, "sole_lead", 94, 84, 9.0, 2_900_000, 185, 1006),
        H("Inception", 2010, "sole_lead", 87, 74, 8.8, 2_500_000, 160, 837),
        H("Interstellar", 2014, "sole_lead", 73, 74, 8.7, 2_100_000, 165, 731),
        H("Dunkirk", 2017, "sole_lead", 92, 94, 7.8, 720_000, 100, 527),
        H("Oppenheimer", 2023, "sole_lead", 93, 90, 8.3, 850_000, 100, 976),
    ], awards=[
        ("oscar_directing", 2023, True), ("oscar_picture", 2023, True),
        *noms("oscar_directing", [2017]), *noms("oscar_picture", [2010, 2017]),
        ("globe", 2023, True), *noms("globe", [2010, 2017]),
    ], filler=Filler(6, "sole_lead", 1998, 2020, rt=85, meta=78, imdb=7.9,
                     votes=700_000, budget_m=70, gross_m=280), is_director=True))

    add(build("Steven Spielberg", [
        H("Jaws", 1975, "sole_lead", 97, 87, 8.1, 650_000, 9, 477),
        H("E.T. the Extra-Terrestrial", 1982, "sole_lead", 99, 94, 7.9, 430_000, 10.5, 792),
        H("Jurassic Park", 1993, "sole_lead", 91, 68, 8.2, 1_100_000, 63, 1100),
        H("Schindler's List", 1993, "sole_lead", 98, 95, 9.0, 1_500_000, 22, 322),
        H("Saving Private Ryan", 1998, "sole_lead", 94, 91, 8.6, 1_500_000, 70, 482),
        H("Lincoln", 2012, "sole_lead", 89, 86, 7.3, 280_000, 65, 275),
    ], awards=[
        ("oscar_directing", 1993, True), ("oscar_picture", 1993, True),
        ("oscar_directing", 1998, True),
        *noms("oscar_directing", [1977, 1981, 1982, 2005, 2012, 2021]),
        *noms("oscar_picture", [1981, 1985, 1998, 2005, 2012, 2017, 2021]),
        *noms("globe", [1982, 1993, 1998, 2012, 2021]),
    ], filler=Filler(26, "sole_lead", 1974, 2023, rt=80, meta=72, imdb=7.2,
                     votes=250_000, budget_m=70, gross_m=240), is_director=True))

    add(build("Margot Robbie", [
        H("The Wolf of Wall Street", 2013, "supporting", 80, 75, 8.2, 1_500_000, 100, 392),
        H("I, Tonya", 2017, "sole_lead", 90, 77, 7.5, 330_000, 11, 54),
        H("Once Upon a Time in Hollywood", 2019, "supporting", 85, 83, 7.6, 800_000, 90, 377),
        H("Bombshell", 2019, "supporting", 68, 64, 6.8, 100_000, 32, 61),
        H("Birds of Prey", 2020, "sole_lead", 79, 60, 6.0, 300_000, 85, 205),
        H("Barbie", 2023, "sole_lead", 88, 80, 6.8, 600_000, 145, 1446),
    ], awards=[
        *noms("oscar_lead", [2017]), *noms("oscar_supporting", [2019]),
        *noms("globe", [2017, 2019, 2023]),
    ], filler=Filler(18, "co_lead", 2013, 2024, rt=63, meta=57, imdb=6.4,
                     votes=120_000, budget_m=45, gross_m=120)))

    add(build("Timothee Chalamet", [
        H("Call Me by Your Name", 2017, "sole_lead", 94, 93, 7.8, 300_000, 3.5, 42),
        H("Lady Bird", 2017, "supporting", 99, 94, 7.4, 300_000, 10, 79),
        H("Little Women", 2019, "co_lead", 95, 91, 7.8, 250_000, 40, 218),
        H("Dune", 2021, "sole_lead", 83, 74, 8.0, 830_000, 165, 434),
        H("Wonka", 2023, "sole_lead", 82, 66, 7.0, 200_000, 125, 634),
        H("Dune: Part Two", 2024, "sole_lead", 92, 79, 8.5, 600_000, 190, 715),
    ], awards=[
        *noms("oscar_lead", [2017]), *noms("globe", [2017, 2023]),
    ], filler=Filler(12, "co_lead", 2016, 2024, rt=68, meta=64, imdb=6.7,
                     votes=80_000, budget_m=25, gross_m=60)))

    add(build("Florence Pugh", [
        H("Lady Macbeth", 2016, "sole_lead", 89, 83, 6.8, 30_000, 0.5, 5),
        H("Midsommar", 2019, "sole_lead", 83, 72, 7.1, 400_000, 9, 48),
        H("Little Women", 2019, "ensemble_lead", 95, 91, 7.8, 250_000, 40, 218),
        H("Black Widow", 2021, "co_lead", 79, 67, 6.7, 400_000, 200, 379),
        H("Don't Worry Darling", 2022, "sole_lead", 38, 48, 6.2, 160_000, 35, 87),
        H("Oppenheimer", 2023, "supporting", 93, 90, 8.3, 850_000, 100, 976),
    ], awards=[
        *noms("oscar_supporting", [2019]), *noms("globe", [2019]),
    ], filler=Filler(10, "co_lead", 2016, 2024, rt=70, meta=64, imdb=6.6,
                     votes=70_000, budget_m=25, gross_m=55)))

    add(build("Michelle Yeoh", [
        H("Crouching Tiger, Hidden Dragon", 2000, "co_lead", 98, 94, 7.9, 260_000, 17, 214),
        H("Memoirs of a Geisha", 2005, "supporting", 35, 54, 7.3, 130_000, 85, 162),
        H("Crazy Rich Asians", 2018, "supporting", 91, 74, 6.9, 200_000, 30, 239),
        H("Shang-Chi", 2021, "supporting", 91, 71, 7.4, 400_000, 150, 432),
        H("Everything Everywhere All at Once", 2022, "sole_lead", 93, 81, 7.8, 600_000, 25, 143),
        H("Wicked", 2024, "supporting", 88, 73, 7.3, 200_000, 150, 750),
    ], awards=[
        ("oscar_lead", 2022, True), ("globe", 2022, True),
        ("sag_individual", 2022, True),
    ], filler=Filler(38, "co_lead", 1985, 2024, rt=62, meta=56, imdb=6.4,
                     votes=25_000, budget_m=20, gross_m=48)))

    add(build("Ke Huy Quan", [
        H("Indiana Jones and the Temple of Doom", 1984, "supporting", 77, 57, 7.5, 500_000, 28, 333),
        H("The Goonies", 1985, "ensemble_lead", 76, 62, 7.7, 280_000, 19, 61),
        H("Everything Everywhere All at Once", 2022, "supporting", 93, 81, 7.8, 600_000, 25, 143),
    ], awards=[
        ("oscar_supporting", 2022, True), ("globe", 2022, True),
        ("sag_individual", 2022, True),
    ]))

    add(build("Paul Giamatti", [
        H("Private Parts", 1997, "supporting", 78, 70, 6.8, 40_000, 28, 41),
        H("American Splendor", 2003, "sole_lead", 94, 90, 7.4, 40_000, 2, 8),
        H("Sideways", 2004, "co_lead", 97, 94, 7.5, 190_000, 16, 110),
        H("Cinderella Man", 2005, "supporting", 80, 69, 8.0, 180_000, 88, 108),
        H("San Andreas", 2015, "supporting", 49, 43, 6.1, 240_000, 110, 474),
        H("The Holdovers", 2023, "sole_lead", 97, 82, 7.9, 130_000, 30, 41),
    ], awards=[
        *noms("oscar_supporting", [2005]), *noms("oscar_lead", [2023]),
        ("globe", 2023, True), *noms("globe", [2005]),
    ], filler=Filler(60, "supporting", 1997, 2024, rt=64, meta=58, imdb=6.6,
                     votes=45_000, budget_m=25, gross_m=65)))

    add(build("Stephen Root", [
        H("Office Space", 1999, "supporting", 80, 68, 7.6, 280_000, 10, 12),
        H("O Brother, Where Art Thou?", 2000, "minor", 79, 69, 7.7, 320_000, 26, 72),
        H("No Country for Old Men", 2007, "minor", 93, 92, 8.2, 1_000_000, 25, 171),
        H("Get Out", 2017, "minor", 98, 85, 7.8, 700_000, 4.5, 255),
        H("Dolemite Is My Name", 2019, "supporting", 97, 76, 7.3, 50_000, 40, 1),
    ], filler=Filler(70, "minor", 1992, 2024, rt=63, meta=57, imdb=6.5,
                     votes=50_000, budget_m=30, gross_m=85)))

    add(build("John Carroll Lynch", [
        H("Fargo", 1996, "supporting", 94, 85, 8.1, 700_000, 7, 60),
        H("Zodiac", 2007, "supporting", 90, 79, 7.7, 500_000, 65, 85),
        H("Shutter Island", 2010, "minor", 69, 63, 8.2, 1_300_000, 80, 294),
        H("The Founder", 2016, "supporting", 81, 66, 7.2, 130_000, 25, 24),
        H("Jackie", 2016, "minor", 88, 81, 6.8, 60_000, 9, 30),
    ], filler=Filler(58, "minor", 1996, 2024, rt=61, meta=55, imdb=6.4,
                     votes=40_000, budget_m=28, gross_m=70)))

    add(build("Barry Keoghan", [
        H("Dunkirk", 2017, "supporting", 92, 94, 7.8, 720_000, 100, 527),
        H("The Killing of a Sacred Deer", 2017, "co_lead", 80, 73, 7.0, 130_000, 5, 7),
        H("The Green Knight", 2021, "minor", 87, 85, 6.6, 130_000, 15, 18),
        H("The Batman", 2022, "cameo", 85, 72, 7.8, 800_000, 185, 772),
        H("The Banshees of Inisherin", 2022, "supporting", 96, 87, 7.7, 250_000, 20, 51),
        H("Saltburn", 2023, "sole_lead", 71, 61, 7.0, 250_000, 25, 20),
    ], awards=[
        *noms("oscar_supporting", [2022]), ("bafta", 2022, True),
        *noms("globe", [2022]),
    ], filler=Filler(14, "supporting", 2014, 2024, rt=66, meta=62, imdb=6.5,
                     votes=45_000, budget_m=15, gross_m=32)))

    add(build("Ana de Armas", [
        H("Blade Runner 2049", 2017, "supporting", 88, 81, 8.1, 700_000, 150, 267),
        H("Knives Out", 2019, "co_lead", 97, 82, 7.9, 700_000, 40, 313),
        H("No Time to Die", 2021, "minor", 83, 68, 7.3, 450_000, 250, 774),
        H("Blonde", 2022, "sole_lead", 42, 49, 5.5, 80_000, 22, 1),
        H("Ghosted", 2023, "co_lead", 28, 36, 5.7, 90_000, 75, 1),
    ], awards=[
        *noms("oscar_lead", [2022]), *noms("globe", [2019, 2022]),
    ], filler=Filler(20, "supporting", 2010, 2024, rt=58, meta=52, imdb=6.2,
                     votes=40_000, budget_m=25, gross_m=55)))

    add(build("Greta Gerwig", [
        H("Lady Bird", 2017, "sole_lead", 99, 94, 7.4, 300_000, 10, 79),
        H("Little Women", 2019, "sole_lead", 95, 91, 7.8, 250_000, 40, 218),
        H("Barbie", 2023, "sole_lead", 88, 80, 6.8, 600_000, 145, 1446),
    ], awards=[
        *noms("oscar_directing", [2017]), *noms("oscar_picture", [2017, 2019, 2023]),
        *noms("globe", [2017, 2023]),
    ], is_director=True))

    add(build("Jordan Peele", [
        H("Get Out", 2017, "sole_lead", 98, 85, 7.8, 700_000, 4.5, 255),
        H("Us", 2019, "sole_lead", 93, 81, 6.8, 300_000, 20, 256),
        H("Nope", 2022, "sole_lead", 82, 77, 6.8, 250_000, 68, 172),
    ], awards=[
        *noms("oscar_directing", [2017]), *noms("oscar_picture", [2017]),
        *noms("globe", [2017]),
    ], is_director=True))

    add(build("Brian Tyree Henry", [
        H("If Beale Street Could Talk", 2018, "minor", 95, 87, 7.1, 40_000, 12, 20),
        H("Joker", 2019, "minor", 68, 59, 8.3, 1_500_000, 55, 1074),
        H("Eternals", 2021, "supporting", 47, 52, 6.3, 400_000, 200, 402),
        H("Bullet Train", 2022, "supporting", 54, 49, 7.3, 400_000, 90, 239),
        H("Causeway", 2022, "co_lead", 88, 70, 6.3, 20_000, 10, 0.5),
    ], awards=[
        *noms("oscar_supporting", [2022]),
    ], filler=Filler(16, "supporting", 2015, 2024, rt=67, meta=60, imdb=6.6,
                     votes=60_000, budget_m=35, gross_m=95)))

    add(build("Margaret Qualley", [
        H("Once Upon a Time in Hollywood", 2019, "minor", 85, 83, 7.6, 800_000, 90, 377),
        H("Poor Things", 2023, "minor", 92, 87, 7.7, 300_000, 35, 117),
        H("Drive-Away Dolls", 2024, "co_lead", 66, 60, 5.5, 20_000, 20, 7),
        H("The Substance", 2024, "co_lead", 90, 78, 7.3, 250_000, 17, 77),
    ], filler=Filler(12, "supporting", 2015, 2024, rt=68, meta=62, imdb=6.5,
                     votes=35_000, budget_m=18, gross_m=40)))

    add(build("Stephanie Hsu", [
        H("Everything Everywhere All at Once", 2022, "supporting", 93, 81, 7.8, 600_000, 25, 143),
        H("Joy Ride", 2023, "ensemble_lead", 91, 74, 6.7, 30_000, 20, 15),
    ], awards=[
        *noms("oscar_supporting", [2022]),
    ], filler=Filler(6, "minor", 2018, 2024, rt=70, meta=63, imdb=6.6,
                     votes=25_000, budget_m=15, gross_m=30)))

    add(build("Mikey Madison", [
        H("Once Upon a Time in Hollywood", 2019, "minor", 85, 83, 7.6, 800_000, 90, 377),
        H("Scream", 2022, "supporting", 76, 61, 6.3, 200_000, 24, 140),
        H("Anora", 2024, "sole_lead", 98, 91, 7.5, 100_000, 6, 56),
    ], awards=[
        ("oscar_lead", 2024, True), ("bafta", 2024, True),
    ]))

    add(build("Dominic Sessa", [
        H("The Holdovers", 2023, "co_lead", 97, 82, 7.9, 130_000, 30, 41),
    ]))

    add(build("Sophie Wilde", [
        H("Talk to Me", 2023, "sole_lead", 94, 76, 7.1, 130_000, 4.5, 92),
    ]))

    return people
