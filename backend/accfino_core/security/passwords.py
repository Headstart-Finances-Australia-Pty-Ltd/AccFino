"""Password policy for new and changed passwords (existing passwords keep working)."""
from fastapi import HTTPException

from accfino_core import config


def validate_new_password(pw: str) -> None:
    pw = pw or ""
    problems = []
    if len(pw) < config.PASSWORD_MIN_LENGTH:
        problems.append(f"at least {config.PASSWORD_MIN_LENGTH} characters")
    if not any(c.isalpha() for c in pw):
        problems.append("a letter")
    if not any(c.isdigit() for c in pw):
        problems.append("a number")
    if problems:
        raise HTTPException(400, "Password must contain " + ", ".join(problems))
