CREATE TABLE IF NOT EXISTS market (
    market_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id      INTEGER,
    question        TEXT,
    outcome_a       TEXT,
    outcome_b       TEXT,
    reserve_a       REAL,
    reserve_b       REAL,
    resolved        INTEGER DEFAULT 0,
    winning_outcome TEXT,
    created_at      TEXT
);
