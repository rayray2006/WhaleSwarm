CREATE TABLE IF NOT EXISTS poly_comment (
    comment_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id   INTEGER,
    creator_id  INTEGER,
    content     TEXT,
    created_at  TEXT
);
