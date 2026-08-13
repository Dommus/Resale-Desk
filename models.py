# https://flask-sqlalchemy.readthedocs.io/en/stable/quickstart/
# https://docs.sqlalchemy.org/en/20/orm/quickstart.html
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import String, ForeignKey, Enum as SQLEnum, func
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
    ON_SALE = 'On Sale'
    SOLD = 'Sold'
    NOT_SOLD = 'Not Sold'
    WAITING = 'Waiting'
    REFUNDED = 'Refunded'
    IN_STORAGE = 'In Storage'
    RESERVED = 'Reserved'

class ListingStatus(Enum):
    ACTIVE = 'Active'
    SOLD = 'Sold'
    REMOVED = 'Removed'
    EXPIRED = 'Expired'

class PurchaseType(Enum):
    SINGLE = 'Single'
    BUNDLE = 'Bundle'


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(primary_key=True)

    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)

    shelves: Mapped[List["Shelf"]] = relationship("Shelf", back_populates="owner", cascade="all, delete-orphan", lazy=True)
    purchases: Mapped[List["Purchase"]] = relationship("Purchase", back_populates="owner", cascade="all, delete-orphan", lazy=True)
    items: Mapped[List["Item"]] = relationship("Item", back_populates="owner", cascade="all, delete-orphan", lazy=True)

class Inventory(db.Model):
    __tablename__ = 'inventory'

    id: Mapped[int] = mapped_column(primary_key=True)

class Shelf(db.Model):
    __tablename__ = 'shelves'

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(256))

    owner: Mapped["User"] = relationship("User", back_populates="shelves")
    items: Mapped[List["Item"]] = relationship("Item", back_populates="shelf", lazy=True)


class Purchase(db.Model):
    __tablename__ = "purchases"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    seller: Mapped[Optional[str]] = mapped_column(String(128))
    platform: Mapped[Optional[str]] = mapped_column(String(64))
    date: Mapped[datetime_date] = mapped_column(default=datetime_date.today)
    purchase_type: Mapped[PurchaseType] = mapped_column(SQLEnum(PurchaseType), nullable=False, default=PurchaseType.SINGLE)
    purchase_price: Mapped[float] = mapped_column(nullable=False, default=0.0)
    shipping_cost: Mapped[float] = mapped_column(nullable=False, default=0.0)
    notes: Mapped[Optional[str]] = mapped_column(String(5120))

    items: Mapped[List["Item"]] = relationship("Item", back_populates="purchase", cascade="all, delete-orphan", lazy=True)
    owner: Mapped["User"] = relationship("User", back_populates="purchases")

    @property
    def total_cost(self):
        return round((self.purchase_price or 0) + (self.shipping_cost or 0), 2)

    @property
    def allocated_total(self):
        return round(sum(i.allocated_cost or 0 for i in self.items), 2)

    # Sums revenue across the purchase's sold items and subtracts total cost of all items associated with it
    @property
    def profit(self):
        total_revenue = sum(
            item.sale.net_revenue for item in self.items if item.sale is not None
        )
        return round(sum(i.allocated_cost or 0 for i in self.items), 2)

class Item(db.Model):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    purchase_id: Mapped[int] = mapped_column(ForeignKey("purchases.id"), nullable=False)
    shelf_id: Mapped[Optional[int]] = mapped_column(ForeignKey("shelves.id"))

    # Can use Item.purchase.date to access the date the item was bought

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(64))
    condition: Mapped[Optional[str]] = mapped_column(String(32))
    # code: Mapped[Optional[str]] = mapped_column(String(10), unique=True)  # NEED TO IMPLEMENT THIS, MAYBE EVEN WITH A QR CODE
    brand: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[ItemStatus] = mapped_column(
        SQLEnum(ItemStatus, values_callable=lambda statuses: [status.value for status in statuses]),
        default=ItemStatus.ON_SALE,
    )
    notes: Mapped[Optional[str]] = mapped_column(String(5120))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    allocated_cost: Mapped[float] = mapped_column(default=0) #RENAME THIS TO JUST COST

    owner: Mapped["User"] = relationship("User", back_populates="items")
    purchase: Mapped["Purchase"] = relationship("Purchase", back_populates="items")
    shelf: Mapped[Optional["Shelf"]] = relationship("Shelf", back_populates="items")

    listings = db.relationship("Listing", backref="item", lazy=True, cascade="all, delete-orphan")
    sale = db.relationship("Sale", backref="item", uselist=False, cascade="all, delete-orphan")


    def generate_code(self):
        self.inventory_code = f"INV-{self.id:06d}"

    @property
    def days_in_inventory(self):
        end = self.sale.sale_date if self.sale else datetime_date.today
        start = self.created_at.date() if self.created_at else end
        return (end - start).days

class Sale(db.Model):
    __tablename__ = "sales"

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False, unique=True)
    listing_id = db.Column(db.Integer, db.ForeignKey("listings.id"))

    sale_date = db.Column(db.Date, nullable=False, default=datetime_date.today)
    sale_price = db.Column(db.Float, nullable=False, default=0)
    shipping_received = db.Column(db.Float, nullable=False, default=0)
    shipping_paid = db.Column(db.Float, nullable=False, default=0)
    platform_fee = db.Column(db.Float, nullable=False, default=0)
    payment_fee = db.Column(db.Float, nullable=False, default=0)
    notes = db.Column(db.Text)

    listing = db.relationship("Listing", backref="sale")

    @property
    def gross_revenue(self):
        return round((self.sale_price or 0) + (self.shipping_received or 0), 2)

    @property
    def net_revenue(self):
        return round(
            self.gross_revenue - (self.shipping_paid or 0) - (self.platform_fee or 0) - (self.payment_fee or 0), 2
        )

    @property
    def profit(self):
        cost = self.item.allocated_cost or 0
        return round(self.net_revenue - cost, 2)

    @property
    def roi(self):
        cost = self.item.allocated_cost or 0
        if cost <= 0:
            return None
        return round((self.profit / cost) * 100, 1)

    @property
    def margin(self):
        if self.gross_revenue <= 0:
            return None
        return round((self.profit / self.gross_revenue) * 100, 1)

class Listing(db.Model):
    __tablename__ = "listings"

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False)

    platform = db.Column(db.String(80), nullable=False)
    listing_id = db.Column(db.String(120), nullable=False)
    listing_url = db.Column(db.String(500))
    listing_price = db.Column(db.Float)
    date_listed = db.Column(db.Date, default=datetime_date.today)
    status: Mapped[ListingStatus] = mapped_column(SQLEnum(ListingStatus), default=ListingStatus.ACTIVE)
