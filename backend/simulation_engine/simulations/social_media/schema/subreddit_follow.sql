CREATE TABLE IF NOT EXISTS subreddit_follow (
    user_id       INTEGER,
    subreddit_id  INTEGER,
    created_at    TEXT,
    PRIMARY KEY (user_id, subreddit_id)
);
