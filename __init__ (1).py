"""
BTC Reflex Engine — Database Session Helpers
"""
from __future__ import annotations
from contextlib import contextmanager
from app.database.models import SessionLocal


@contextmanager
def get_db():
    """Context manager for safe DB sessions. Always closes on exit."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
