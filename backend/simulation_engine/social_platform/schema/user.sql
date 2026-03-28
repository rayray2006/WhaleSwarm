CREATE TABLE IF NOT EXISTS user (
    user_id     INTEGER PRIMARY KEY,
    agent_id    INTEGER,
    user_name   TEXT,
    name        TEXT,
    bio         TEXT,
    created_at  TEXT,
    num_followings  INTEGER DEFAULT 0,
    num_followers   INTEGER DEFAULT 0
);
