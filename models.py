from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin

# Using SQLAlchemy as an ORM (Object Relational Mapping)
# to interact with the database using Python instead of SQL queries.
db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.login_message = "Please log in to continue."
login_manager.login_message_category = "warning"

# Models
class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)