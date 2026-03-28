"""Shared enumerations for the social-platform simulation layer."""

from enum import IntEnum, auto


class ActionType(IntEnum):
    """Every action an agent can take on any simulated platform."""

    NONE = 0
    REPOST = auto()
    CREATE_POST = auto()
    LIKE_POST = auto()
    UNLIKE_POST = auto()
    FOLLOW = auto()
    UNFOLLOW = auto()
    MUTE = auto()
    QUOTE_POST = auto()
    CREATE_COMMENT = auto()
    DISLIKE_POST = auto()
    DISLIKE_COMMENT = auto()
    LIKE_COMMENT = auto()
    SEARCH_POSTS = auto()
    SEARCH_USER = auto()
    TREND = auto()
    REFRESH = auto()
    REPORT = auto()
    DO_NOTHING = auto()
    SIGN_UP = auto()
    CREATE_MARKET = auto()
    BUY_SHARES = auto()
    SELL_SHARES = auto()
    BROWSE_MARKETS = auto()
    VIEW_PORTFOLIO = auto()
    COMMENT_ON_MARKET = auto()


class RecsysType(IntEnum):
    """Recommendation-system backend selector."""

    RANDOM = 0
    REDDIT = auto()
    TWITTER = auto()
    TWHIN = auto()
