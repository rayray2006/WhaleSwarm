CREATE TABLE IF NOT EXISTS subreddit_similarity (
    subreddit_id         INTEGER,
    similar_subreddit_id INTEGER,
    created_at           TEXT,
    PRIMARY KEY (subreddit_id, similar_subreddit_id)
);
