# https://flask-sqlalchemy.readthedocs.io/en/stable/quickstart/
# https://docs.sqlalchemy.org/en/20/orm/quickstart.html
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import String, Text, ForeignKey, Numeric, Enum as SQLEnum, func, CheckConstraint, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from datetime import date as datetime_date, datetime
from enum import Enum
from typing import List, Optional
from decimal import Decimal
from translations import _


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
    ON_SALE = 'On Sale'
    SOLD = 'Sold'
    WAITING = 'Waiting'
    IN_STORAGE = 'In Storage'
    RESERVED = 'Reserved'
    WRITTEN_OFF = 'Written Off'

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

    # Currency display preference (e.g. "USD", "EUR").
    # Keep in sync with CURRENCY_SYMBOLS / DEFAULT_CURRENCY_CODE in utilities.py
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)

    shelves: Mapped[List["Shelf"]] = relationship("Shelf", back_populates="owner", cascade="all, delete-orphan", lazy=True)
    purchases: Mapped[List["Purchase"]] = relationship("Purchase", back_populates="owner", cascade="all, delete-orphan", lazy=True)
    items: Mapped[List["Item"]] = relationship("Item", back_populates="owner", cascade="all, delete-orphan", lazy=True)
    expenses: Mapped[List["Expense"]] = relationship("Expense", back_populates="owner", cascade="all, delete-orphan", lazy=True)

class HiddenSuggestion(db.Model):
    # A previously used value the user removed from a field's dropdown
    # (e.g. a misspelt brand). The records that use it keep it; it's only
    # left out of the suggestions until it's saved again.
    __tablename__ = 'hidden_suggestions'
    __table_args__ = (db.UniqueConstraint('user_id', 'field', 'value', name='uq_hidden_suggestion'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    field: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[str] = mapped_column(String(128), nullable=False)


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
    date: Mapped[Optional[datetime_date]] = mapped_column(nullable=True, default=None)
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
        # Includes returned sales: what was kept after the refund (usually 0 or negative)
        return sum((sale.net_proceeds for item in self.items for sale in item.sales), Decimal("0.00"))
    
    @property
    def has_assigned_prices(self) -> bool:
        # A bundle whose price has been split over its items: every item has a
        # price, and they add up to the purchase price. Anything else (a price
        # missing, the purchase price edited, an item added) leaves the cost
        # with the bundle as a whole.
        if self.purchase_type != PurchaseType.BUNDLE or not self.items:
            return False
        prices = [item.assigned_price for item in self.items]
        return None not in prices and sum(prices, Decimal("0.00")) == self.purchase_price

    @property
    def assigned_total(self) -> Decimal:
        return sum((item.assigned_price for item in self.items if item.assigned_price is not None), Decimal("0.00"))

    def item_costs(self) -> dict:
        # Each item's cost in a bundle with assigned prices: its price plus a
        # share of the shipping, in proportion to its price (or to its units
        # when every price is 0). The last item takes the rounding, so the
        # costs always add up to the bundle's total cost.
        shipping = self.shipping_cost or Decimal("0.00")
        price_total = sum((item.assigned_price for item in self.items), Decimal("0.00"))
        units = sum(item.quantity for item in self.items)
        costs = {}
        shipping_left = shipping
        for index, item in enumerate(self.items):
            if index == len(self.items) - 1:
                share = shipping_left
            elif price_total > 0:
                share = round(shipping * item.assigned_price / price_total, 2)
            else:
                share = round(shipping * item.quantity / units, 2)
            shipping_left -= share
            costs[item] = round(item.assigned_price + share, 2)
        return costs

    @property
    def profit(self) -> Decimal:
        # A bundle has one purchase cost shared by all of its items, so its
        # profit must be calculated at purchase level rather than by adding
        # item profits (which have no cost of their own). Once its price has
        # been split over the items, it adds up item profits like a single.
        if self.purchase_type == PurchaseType.BUNDLE and not self.has_assigned_prices:
            return round(self.total_revenue - self.total_cost, 2)

        return sum(
            (item.realized_profit for item in self.items if item.realized_profit is not None),
            Decimal("0.00"),
        )

    @property
    def roi(self) -> Optional[Decimal]:
        if self.total_cost <= 0:
            return None
        return round((self.profit / self.total_cost) * 100, 1)

    @property
    def margin(self) -> Optional[Decimal]:
        if self.total_revenue <= 0:
            return None
        return round((self.profit / self.total_revenue) * 100, 1)
    
    @property
    def display_name(self) -> str:
        return self.name or self.seller or self.platform or _("Purchase - {date}", date=self.date or _("Unassigned date"))

class Item(db.Model):
    __tablename__ = "items"

    __table_args__ = (
        # Cant have negative items on a shelf
        CheckConstraint("quantity > 0", name="ck_items_quantity_positive"),

        # Sold and written-off units can't exceed the total quantity
        CheckConstraint(
            "quantity_sold >= 0 AND quantity_written_off >= 0 "
            "AND quantity_sold + quantity_written_off <= quantity",
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
    quantity_written_off: Mapped[int] = mapped_column(nullable=False, default=0)
    category: Mapped[Optional[str]] = mapped_column(String(64))
    condition: Mapped[Optional[str]] = mapped_column(String(32))
    brand: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[ItemStatus] = mapped_column(
        SQLEnum(ItemStatus, values_callable=lambda statuses: [status.value for status in statuses]),
        default=ItemStatus.ON_SALE,
    )
    notes: Mapped[Optional[str]] = mapped_column(String(5120))
    # Bundles only: this line's share of the purchase price (all its units).
    # Used once every item in the bundle has one and they add up to the price.
    assigned_price: Mapped[Optional[Decimal]] = mapped_column(MONEY)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    owner: Mapped["User"] = relationship("User", back_populates="items")
    purchase: Mapped["Purchase"] = relationship("Purchase", back_populates="items")
    shelf: Mapped[Optional["Shelf"]] = relationship("Shelf", back_populates="items")

    listings: Mapped[List["Listing"]] = relationship("Listing", back_populates="item", cascade="all, delete-orphan", lazy=True)
    # Every sale ever recorded, including ones refunded with the item returned.
    # Use Item.kept_sales for the sales that currently hold units.
    sales: Mapped[List["Sale"]] = relationship("Sale", back_populates="item", cascade="all, delete-orphan", order_by="Sale.id")

    @property
    def kept_sales(self) -> List["Sale"]:
        # Sales that hold units. Sales whose item came back are only kept as history.
        return [sale for sale in self.sales if not sale.item_returned]

    @property
    def last_sale_date(self) -> Optional[datetime_date]:
        dates = [sale.sale_date for sale in self.kept_sales if sale.sale_date]
        return max(dates) if dates else None

    @property
    def kept_net_proceeds(self) -> Decimal:
        return sum((sale.net_proceeds for sale in self.kept_sales), Decimal("0.00"))

    # ROI and margin over all kept sales, so several sales read as one
    @property
    def kept_roi(self) -> Optional[Decimal]:
        costs = [sale.cost_basis for sale in self.kept_sales]
        profits = [sale.profit for sale in self.kept_sales]
        if not costs or None in costs or None in profits or sum(costs) <= 0:
            return None
        return round((sum(profits) / sum(costs)) * 100, 1)

    @property
    def kept_margin(self) -> Optional[Decimal]:
        gross = sum((sale.gross_proceeds for sale in self.kept_sales), Decimal("0.00"))
        profits = [sale.profit for sale in self.kept_sales]
        if gross <= 0 or None in profits:
            return None
        return round((sum(profits) / gross) * 100, 1)

    @property
    def returned_sales(self) -> List["Sale"]:
        return [sale for sale in self.sales if sale.item_returned]

    @property
    def is_written_off(self) -> bool:
        return self.quantity_written_off > 0

    @property
    def inventory_code(self) -> str | None:
        if self.id is None:
            return None
        return f"I-{self.id:06d}"

    @property
    def days_in_inventory(self) -> Optional[int]:
        if not self.purchase or self.purchase.date is None:
            return None
        end = self.last_sale_date or datetime_date.today()
        return (end - self.purchase.date).days

    @property
    def available_quantity(self) -> int:
        return max(self.quantity - self.quantity_sold - self.quantity_written_off, 0)

    @property
    def is_bundle(self) -> bool:
        return bool(self.purchase and self.purchase.purchase_type == PurchaseType.BUNDLE)

    @property
    def has_own_cost(self) -> bool:
        # False for items of a bundle whose price hasn't been split over its items
        return not self.is_bundle or self.purchase.has_assigned_prices

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
        if self.is_bundle:
            # Bundle cost belongs to the Purchase as a whole, unless its
            # price has been split over the items
            if not self.purchase.has_assigned_prices:
                return None
            return self.purchase.item_costs()[self]
        return round(self.purchase.total_cost, 2)

    @property
    def purchase_cost(self) -> Optional[Decimal]:
        """The item's total cost, when it has an unambiguous item cost."""
        return self.total_cost_basis

    @property
    def write_off_loss(self) -> Optional[Decimal]:
        # Cost of the written-off units. None for bundle items without an
        # assigned price, whose bundle profit already subtracts the whole cost.
        if not self.is_written_off:
            return Decimal("0.00")
        return self.cost_for_quantity(self.quantity_written_off)

    @property
    def realized_profit(self) -> Optional[Decimal]:
        # Profit of every sale (returned ones included) minus write-off losses.
        # None when nothing has happened yet or the cost isn't known per item.
        if not self.has_own_cost or (not self.sales and not self.is_written_off):
            return None
        profits = [sale.profit for sale in self.sales]
        if None in profits or self.write_off_loss is None:
            return None
        return round(sum(profits, Decimal("0.00")) - self.write_off_loss, 2)

    def cost_for_quantity(self, quantity: int) -> Optional[Decimal]:
        if self.unit_cost is None or quantity < 0 or quantity > self.quantity:
            return None
        if quantity == self.quantity:
            return self.total_cost_basis
        return round(self.unit_cost * quantity, 2)

class Sale(db.Model):
    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    listing_id: Mapped[Optional[int]] = mapped_column(ForeignKey("listings.id"))

    # Left empty when the sale date is unknown (e.g. a CSV row without "Sold date")
    sale_date: Mapped[Optional[datetime_date]] = mapped_column()
    sale_price: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    shipping_collected: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    shipping_paid: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    platform_fee: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    payment_fee: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.00"))
    quantity: Mapped[int] = mapped_column(nullable=False, default=1)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    # Refund given to the buyer. When the item came back it returns to stock,
    # and this sale only keeps whatever money was lost (fees, shipping).
    refund_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0.00"))
    item_returned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    item: Mapped["Item"] = relationship("Item", back_populates="sales")
    listing: Mapped[Optional["Listing"]] = relationship("Listing", back_populates="sales")

    @property
    def unit_sale_price(self):
        if not self.quantity:
            return Decimal("0.00")
        return round((self.sale_price or Decimal("0.00")) / self.quantity, 2)

    @property
    def gross_proceeds(self) -> Decimal:
        return round((self.sale_price or Decimal("0.00")) + (self.shipping_collected or Decimal("0.00")), 2)

    @property
    def is_refunded(self) -> bool:
        return bool(self.refund_amount) or self.item_returned

    @property
    def net_proceeds(self) -> Decimal:
        return round(
            self.gross_proceeds
            - (self.refund_amount or Decimal("0.00"))
            - (self.shipping_paid or Decimal("0.00"))
            - (self.platform_fee or Decimal("0.00"))
            - (self.payment_fee or Decimal("0.00")),
            2,
        )

    @property
    def cost_basis(self) -> Optional[Decimal]:
        # A returned item went back into stock, so this sale used none of its cost
        if self.item_returned:
            return Decimal("0.00")
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
    listing_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, default=None)
    listing_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, default=None)
    listing_price: Mapped[Optional[Decimal]] = mapped_column(MONEY, default=None)
    date_listed: Mapped[datetime_date] = mapped_column(default=datetime_date.today)
    # Persist the human-readable enum values (Active, Sold, ...) so they
    # match the existing database rows and the values used by the forms.
    status: Mapped[ListingStatus] = mapped_column(
        SQLEnum(ListingStatus, values_callable=lambda statuses: [status.value for status in statuses]),
        default=ListingStatus.ACTIVE,
    )

    item: Mapped["Item"] = relationship("Item", back_populates="listings")
    # A listing for several units can be linked to more than one sale
    sales: Mapped[List["Sale"]] = relationship("Sale", back_populates="listing")


# Running costs that belong to no single item: packaging, tape, subscriptions,
# storage... Like a bundle's price, they aren't split over items (any split
# would be made up), so they only come off the total profit.
class Expense(db.Model):
    __tablename__ = "expenses"

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_expenses_amount_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    # Always dated, so every expense falls in a month on the dashboard charts
    date: Mapped[datetime_date] = mapped_column(nullable=False, default=datetime_date.today)
    description: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(64))
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    owner: Mapped["User"] = relationship("User", back_populates="expenses")
