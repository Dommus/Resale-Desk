from datetime import datetime
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
    description = db.Column(db.String(256))

    items = db.relationship('Item', backref='shelf', lazy=True)


class Purchase(db.Model):
    __tablename__ = "purchases"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    date = db.Column(db.Date, nullable=False, default=datetime.now)
    seller = db.Column(db.String(128))
    platform = db.Column(db.String(64))
    purchase_type = db.Column(db.String(10), nullable=False, default="single")  # "single" or "bundle"
    purchase_price = db.Column(db.Float, nullable=False, default=0)
    shipping_cost = db.Column(db.Float, nullable=False, default=0)
    notes = db.Column(db.Text)


    shelf_id = db.Column(db.Integer, db.ForeignKey("shelves.id"))


class Item(db.Model):
    __tablename__ = "items"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    code = db.Column(db.String(20), unique=True)

    shelf_id = db.Column(db.Integer, db.ForeignKey("shelves.id"))
