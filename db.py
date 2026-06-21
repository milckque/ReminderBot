import os
from sqlalchemy import create_engine, Column, Integer, BigInteger, String, DateTime, Boolean
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from datetime import datetime, timezone

_db_path = os.environ.get("DB_PATH", "reminders.db")
engine = create_engine(f"sqlite:///{_db_path}")
Session = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False)
    guild_id = Column(BigInteger, nullable=False)
    channel_id = Column(BigInteger, nullable=False)
    message = Column(String, nullable=False)
    interval_seconds = Column(Integer, nullable=False)
    next_fire_at = Column(DateTime(timezone=True), nullable=False)
    fire_count = Column(Integer, default=0, nullable=False)
    snoozed_until = Column(DateTime(timezone=True), nullable=True)
    completed = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def init_db():
    Base.metadata.create_all(engine)
