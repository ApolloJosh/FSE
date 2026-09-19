"""Every tunable constant in the Film Stock Exchange price engine.

Values are fitted, not guessed: see tests/test_reference_careers.py, which pins
six simulated careers to the prices in the design doc. Change a number here and
those tests tell you what it cost you.
"""

# ---------------------------------------------------------------- price curve
PRICE_FLOOR = 2.50          # CR; no listed stock goes below this
PRICE_COEF = 0.05
PRICE_EXP = 0.88            # compression: the reason a nom moves a newcomer 171%

# ------------------------------------------------------------- CP components
# Refitted 2026-09-19 against the real 256-person roster. The original values
# were fitted to synthetic careers of ~35 credits; real filmographies run to
# ~58, which made "has a lot of credits" 58% of all value in the market and
# ranked Kieran Culkin above Tom Cruise. Working points down 160 -> 90, box
# office ladder x3 (only 45% of credits carry budget data, so it was 7% of
# value and could not see a box-office star at all).
WORKING_POINTS = 90.0       # CP per scored credit at role weight 1.0
RECEPTION_COEF = 5.0        # CP per point of (RS - 50) at role weight 1.0
DIRECTOR_SCALE = 0.75       # directors take full weight, so scale box+reception

# ---------------------------------------------------------------- role weight
ROLE_WEIGHTS = {
    "sole_lead": 1.00,
    "co_lead": 0.80,
    "ensemble_lead": 0.60,
    "major_supporting": 0.45,
    "supporting": 0.30,
    "minor": 0.15,
    "cameo": 0.08,
    "uncredited": 0.00,
}
VOICE_MULTIPLIER = 0.85
ENSEMBLE_WEIGHT_CAP = 3.0   # total scored role weight allowed per film

# Absolute billed position -> role tier, as the role table describes it:
# "billed 1st or 2nd", "billed 3rd-6th", "billed 7th-12th", "billed 13th-25th".
# (highest position in the band, tier)
BILLING_BANDS = [
    (1, "sole_lead"),
    (2, "co_lead"),
    (6, "major_supporting"),
    (12, "supporting"),
    (25, "minor"),
    (10**6, "cameo"),
]
# Cast-size normalization: being 8th billed out of 60 is more selective than
# 8th out of 12, so a part high up a deep cast list is promoted one step.
DEEP_CAST_SIZE = 30
DEEP_CAST_FRACTION = 0.15
CAMEO_RUNTIME_SHARE = 0.08   # under this share of runtime -> caps at cameo
MAJOR_RUNTIME_SHARE = 0.35   # over this share -> floors at major_supporting

# Television, scored at a discount against the season
TV_ROLE_WEIGHTS = {"regular": 0.50, "recurring": 0.20, "guest": 0.05}

# ------------------------------------------------------------ reception score
# source -> (mu, sigma, weight). Recompute mu/sigma on the real corpus.
RECEPTION_SOURCES = {
    "rt_critics": (60.0, 27.0, 0.20),
    "metascore": (56.0, 17.0, 0.20),
    "rt_audience": (63.0, 19.0, 0.20),
    "imdb": (6.3, 1.0, 0.20),
    "letterboxd": (3.15, 0.55, 0.20),
}
RECEPTION_CENTER = 50.0
RECEPTION_SPREAD = 15.0
MIN_RECEPTION_SOURCES = 3
CONFIDENCE_VOTE_EXP = 4.0    # log10(votes)/4 -> 10k votes is full confidence
RECEPTION_LOCK_DAYS = 90
RERATE_YEARS = 2
RERATE_THRESHOLD = 8.0       # RS points of drift needed to fire a re-rate

# ----------------------------------------------------------------- box office
BREAKEVEN_MULTIPLE = 2.5
# (upper bound of multiple, BOP in CP at role weight 1.0)
# Positives x3 against the original fit, negatives only x1.5. Tripling both
# made four flops fatal: Chris Hemsworth priced at CR 7.66, below 248 other
# people, because he is a small share of enormous hits (Endgame paid him +146
# through the ensemble cap) and the lead of modest failures (Crime 101 cost
# him -580). Bombs should hurt; they should not erase a career.
BOX_OFFICE_LADDER = [
    (1.0, -540.0),
    (1.7, -315.0),
    (2.5, -135.0),
    (3.5, 0.0),
    (5.0, 360.0),
    (8.0, 810.0),
    (15.0, 1350.0),
    (float("inf"), 1980.0),
]
# A film has to have been seen by somebody before its multiple means anything.
# Sean Baker's debut cost $3,000 and took $69,816 - a 23x "phenomenon" that
# paid like a blockbuster. Below this, box office scores nothing either way.
MIN_GROSS_FOR_POINTS = 5_000_000
# S ramps from $1M (0.0) to $1B (1.0) instead of starting at a 0.5 floor, so a
# film that grossed $70k no longer earns three quarters of a billion-dollar
# opening's credit.
SCALE_LOG_FLOOR = 6.0
SCALE_LOG_SPAN = 3.0
BOX_OFFICE_LOCK_DAYS = 120
# A film can only be punished at the box office if it was actually a bet.
# Awards-season platform releases routinely gross under break-even by design;
# scoring those as bombs punished exactly the prestige work the awards engine
# is meant to reward. Below both thresholds, box office points floor at zero:
# a small film can earn, but it cannot cost.
WIDE_RELEASE_BUDGET = 40_000_000
WIDE_RELEASE_GROSS = 50_000_000
STREAMING_BREAKEVEN_VIEWERS = 12_000_000   # first 28 days
STREAMING_DISCOUNT = 0.7

# --------------------------------------------------------------------- awards
# key -> (nomination CP, additional CP on a win)
AWARD_TABLE = {
    "oscar_lead": (400, 900),
    "oscar_supporting": (340, 750),
    "oscar_directing": (420, 950),
    "oscar_picture": (250, 600),
    "oscar_screenplay": (230, 520),
    "bafta": (140, 300),
    "globe": (110, 230),
    "sag_individual": (130, 280),
    "sag_ensemble": (60, 130),
    "emmy_lead": (200, 450),
    "emmy_supporting": (160, 360),
    "critics_choice": (70, 150),
    "festival_top": (180, 400),
    "european_film": (100, 220),
    "national_major": (90, 200),      # Golden Horse, Cesar, Filmfare, AFA
    "spirit_gotham": (60, 130),
    "critics_group": (0, 90),
}
CRITICS_GROUP_CAP = 270
FIRST_OSCAR_WIN_MULTIPLIER = 1.5
OSCAR_KEYS = {"oscar_lead", "oscar_supporting", "oscar_directing",
              "oscar_picture", "oscar_screenplay"}
PRECURSOR_KEYS = {"bafta", "globe", "sag_individual", "critics_choice"}
SNUB_MIN_PRECURSORS = 2
SNUB_CLAWBACK = 0.40
# Oscar nominations for films of year Y are announced in late January of Y+1.
# The clawback cannot fire before that morning - until then, nothing has
# happened yet and a heavily precursed stock is simply riding high.
OSCAR_NOMINATION_MONTH_DAY = (1, 23)

# ---------------------------------------------------------- decay and downside
# (CP threshold, tier name, annual age decay, annual idle rate)
DECAY_TIERS = [
    (120, "Debut", 0.22, 0.200),
    (700, "Working", 0.18, 0.160),
    (2400, "Recognized", 0.14, 0.120),
    (6000, "Established", 0.10, 0.090),
    (12000, "A-List", 0.07, 0.060),
    (float("inf"), "Legend", 0.04, 0.035),
]
DECAY_RETENTION = 0.40       # an event never decays below 40% of face value
GRACE_DAYS = 270             # idle decay does not start until this has passed
IN_PRODUCTION_IDLE_FACTOR = 0.5
BOMB_COMPOUND = 1.25         # same film, bad reviews AND bad box office
MAX_SINGLE_EVENT_LOSS = 0.35 # no one event removes more than 35% of current CP

# ------------------------------------------------------------------- listing
MIN_IMDB_VOTES_TO_LIST = 1000

# ------------------------------------------------------------ player economy
STARTING_BANKROLL = 50.00
TRADE_FEE = 0.015
SETTLEMENT_DAYS = 7
POSITION_CAP_PCT = 0.05
FREE_PORTFOLIO_SLOTS = 10
# (days held before the event, share of the gain realized)
CONVICTION_LADDER = [
    (7, 0.40),
    (30, 0.70),
    (90, 1.00),
    (365, 1.15),
    (float("inf"), 1.30),
]
