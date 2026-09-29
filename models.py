# https://flask-sqlalchemy.readthedocs.io/en/stable/quickstart/
# https://docs.sqlalchemy.org/en/20/orm/quickstart.html
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import String, Text, ForeignKey, Numeric, Enum as SQLEnum, func, CheckConstraint
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
    WAITING = 'Waiting'
    REFUNDED = 'Refunded'
    IN_STORAGE = 'In Storage'
    RESERVED = 'Reserved'
    NOT_SOLD = 'Not Sold'

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

    name: Mapped[Optional[str]] = mapped_column(String(128))
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
        return sum((item.sale.net_proceeds for item in self.items if item.sale is not None), Decimal("0.00"))
    
    @property
    def profit(self) -> Decimal:
        return sum(
            (item.sale.profit for item in self.items if item.sale and item.sale.profit is not None),
            Decimal("0.00"),
        )
    
    @property
    def display_name(self) -> str:
        return self.name or self.seller or self.platform or f"Purchase - {self.date}"

class Item(db.Model):
    __tablename__ = "items"

    __table_args__ = (
        # Ensure quantity is positive
        CheckConstraint("quantity > 0", name="ck_items_quantity_positive"),

        # Sold quantity must be between 0 and total quantity
        CheckConstraint(
            "quantity_sold >= 0 AND quantity_sold <= quantity",
            name="ck_items_quantity_sold_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    purchase_id: Mapped[int] = mapped_column(ForeignKey("purchases.id"), nullable=False)
    shelf_id: Mapped[Optional[int]] = mapped_column(ForeignKey("shelves.id"))

    # Can use Item.purchase.date to access the date the item was bought

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False, default=1)
    quantity_sold: Mapped[int] = mapped_column(nullable=False, default=0)
    # Total cost allocated to this product line. A zero value means that
    # bundle cost allocation has not been provided yet.
    cost_basis: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0.00"))
    category: Mapped[Optional[str]] = mapped_column(String(64))
    condition: Mapped[Optional[str]] = mapped_column(String(32))
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
    @property
    def inventory_code(self) -> str | None:
        if self.id is None:
            return None
        return f"I-{self.id:06d}"

    @property
    def days_in_inventory(self) -> int:
        end = self.sale.sale_date if self.sale else datetime_date.today()
        start = self.purchase.date if self.purchase.date else end
        return (end - start).days

    @property
    def available_quantity(self) -> int:
        return max(self.quantity - self.quantity_sold, 0)

    @property
    def unit_cost(self) -> Optional[Decimal]:

        # Cost of one unit when the purchase has an unambiguous cost.

        if not self.purchase or self.quantity <= 0:
            return None
        basis = self.total_cost_basis
        if basis is None:
            return None
        return basis / Decimal(self.quantity)

    @property
    def total_cost_basis(self) -> Optional[Decimal]:
        if not self.purchase or self.quantity <= 0:
            return None
        if self.purchase.purchase_type == PurchaseType.SINGLE:
            return round(self.purchase.total_cost, 2)
        allocated_cost = self.cost_basis or Decimal("0.00")
        if allocated_cost > 0:
            return round(allocated_cost, 2)
        return None

    @property
    def purchase_cost(self) -> Decimal:
        """Backward-compatible display value for this item's total cost."""
        return self.total_cost_basis or Decimal("0.00")

    def cost_for_quantity(self, quantity: int) -> Optional[Decimal]:
        if self.unit_cost is None or quantity < 0 or quantity > self.quantity:
            return None
        if quantity == self.quantity:
            return self.total_cost_basis
        return round(self.unit_cost * quantity, 2)

class Sale(db.Model):
    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False, unique=True)
    listing_id: Mapped[Optional[int]] = mapped_column(ForeignKey("listings.id"))

    sale_date: Mapped[datetime_date] = mapped_column(default=datetime_date.today)
    sale_price: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    shipping_collected: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    shipping_paid: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    platform_fee: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    payment_fee: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    quantity: Mapped[int] = mapped_column(nullable=False, default=1)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    item: Mapped["Item"] = relationship("Item", back_populates="sale")
    listing: Mapped[Optional["Listing"]] = relationship("Listing", back_populates="sale")

    @property
    def unit_sale_price(self):
        if not self.quantity:
            return Decimal("0.00")
        return round((self.sale_price or Decimal("0.00")) / self.quantity, 2)

    @property
    def gross_proceeds(self) -> Decimal:
        return round((self.sale_price or Decimal("0.00")) + (self.shipping_collected or Decimal("0.00")), 2)

    @property
    def net_proceeds(self) -> Decimal:
        return round(
            self.gross_proceeds
            - (self.shipping_paid or Decimal("0.00"))
            - (self.platform_fee or Decimal("0.00"))
            - (self.payment_fee or Decimal("0.00")),
            2,
        )

    @property
    def cost_basis(self) -> Optional[Decimal]:
        return self.item.cost_for_quantity(self.quantity) if self.item else None

    @property
    def profit(self) -> Optional[Decimal]:
        if self.cost_basis is None:
            return None
        return round(self.net_proceeds - self.cost_basis, 2)

    @property
    def roi(self) -> Optional[Decimal]:
        cost = self.cost_basis
        if cost is None or cost <= 0 or self.profit is None:
            return None
        return round((self.profit / cost) * 100, 1)

    @property
    def margin(self) -> Optional[Decimal]:
        if self.gross_proceeds <= 0 or self.profit is None:
            return None
        return round((self.profit / self.gross_proceeds) * 100, 1)

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
