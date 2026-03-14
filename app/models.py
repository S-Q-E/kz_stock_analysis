from peewee import *
from datetime import datetime

db = SqliteDatabase(None)  # Will be initialized in db.py


class BaseModel(Model):
    class Meta:
        database = db


class User(BaseModel):
    id = IntegerField(primary_key=True)
    username = CharField(null=True)
    first_name = CharField(null=True)
    last_name = CharField(null=True)


class Request(BaseModel):
    id = AutoField(primary_key=True)
    user = ForeignKeyField(User, backref='requests')
    ticker = CharField()
    period = CharField()
    request_date = DateTimeField(default=datetime.now)
    trend = CharField(null=True)
    forecast = CharField(null=True)
    comment = CharField(null=True)


class Graph(BaseModel):
    id = AutoField(primary_key=True)
    request = ForeignKeyField(Request, backref='graphs')
    filepath = CharField()


class Favorite(BaseModel):
    user = ForeignKeyField(User, backref='favorites')
    ticker = CharField()

    class Meta:
        primary_key = CompositeKey('user', 'ticker')
