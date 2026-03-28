CREATE TABLE IF NOT EXISTS quote_post (
    quote_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    post_id INTEGER,
    content TEXT,
    created_at TEXT
);
