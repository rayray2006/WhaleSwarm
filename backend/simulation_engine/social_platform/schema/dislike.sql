CREATE TABLE IF NOT EXISTS dislike (
    user_id     INTEGER,
    post_id     INTEGER,
    created_at  TEXT,
    PRIMARY KEY (user_id, post_id)
);
