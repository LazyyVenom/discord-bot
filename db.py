from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from config import Config

engine = create_engine(Config.db_url, echo=False)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

def init_db():
    """Initialize database tables"""
    Base.metadata.create_all(engine)

def get_session():
    """Get a new database session"""
    return SessionLocal()

def get_or_create_user(session, discord_id, username):
    """Get or create a user"""
    from models import User
    user = session.query(User).filter_by(discord_id=discord_id).first()
    if not user:
        user = User(discord_id=discord_id, username=username)
        session.add(user)
        session.commit()
    return user

def add_question(session, title, description, category, correct_option, difficulty="medium", points=10, asked_by=None, 
                 option_a=None, option_b=None, option_c=None, option_d=None, answer=None):
    """Add a new question to the database (MCQ format)"""
    from models import Question
    question = Question(
        title=title,
        description=description,
        category=category,
        option_a=option_a,
        option_b=option_b,
        option_c=option_c,
        option_d=option_d,
        correct_option=correct_option,
        answer=answer,
        difficulty=difficulty,
        points=points,
        asked_by=asked_by
    )
    session.add(question)
    session.commit()
    return question

def add_resource(session, title, url, category, description=None, tags=None, added_by=None):
    """Add a new resource to the database"""
    from models import Resource
    resource = Resource(
        title=title,
        url=url,
        category=category,
        description=description,
        tags=tags,
        added_by=added_by
    )
    session.add(resource)
    session.commit()
    return resource

def record_answer(session, question_id, user_id, answer_text, is_correct, points_awarded=0):
    """Record a user's answer"""
    from models import Answer, User
    answer = Answer(
        question_id=question_id,
        user_id=user_id,
        answer_text=answer_text,
        is_correct=is_correct,
        points_awarded=points_awarded
    )
    session.add(answer)
    
    if is_correct:
        user = session.query(User).filter_by(id=user_id).first()
        if user:
            user.aura_points += points_awarded
            user.correct_answers += 1
        
    session.commit()
    return answer