"""
Channel naming convention for Redis pub/sub.

Format: account:{account_id}:{event_type}
Centralized to prevent typos across producers and consumers.
"""


def position_channel(account_id: int) -> str:
    return f"account:{account_id}:position_update"


def fill_channel(account_id: int) -> str:
    return f"account:{account_id}:fill"


def order_channel(account_id: int) -> str:
    return f"account:{account_id}:order_update"


def equity_channel(account_id: int) -> str:
    return f"account:{account_id}:equity_update"


def dd_state_channel(account_id: int) -> str:
    return f"account:{account_id}:dd_state"


def weekly_pnl_channel(account_id: int) -> str:
    return f"account:{account_id}:weekly_pnl"


def channel_pattern(account_id: int) -> str:
    """PSUBSCRIBE pattern matching all channels for an account."""
    return f"account:{account_id}:*"


def extract_event_type(channel: str) -> str:
    """Extract event type from channel name (last segment after ':')."""
    parts = channel.split(":")
    return parts[-1] if len(parts) >= 3 else channel
