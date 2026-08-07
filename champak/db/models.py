"""SQLAlchemy models. This file is the authoritative schema definition."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    discord_id = Column(String, unique=True, nullable=False)
    username = Column(String, nullable=False)
    # Cached aggregates. Every write goes through services.users so these
    # stay in step with the answers table; admin.py recompute-aura repairs
    # them if they ever drift.
    aura_points = Column(Integer, nullable=False, default=0)
    correct_answers = Column(Integer, nullable=False, default=0)
    total_answers = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=_utcnow)

    answers = relationship("Answer", back_populates="user")


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)  # the question text itself
    description = Column(Text, nullable=True)  # optional elaboration
    category = Column(String, nullable=False)
    difficulty = Column(Integer, nullable=False, default=2)  # 1-5

    # Option columns stay nullable because tightening them in SQLite means a
    # table rebuild; services.questions rejects incomplete questions instead.
    option_a = Column(Text, nullable=True)
    option_b = Column(Text, nullable=True)
    option_c = Column(Text, nullable=True)
    option_d = Column(Text, nullable=True)
    correct_option = Column(String, nullable=False)  # A, B, C or D

    explanation = Column(Text, nullable=False)
    points = Column(Integer, nullable=False, default=10)
    is_active = Column(Boolean, nullable=False, default=True)
    asked_by = Column(String, nullable=True)
    import_key = Column(String, unique=True, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    answers = relationship("Answer", back_populates="question")


class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (
        # Doubles as a race guard: two fast button clicks cannot both insert
        # the same attempt number.
        UniqueConstraint("question_id", "user_id", "attempt_number",
                         name="uq_answer_attempt"),
        Index("ix_answers_user_question", "user_id", "question_id"),
    )

    id = Column(Integer, primary_key=True)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    answer_text = Column(Text, nullable=False)
    is_correct = Column(Boolean, nullable=False, default=False)
    points_awarded = Column(Integer, nullable=False, default=0)
    attempt_number = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=_utcnow)

    question = relationship("Question", back_populates="answers")
    user = relationship("User", back_populates="answers")


class Resource(Base):
    __tablename__ = "resources"

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    url = Column(String, nullable=False)
    category = Column(String, nullable=False)
    tags = Column(String, nullable=True)
    added_by = Column(String, nullable=True)
    upvotes = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=_utcnow)
