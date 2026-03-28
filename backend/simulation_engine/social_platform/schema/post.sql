CREATE TABLE IF NOT EXISTS post (
    post_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    content     TEXT,
    created_at  TEXT,
    num_likes       INTEGER DEFAULT 0,
    num_dislikes    INTEGER DEFAULT 0
);
