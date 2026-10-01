from sqlalchemy import Column, Integer, String, TIMESTAMP, event, inspect as sa_inspect
from sqlalchemy.orm import relationship
from .base import Base
from .association import user_role_table
from datetime import datetime

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False)
    full_name = Column(String(200), nullable=True)
    email = Column(String(200), unique=True, nullable=False)
    password = Column(String(255), nullable=False)
    phone = Column(String(20), nullable=True)
    address = Column(String(255), nullable=True)
    # Registered company name - transfers to/from this company = Internal
    home_company = Column(String(255), nullable=True, default="")
    created_at = Column(TIMESTAMP, default=datetime.now)
    updated_at = Column(TIMESTAMP, default=datetime.now, onupdate=datetime.now)

    # Relationships roles
    roles = relationship('Role', secondary=user_role_table, back_populates='users')
    transactions = relationship('Transaction', back_populates='user', cascade='all, delete-orphan')

    # Check user roles

    def has_role(self, role_name):
        return any(role.name == role_name for role in self.roles)


# ── Mandatory contact details, enforced at the MODEL level ─────────────────────────────────────────────────────────────
# No code path (API, script, future feature) can INSERT a user without a valid email and phone number, and an existing user's email / phone
# cannot be changed to something invalid or blank. (PostgreSQL has a matching trigger - accfino_core.migrate - as a second line of defence.)
@event.listens_for(User, "before_insert")
def _user_contact_on_insert(mapper, connection, target):
    from accfino_core.security import contact
    contact.enforce_on_insert(target)


@event.listens_for(User, "before_update")
def _user_contact_on_update(mapper, connection, target):
    from accfino_core.security import contact
    state = sa_inspect(target)
    changed = [k for k in ("email", "phone") if state.attrs[k].history.has_changes()]
    if changed:
        contact.enforce_on_update(target, changed)
