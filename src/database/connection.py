"""
Database connection and session management for the EDS application.
"""

import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import StaticPool
from contextlib import contextmanager
import logging
from typing import Generator

from .models import Base

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages database connections and sessions for the EDS application."""

    def __init__(self, database_url: str = None):
        """
        Initialize the database manager.

        Args:
            database_url: PostgreSQL connection string. If None, will use environment variable.
        """
        if database_url is None:
            database_url = os.getenv(
                "DATABASE_URL",
                "postgresql://eds_user:eds_password@localhost:5432/eds_database",
            )

        self.database_url = database_url
        self.engine = None
        self.SessionLocal = None
        self._setup_engine()

    def _setup_engine(self):
        """Set up the SQLAlchemy engine with appropriate configuration."""
        try:
            # Configure engine with connection pooling
            self.engine = create_engine(
                self.database_url,
                echo=os.getenv("SQL_ECHO", "false").lower() == "true",
                pool_size=10,
                max_overflow=20,
                pool_recycle=3600,  # Recycle connections after 1 hour
                pool_pre_ping=True,  # Validate connections before use
            )

            # Create session factory
            self.SessionLocal = scoped_session(
                sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
            )

            # Set up connection event listeners
            self._setup_connection_events()

            logger.info("Database engine initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize database engine: {e}")
            raise

    def _setup_connection_events(self):
        """Set up SQLAlchemy event listeners for connection management."""

        @event.listens_for(self.engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            """Set up connection-specific settings."""
            if "postgresql" in self.database_url:
                # PostgreSQL-specific settings
                cursor = dbapi_connection.cursor()
                cursor.execute("SET timezone TO 'UTC'")
                cursor.close()

    def create_tables(self):
        """Create all database tables if they don't exist."""
        try:
            Base.metadata.create_all(bind=self.engine)
            logger.info("Database tables created successfully")
        except Exception as e:
            logger.error(f"Failed to create database tables: {e}")
            raise

    def drop_tables(self):
        """Drop all database tables. Use with caution!"""
        try:
            Base.metadata.drop_all(bind=self.engine)
            logger.warning("All database tables dropped")
        except Exception as e:
            logger.error(f"Failed to drop database tables: {e}")
            raise

    @contextmanager
    def get_session(self) -> Generator:
        """
        Context manager for database sessions.

        Yields:
            SQLAlchemy session object

        Example:
            with db_manager.get_session() as session:
                tiles = session.query(LandsatTile).all()
        """
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Database session error: {e}")
            raise
        finally:
            session.close()

    def get_session_direct(self):
        """
        Get a database session directly (not as context manager).

        Returns:
            SQLAlchemy session object

        Note:
            Remember to close the session when done!
        """
        return self.SessionLocal()

    def health_check(self) -> bool:
        """
        Perform a basic health check on the database connection.

        Returns:
            True if database is accessible, False otherwise
        """
        try:
            from sqlalchemy import text

            with self.get_session() as session:
                session.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False

    def close(self):
        """Close all database connections and clean up resources."""
        if self.SessionLocal:
            self.SessionLocal.remove()
        if self.engine:
            self.engine.dispose()
        logger.info("Database connections closed")


# Global database manager instance
db_manager = DatabaseManager()


# Convenience functions for getting database sessions
def get_db_session():
    """Get a database session. Remember to close it when done!"""
    return db_manager.get_session_direct()


@contextmanager
def get_db():
    """Context manager for getting a database session."""
    with db_manager.get_session() as session:
        yield session


# Function to initialize the database
def init_database(database_url: str = None, create_tables: bool = True):
    """
    Initialize the database with optional table creation.

    Args:
        database_url: PostgreSQL connection string
        create_tables: Whether to create tables if they don't exist
    """
    global db_manager

    if database_url:
        db_manager = DatabaseManager(database_url)

    if create_tables:
        db_manager.create_tables()

    logger.info("Database initialized successfully")
