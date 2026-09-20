-- Film Stock Exchange, Phase 2.
-- Money-like state, so: exact integers, explicit constraints, and every
-- mutation inside a transaction. Credits and prices are stored as INTEGER
-- CENTIDOLLARS (1 CR = 100). Floats lose pennies, and the leaderboard is
-- decided by pennies.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY,
  provider      TEXT    NOT NULL,
  provider_id   TEXT    NOT NULL,
  display_name  TEXT    NOT NULL,
  avatar_url    TEXT,
  credits       INTEGER NOT NULL,
  slots         INTEGER NOT NULL DEFAULT 10,
  created_at    TEXT    NOT NULL,
  season_base   INTEGER,
  season_id     TEXT,
  UNIQUE (provider, provider_id)
);

CREATE TABLE IF NOT EXISTS positions (
  id            INTEGER PRIMARY KEY,
  user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  slug          TEXT    NOT NULL,
  shares        INTEGER NOT NULL CHECK (shares > 0),
  entry_price   INTEGER NOT NULL,
  held_value    INTEGER NOT NULL,
  opened_on     TEXT    NOT NULL,
  last_buy_on   TEXT    NOT NULL,
  UNIQUE (user_id, slug)
);

CREATE TABLE IF NOT EXISTS trades (
  id            INTEGER PRIMARY KEY,
  user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  slug          TEXT    NOT NULL,
  side          TEXT    NOT NULL CHECK (side IN ('buy', 'sell')),
  shares        INTEGER NOT NULL CHECK (shares > 0),
  price         INTEGER NOT NULL,
  fee           INTEGER NOT NULL,
  cash_delta    INTEGER NOT NULL,
  at            TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS trades_user ON trades(user_id, at DESC);

CREATE TABLE IF NOT EXISTS prices (
  slug          TEXT    NOT NULL,
  on_date       TEXT    NOT NULL,
  price         INTEGER NOT NULL,
  cp            REAL    NOT NULL,
  tier          TEXT    NOT NULL,
  PRIMARY KEY (slug, on_date)
);
CREATE INDEX IF NOT EXISTS prices_date ON prices(on_date);

CREATE TABLE IF NOT EXISTS stocks (
  slug          TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  is_director   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS marks (
  on_date       TEXT PRIMARY KEY,
  positions     INTEGER NOT NULL,
  ran_at        TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger (
  id            INTEGER PRIMARY KEY,
  user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind          TEXT    NOT NULL,
  amount        INTEGER NOT NULL,
  note          TEXT    NOT NULL DEFAULT '',
  at            TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ledger_user ON ledger(user_id, at DESC);

CREATE TABLE IF NOT EXISTS dividends (
  quarter       TEXT    NOT NULL,
  user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  amount        INTEGER NOT NULL,
  PRIMARY KEY (quarter, user_id)
);

-- Phase 3: the daily games.
-- One row per player per game per day. The UNIQUE constraint is the whole
-- anti-replay mechanism: a day's puzzle pays exactly once.
CREATE TABLE IF NOT EXISTS plays (
  id            INTEGER PRIMARY KEY,
  user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  game          TEXT    NOT NULL,
  on_date       TEXT    NOT NULL,
  state         TEXT    NOT NULL DEFAULT '{}',   -- JSON: progress so far
  fraction      REAL    NOT NULL DEFAULT 0,
  payout        INTEGER NOT NULL DEFAULT 0,
  done          INTEGER NOT NULL DEFAULT 0,
  -- Set the first time a day's game pays out. A replay clears `done` so it can
  -- be played again, and leaves this alone, so the second run pays nothing.
  paid          INTEGER NOT NULL DEFAULT 0,
  at            TEXT    NOT NULL,
  UNIQUE (user_id, game, on_date)
);
CREATE INDEX IF NOT EXISTS plays_board ON plays(on_date, game);

-- Solve rates, so an unfair puzzle can be spotted and the generator tuned.
CREATE TABLE IF NOT EXISTS puzzle_stats (
  game          TEXT    NOT NULL,
  on_date       TEXT    NOT NULL,
  attempts      INTEGER NOT NULL DEFAULT 0,
  solves        INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (game, on_date)
);
