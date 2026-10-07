"""Identity models (users, roles, permissions, reset tokens).

Importing any one of them imports them all, so string-based relationships ('Role', 'Permission', ...) always resolve - the same guarantee
db_app.models.__init__ gave before the modular split."""
from accfino.core.identity import association, permission, role, password_reset_token, user  # noqa: F401
