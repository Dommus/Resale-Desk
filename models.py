from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

# Using SQLAlchemy as an ORM (Object Relational Mapping)
# to interact with the database using Python instead of SQL queries.
db = SQLAlchemy()

# Models
class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)