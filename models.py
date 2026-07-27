# https://flask-sqlalchemy.readthedocs.io/en/stable/quickstart/
# https://docs.sqlalchemy.org/en/20/orm/quickstart.html
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import String, Text, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from datetime import date as datetime_date, datetime
from enum import Enum
from typing import List, Optional


# Using SQLAlchemy as an ORM (Object Relational Mapping)
# to interact with the database using Python instead of SQL queries.
class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)





# Models
class ItemStatus(Enum):
    ON_SALE = 'on sale'
    SOLD = 'sold'
    NOT_SOLD = 'not sold'
    WAITING = 'waiting'
    REFUNDED = 'refunded'


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(primary_key=True)
    username:Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)

class Inventory(db.Model):
    __tablename__ = 'inventory'

    id: Mapped[int] = mapped_column(primary_key=True)

class Shelf(db.Model):
    __tablename__ = 'shelves'

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    
    description: Mapped[Optional[str]] = mapped_column(String(256))

    items: Mapped[List["Item"]] = relationship("Item", back_populates="shelf", lazy=True)


class Purchase(db.Model):
    __tablename__ = "purchases"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    
    date: Mapped[datetime_date] = mapped_column(nullable=False, default=datetime_date.today)
    seller: Mapped[Optional[str]] = mapped_column(String(128))
    platform: Mapped[Optional[str]] = mapped_column(String(64))
    purchase_type: Mapped[str] = mapped_column(String(10), nullable=False, default="single")
    purchase_price: Mapped[float] = mapped_column(nullable=False, default=0.0)
    shipping_cost: Mapped[float] = mapped_column(nullable=False, default=0.0)
    notes: Mapped[Optional[str]] = mapped_column(Text)


class Item(db.Model):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    code: Mapped[Optional[str]] = mapped_column(String(10), unique=True) # NEED TO IMPLEMENT THIS, MAYBE EVEN WITH A QR CODE
    brand: Mapped[Optional[str]] = mapped_column(String(32))
    status: Mapped[ItemStatus] = mapped_column(SQLEnum(ItemStatus), default=ItemStatus.ON_SALE)
 
    purchase_id: Mapped[int] = mapped_column(ForeignKey("purchases.id"))

    shelf_id: Mapped[Optional[int]] = mapped_column(ForeignKey("shelves.id"))
    shelf: Mapped[Optional["Shelf"]] = relationship("Shelf", back_populates="items")
