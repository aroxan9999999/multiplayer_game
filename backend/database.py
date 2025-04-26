from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base  # ВАЖНО! Это твой Base из models.py

DATABASE_URL = "postgresql://test:123@localhost/multiplayer_db"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)
