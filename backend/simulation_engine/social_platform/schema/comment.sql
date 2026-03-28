CREATE TABLE IF NOT EXISTS comment (
    comment_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id     INTEGER,
    user_id     INTEGER,
    content     TEXT,
    created_at  TEXT
);
