CREATE TABLE IF NOT EXISTS trace (
    trace_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    action      TEXT,
    info        TEXT,
    created_at  TEXT
);
