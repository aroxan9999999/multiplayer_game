from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    Table,
)
from sqlalchemy.ext.mutable import MutableList, MutableDict
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime
from sqlalchemy.dialects.postgresql import ARRAY, JSON
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.dialects.postgresql import JSON

Base = declarative_base()

game_players = Table(
    'game_players',
    Base.metadata,
    Column('user_id', ForeignKey('users.id'), primary_key=True),
    Column('game_id', ForeignKey('games.id'), primary_key=True)
)


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, index=True)
    password_hash = Column(String(128))
    color = Column(String(8))
    total_games = Column(Integer, default=0)
    total_clicks = Column(Integer, default=0)
    success_clicks = Column(Integer, default=0)
    date_registration = Column(DateTime, default=datetime.utcnow)
    color_used = Column(MutableList.as_mutable(ARRAY(String)), default=list)
    wins_count = Column(Integer, default=0)
    games = relationship("Game", secondary=game_players, back_populates="players")


class Game(Base):
    __tablename__ = 'games'

    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=False)
    players = relationship("User", secondary=game_players, back_populates="games")
    game_players = Column(MutableList.as_mutable(ARRAY(String)), default=list)
    clicked_cells = Column(MutableList.as_mutable(ARRAY(Integer)), default=list)
    total_clicks = Column(Integer, default=0)
    winners = Column(MutableList.as_mutable(ARRAY(String)), default=list)
    game_state = Column(MutableDict.as_mutable(JSON), default=dict)


class UserState(Base):
    __tablename__ = 'user_states'
    id = Column(Integer, primary_key=True)
    game_id = Column(Integer, ForeignKey('games.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    game = relationship("Game", backref="user_states")
    user = relationship("User", backref="user_states")
    total_clicks = Column(Integer, default=0)
    success_clicks = Column(Integer, default=0)
    failed_clicks = Column(Integer, default=0)
    joined_at = Column(DateTime, default=datetime.utcnow)
    color = Column(String(8))