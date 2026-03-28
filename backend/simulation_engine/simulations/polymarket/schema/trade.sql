CREATE TABLE IF NOT EXISTS trade (
    trade_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    market_id   INTEGER,
    side        TEXT,
    outcome     TEXT,
    shares      REAL,
    price       REAL,
    cost        REAL,
    created_at  TEXT
);
