from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.orm import relationship
from accfino.shared.db.base import Base
from accfino.core.identity.association import role_permission_table

class Permission(Base):
    __tablename__ = 'permissions'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)

    # Relationships
    roles = relationship('Role', secondary=role_permission_table, back_populates='permissions')