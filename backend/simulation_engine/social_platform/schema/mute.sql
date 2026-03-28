CREATE TABLE IF NOT EXISTS mute (
    user_id     INTEGER,
    muted_id    INTEGER,
    created_at  TEXT,
    PRIMARY KEY (user_id, muted_id)
);
