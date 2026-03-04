"""
Database Session Management for ATLAS
Handles SQLAlchemy engine and session creation.
"""
import logging
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import DATABASE_URL
from database.models import Base

logger = logging.getLogger(__name__)

# Global engine instance
_engine = None
_SessionLocal = None


def get_engine():
    """Get or create the SQLAlchemy engine."""
    global _engine
    if _engine is None:
        logger.info(f"Creating database engine...")
        _engine = create_engine(
            DATABASE_URL,
            echo=False,  # Set to True for SQL debugging
            pool_pre_ping=True,  # Verify connections before use
            pool_size=5,
            max_overflow=10,
        )
    return _engine


def get_session_factory():
    """Get the session factory."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_engine(),
        )
    return _SessionLocal


def get_session() -> Session:
    """Create a new database session."""
    SessionLocal = get_session_factory()
    return SessionLocal()


@contextmanager
def session_scope():
    """
    Context manager for database sessions.
    Automatically commits on success, rolls back on exception.
    
    Usage:
        with session_scope() as session:
            session.add(obj)
            # auto-commits on exit
    """
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Database error, rolling back: {e}")
        raise
    finally:
        session.close()


def init_db(drop_existing: bool = False):
    """
    Initialize the database - create all tables.
    
    Args:
        drop_existing: If True, drop all existing ATLAS tables first (DANGER!)
    """
    engine = get_engine()
    
    if drop_existing:
        logger.warning("Dropping all ATLAS tables...")
        Base.metadata.drop_all(bind=engine)
    
    logger.info("Creating ATLAS database tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialization complete.")


def check_connection() -> bool:
    """Test database connectivity."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute("SELECT 1")
        logger.info("Database connection successful")
        return True
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("Testing ATLAS database connection...")
    if check_connection():
        print("✓ Connection successful")
        
        print("\nInitializing database tables...")
        init_db()
        print("✓ Tables created")
    else:
        print("✗ Connection failed - check DATABASE_URL")
