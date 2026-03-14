from peewee import SqliteDatabase, IntegrityError
from app.models import db, User, Request, Graph, Favorite
import os

DATABASE_NAME = os.getenv("DATABASE_NAME", "stock_analysis.db")

def initialize_db():
    db.init(DATABASE_NAME)
    db.connect()
    db.create_tables([User, Request, Graph, Favorite])
    db.close()

def get_db():
    return db

def connect_db():
    if db.is_closed():
        db.connect()

def close_db(e=None):
    if not db.is_closed():
        db.close()

def add_favorite(user_id, ticker):
    connect_db()
    try:
        user = User.get_or_none(id=user_id)
        if user:
            Favorite.create(user=user, ticker=ticker)
            return True
    except IntegrityError:
        # Favorite already exists
        return False
    finally:
        close_db()
    return False

def remove_favorite(user_id, ticker):
    connect_db()
    try:
        query = Favorite.delete().where(Favorite.user == user_id, Favorite.ticker == ticker)
        deleted_rows = query.execute()
        return deleted_rows > 0
    finally:
        close_db()

def get_favorites(user_id):
    connect_db()
    try:
        favorites = Favorite.select().where(Favorite.user == user_id)
        return [fav.ticker for fav in favorites]
    finally:
        close_db()

def is_favorite(user_id, ticker):
    connect_db()
    try:
        return Favorite.select().where(Favorite.user == user_id, Favorite.ticker == ticker).exists()
    finally:
        close_db()

