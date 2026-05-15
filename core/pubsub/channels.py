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
