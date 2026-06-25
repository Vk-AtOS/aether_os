"""
PostgreSQL database configuration for DCSP.
"""

from __future__ import annotations

import os
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from src.models import Base
from dotenv import load_dotenv

load_dotenv()

# Database URL from environment
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./vkatos.db")

# Create engine (PostgreSQL connection)
engine = create_engine(DATABASE_URL)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all_tables() -> None:
    """Create all SQLAlchemy models in the database."""
    Base.metadata.create_all(bind=engine)
