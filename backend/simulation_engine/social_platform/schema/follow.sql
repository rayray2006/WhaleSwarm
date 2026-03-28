CREATE TABLE IF NOT EXISTS follow (
    follower_id INTEGER,
    followee_id INTEGER,
    created_at  TEXT,
    PRIMARY KEY (follower_id, followee_id)
);
