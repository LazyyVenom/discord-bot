from db import engine, SessionLocal
from models import User
from db import Base

Base.metadata.create_all(engine)

session = SessionLocal()
session.commit()

users = session.query(User).all()
print(users)

session.close()