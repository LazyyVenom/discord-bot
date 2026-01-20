from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from config import Config

engine = create_engine(Config.db_url, echo=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()