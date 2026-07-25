from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

# Using SQLAlchemy as an ORM (Object Relational Mapping)
# to interact with the database using Python instead of SQL queries.
db = SQLAlchemy()

# Models
class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)

class Inventory(db.Model):
    __tablename__ = 'inventory'

    id = db.Column(db.Integer, primary_key=True)

class Shelf(db.Model):
    __tablename__ = 'shelves'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    name = db.Column(db.String(64), nullable=False)
    description = db.Column(db.String(255))

    items = db.relationship('Item', backref='shelf', lazy=True)

class Item(db.Model):
    __tablename__ = "items"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    code = db.Column(db.String(20), unique=True)

    shelf_id = db.Column(db.Integer, db.ForeignKey("shelves.id"))
