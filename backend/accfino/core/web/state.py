"""Process-wide readiness flag (set by the start-up hook, read by /ready)."""
_ready = False


def mark_ready() -> None:
    global _ready
    _ready = True


def is_ready() -> bool:
    return _ready
