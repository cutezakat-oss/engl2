from sqlalchemy import Integer, String, DateTime, func, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, declarative_base, relationship
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str] = mapped_column(String(255), nullable=True)
    created_at = mapped_column(DateTime, server_default=func.now())

    elo: Mapped[int] = mapped_column(Integer, default=300)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    games_played: Mapped[int] = mapped_column(Integer, default=0)

    settings: Mapped["UserSettings"] = relationship(back_populates="user", uselist=False)
    learned_words: Mapped[list["LearnedWord"]] = relationship(back_populates="user")
    study_words: Mapped[list["StudyWord"]] = relationship(back_populates="user")

    battles_as_player1: Mapped[list["Battle"]] = relationship(
        foreign_keys="Battle.player1_id",
        back_populates="player1"
    )
    battles_as_player2: Mapped[list["Battle"]] = relationship(
        foreign_keys="Battle.player2_id",
        back_populates="player2"
    )

    # Связи для приглашений
    invites_sent: Mapped[list["Invite"]] = relationship(
        foreign_keys="Invite.inviter_id",
        back_populates="inviter"
    )
    invites_received: Mapped[list["Invite"]] = relationship(
        foreign_keys="Invite.invitee_id",
        back_populates="invitee"
    )

class UserSettings(Base):
    __tablename__ = "user_settings"
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), primary_key=True)
    difficulty: Mapped[str] = mapped_column(String(20), default="medium")
    user: Mapped["User"] = relationship(back_populates="settings")

class LearnedWord(Base):
    __tablename__ = "learned_words"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    word: Mapped[str] = mapped_column(String(100), nullable=False)
    translation: Mapped[str] = mapped_column(String(100), nullable=True)
    learned_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    user: Mapped["User"] = relationship(back_populates="learned_words")

class StudyWord(Base):
    __tablename__ = "study_words"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    word: Mapped[str] = mapped_column(String(100), nullable=False)
    translation: Mapped[str] = mapped_column(String(100), nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    user: Mapped["User"] = relationship(back_populates="study_words")

# ---------- PvP модели ----------
class Battle(Base):
    __tablename__ = "battles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player1_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    player2_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="waiting")
    winner_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    rounds_total: Mapped[int] = mapped_column(Integer, default=10)
    current_round: Mapped[int] = mapped_column(Integer, default=0)
    player1_score: Mapped[int] = mapped_column(Integer, default=0)
    player2_score: Mapped[int] = mapped_column(Integer, default=0)
    difficulty: Mapped[str] = mapped_column(String(20), default="medium")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    player1: Mapped["User"] = relationship(foreign_keys=[player1_id], back_populates="battles_as_player1")
    player2: Mapped["User"] = relationship(foreign_keys=[player2_id], back_populates="battles_as_player2")
    winner: Mapped["User"] = relationship(foreign_keys=[winner_id])
    rounds: Mapped[list["BattleRound"]] = relationship(back_populates="battle", cascade="all, delete-orphan")

class BattleRound(Base):
    __tablename__ = "battle_rounds"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    battle_id: Mapped[int] = mapped_column(Integer, ForeignKey("battles.id"), nullable=False)
    round_number: Mapped[int] = mapped_column(Integer)
    question_type: Mapped[str] = mapped_column(String(20), default="text_input")
    word: Mapped[str] = mapped_column(String(100))
    correct_answer: Mapped[str] = mapped_column(String(100))
    options: Mapped[str] = mapped_column(String(500), nullable=True)
    player1_answer: Mapped[str] = mapped_column(String(100), nullable=True)
    player2_answer: Mapped[str] = mapped_column(String(100), nullable=True)
    player1_time: Mapped[float] = mapped_column(nullable=True)
    player2_time: Mapped[float] = mapped_column(nullable=True)
    winner_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    battle: Mapped["Battle"] = relationship(back_populates="rounds")
    winner: Mapped["User"] = relationship(foreign_keys=[winner_id])

# ---------- Новая модель для приглашений ----------
class Invite(Base):
    __tablename__ = "invites"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inviter_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    invitee_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, accepted, declined, expired
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    inviter: Mapped["User"] = relationship(foreign_keys=[inviter_id], back_populates="invites_sent")
    invitee: Mapped["User"] = relationship(foreign_keys=[invitee_id], back_populates="invites_received")
