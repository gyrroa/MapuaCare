# app/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import settings

# More resilient engine config for Supabase
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,     # tests connections before using them
    pool_recycle=1800,      # recycle every 30 min (prevents server kills)
    pool_size=5,            # reasonable defaults
    max_overflow=10,        # short spikes
    pool_timeout=30,        # wait time for a connection
    future=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
