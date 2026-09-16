# https://flask-sqlalchemy.readthedocs.io/en/stable/quickstart/
# https://docs.sqlalchemy.org/en/20/orm/quickstart.html
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import String, Text, ForeignKey, Numeric, Enum as SQLEnum, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from datetime import date as datetime_date, datetime
from enum import Enum
from typing import List, Optional
from decimal import Decimal


# Using SQLAlchemy as an ORM (Object Relational Mapping) to interact with the database by writing  Python instead of SQL queries.

# Initialize the extension
class Base(DeclarativeBase):
    pass

# Define standard type for money, to not have to write it over and over again
MONEY = Numeric(12, 2)

db = SQLAlchemy(model_class=Base)

#############
# Models
#############

class ItemStatus(Enum):
    # TODO: Remove any status I decide later not to use
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

class Shelf(db.Model):
    __tablename__ = 'shelves'

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), nullable=False)

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(256))

    owner: Mapped["User"] = relationship("User", back_populates="shelves")
    items: Mapped[List["Item"]] = relationship("Item", back_populates="shelf", lazy=True)


class Purchase(db.Model):
    __tablename__ = 'purchases'

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    seller: Mapped[Optional[str]] = mapped_column(String(128))
    platform: Mapped[Optional[str]] = mapped_column(String(64))
    date: Mapped[datetime_date] = mapped_column(default=datetime_date.today)
    purchase_type: Mapped[PurchaseType] = mapped_column(SQLEnum(PurchaseType), nullable=False, default=PurchaseType.SINGLE)
    purchase_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0.00"))
    shipping_cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0.00"))
    notes: Mapped[Optional[str]] = mapped_column(Text)

    items: Mapped[List["Item"]] = relationship("Item", back_populates="purchase", cascade="all, delete-orphan", lazy=True)
    owner: Mapped["User"] = relationship("User", back_populates="purchases")


    # https://www.geeksforgeeks.org/python/python-property-function/
    # Note: using '->' annotations on these functions to specify the return type
    @property
    def total_cost(self) -> Decimal:
        purchase_price = self.purchase_price if self.purchase_price is not None else Decimal("0")
        shipping_cost = self.shipping_cost if self.shipping_cost is not None else Decimal("0")
        return purchase_price + shipping_cost

    @property
    def total_revenue(self) -> Decimal:
        return sum((item.sale.net_revenue for item in self.items if item.sale is not None), Decimal("0.00"))
    
    @property
    def profit(self) -> Decimal:
        # Show profit differently depending on the situation
        # Might make different profit functions instead later?
        ##### THIS IS UNFINISHED. TOUCH LATER

        total_profit = Decimal("0.00")
        if self.purchase_type == PurchaseType.BUNDLE:
            bundle_cost = self.purchase_price

        for item in self.items:
            if item.status == ItemStatus.SOLD and item.sale:
                if self.purchase_type == PurchaseType.SINGLE:
                    item_profit = item.sale.sale_price
                    total_profit += item_profit
                elif self.purchase_type == PurchaseType.BUNDLE:
                    items_revenue += item.sale.sale_price
                    total_profit = items_revenue - bundle_cost 

        return round(total_profit, 2)
    
    @property
    def display_name(self) -> str:
        name = self.seller or self.platform or "Purchase"
        return f"{name} - {self.date}"

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

    owner: Mapped["User"] = relationship("User", back_populates="items")
    purchase: Mapped["Purchase"] = relationship("Purchase", back_populates="items")
    shelf: Mapped[Optional["Shelf"]] = relationship("Shelf", back_populates="items")

    listings: Mapped[List["Listing"]] = relationship("Listing", back_populates="item", cascade="all, delete-orphan", lazy=True)
    sale: Mapped[Optional["Sale"]] = relationship("Sale", back_populates="item", uselist=False, cascade="all, delete-orphan")

    # WORK ON THIS LATER. UNFINISHED IMPLEMENTATION
    # # # # # ## # ## # ## # #
     # # # # # # # # # # # # 
    def generate_code(self):
        self.inventory_code = f"INV-{self.id:06d}"

    @property
    def days_in_inventory(self) -> int:
        end = self.sale.sale_date if self.sale else datetime_date.today()
        start = self.created_at.date() if self.created_at else end
        return (end - start).days

    @property
    def purchase_cost(self) -> Decimal:
        return self.purchase.total_cost if self.purchase else Decimal("0.00")

class Sale(db.Model):
    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False, unique=True)
    listing_id: Mapped[Optional[int]] = mapped_column(ForeignKey("listings.id"))

    sale_date: Mapped[datetime_date] = mapped_column(default=datetime_date.today)
    sale_price: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    shipping_received: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    shipping_paid: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    platform_fee: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    payment_fee: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    notes: Mapped[Optional[str]] = mapped_column(Text)

    item: Mapped["Item"] = relationship("Item", back_populates="sale")
    listing: Mapped[Optional["Listing"]] = relationship("Listing", back_populates="sale")

    @property
    def gross_revenue(self) -> Decimal:
        return round((self.sale_price or Decimal("0.00")) + (self.shipping_received or Decimal("0.00")), 2)

    @property
    def net_revenue(self) -> Decimal:
        return round(
            self.gross_revenue
            - (self.shipping_paid or Decimal("0.00"))
            - (self.platform_fee or Decimal("0.00"))
            - (self.payment_fee or Decimal("0.00")),
            2,
        )

    @property
    def profit(self) -> Optional[Decimal]:
        return round(self.net_revenue - self.item.purchase_cost, 2)

    @property
    def roi(self) -> Optional[Decimal]:
        cost = self.item.purchase_cost
        if cost <= 0:
            return None
        return round((self.profit / cost) * 100, 1)

    @property
    def margin(self) -> Optional[Decimal]:
        if self.gross_revenue <= 0:
            return None
        return round((self.profit / self.gross_revenue) * 100, 1)

class Listing(db.Model):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)

    platform: Mapped[str] = mapped_column(String(80), nullable=False)
    listing_id: Mapped[str] = mapped_column(String(120))
    listing_url: Mapped[Optional[str]] = mapped_column(String(500))
    listing_price: Mapped[Optional[Decimal]] = mapped_column(MONEY, default=None)
    date_listed: Mapped[datetime_date] = mapped_column(default=datetime_date.today)
    # Persist the human-readable enum values (Active, Sold, ...) so they
    # match the existing database rows and the values used by the forms.
    status: Mapped[ListingStatus] = mapped_column(
        SQLEnum(ListingStatus, values_callable=lambda statuses: [status.value for status in statuses]),
        default=ListingStatus.ACTIVE,
    )

    item: Mapped["Item"] = relationship("Item", back_populates="listings")
    sale: Mapped[Optional["Sale"]] = relationship("Sale", back_populates="listing", uselist=False)
