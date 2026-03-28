CREATE TABLE IF NOT EXISTS position (
    position_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    market_id   INTEGER,
    outcome     TEXT,
    shares      REAL DEFAULT 0
);
