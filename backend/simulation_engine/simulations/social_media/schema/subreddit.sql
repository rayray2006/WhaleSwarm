CREATE TABLE IF NOT EXISTS subreddit (
    subreddit_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT UNIQUE NOT NULL,
    description    TEXT DEFAULT '',
    creator_id     INTEGER,
    num_followers  INTEGER DEFAULT 0,
    created_at     TEXT
);
