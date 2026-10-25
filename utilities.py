import csv
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from flask_login import LoginManager, current_user
from io import StringIO

from models import db, Purchase, Item, Sale, Shelf, Listing, PurchaseType, ItemStatus, ListingStatus
from translations import _

# Login Manager
# https://flask-login.readthedocs.io/en/latest/
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to continue.'
login_manager.login_message_category = 'warning'


# Currency display preference. Cosmetic only.
# Keep the symbols synced with the options in templates/user.html.
CURRENCY_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
    "CNY": "CN¥",
    "CAD": "C$",
    "HKD": "HK$",
    "AUD": "A$",
    "SGD": "S$",
    "CHF": "CHF",
}
DEFAULT_CURRENCY_CODE = "EUR" # Because I'm European :)

def currency_display():
    # Resolve the cosmetic currency sign from the signed-in user's preference.
    # Unknown or missing values fall back to EUR.
    code = DEFAULT_CURRENCY_CODE
    if current_user.is_authenticated and current_user.currency:
        code = current_user.currency
    if code not in CURRENCY_SYMBOLS:
        code = DEFAULT_CURRENCY_CODE
    return CURRENCY_SYMBOLS[code], code


# Proccess and format dates
def parse_date(value, default=None):
    if value is None or str(value).strip() == "":
        return default if default is not None else date.today()
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return default if default is not None else date.today()

# Process currency values without introducing binary floating-point rounding errors.
def parse_decimal(value, default=Decimal("0.00")):
    if value is None or value == '':
        return default
    try:
        parsed = Decimal(str(value))
        return parsed if parsed.is_finite() else default
    except (InvalidOperation, TypeError, ValueError):
        return default

# Convert a form's input of 'quantity' into a valid entry
def parse_quantity(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        quantity = int(str(value).strip())
    except (TypeError, ValueError):
        return None

    return quantity if quantity > 0 else None


#####################
# Handle CSV files
######################

def parse_csv_money(money):
    # Basically the utility of parse_decimal but for handling money from csv file
    if money is None:
        return None

    clean_money = str(money).strip()
    # Remove symbols and spaces
    clean_money = clean_money.replace("€", "").replace("\xa0", "").strip()

    if not clean_money:
        return None

    # Handle commas / dots
    try:
        if "," in clean_money and "." in clean_money:
            clean_money = clean_money.replace(".", "").replace(",", ".")
        elif "," in clean_money:
            clean_money = clean_money.replace(",", ".")

        parsed = Decimal(clean_money)
        return parsed.quantize(Decimal("0.01")) if parsed.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None

# Parse dates from csv in YYYY-MM-DD format
def parse_csv_date(value):
    if value is None or str(value).strip() == "":
        return None

    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None

# Handle quantity from csv file
def parse_non_negative_quantity(value):
    if value is None or str(value).strip() == "":
        return None

    try:
        quantity = int(str(value).strip())
    except (TypeError, ValueError):
        return None

    return quantity if quantity >= 0 else None

# Functions created for process_csv but placed outside because could be useful later
def get_row_clean(row, name):
    return str(row.get(name) or '').strip()

def normalise_name(value):
    return " ".join(str(value).strip().casefold().split())


##############################################################################
# Process and save csv files
# Currently this only works with my own Google Sheet table's layout
# This sheet contains two tables, one for items and another for bundle info
##############################################################################
def process_csv(file, user_id):
    # Decode into text
    stream = StringIO(file.read().decode('utf-8-sig'))
    reader = csv.DictReader(stream)
    rows = list(reader)

    errors = [] # Store any errors when processing each row
    purchases_created = 0
    items_created = 0
    shelves_created = 0

    # bundles_dict stores bundle metadata. purchases_by_bundle stores the actual
    # SQLAlchemy Purchase object, so all item rows can point to the same purchase.
    bundles_dict = {}
    purchases_by_bundle = {}
    bundle_costs_by_name = {}
    item_status_lookup = {
        status.value.casefold(): status for status in ItemStatus
    }

    # store Shelf objects with normalised name.
    shelves = {
        normalise_name(shelf.name): shelf
        for shelf in Shelf.query.filter_by(user_id=user_id).all()
    }

    def has_extra_columns(row):
        return bool(row.get(None))


    # Gather bundles on the Bundles table.
    for row_number, row in enumerate(rows, start=2):
        bundle_name = get_row_clean(row, 'Bundle Name')
        if not bundle_name:
            continue

        if has_extra_columns(row):
            errors.append(_("Row {row}: extra values found after the CSV headers.", row=row_number))
            continue

        bundle_cost = parse_csv_money(row.get("Bundle Cost"))
        if bundle_cost is None:
            errors.append(_("Row {row}: invalid or missing Bundle Cost.", row=row_number))
            continue

        bundle_name_key = normalise_name(bundle_name)
        bundle_key = (bundle_name_key, bundle_cost)
        bundles_dict[bundle_key] = {"name": bundle_name, "cost": bundle_cost}
        bundle_costs_by_name.setdefault(bundle_name_key, set()).add(bundle_cost)

    # Gather items from the Items table.
    for row_number, row in enumerate(rows, start=2):
        bundle_name = get_row_clean(row, 'Bundle')
        item_name = get_row_clean(row, 'Item')

        # Rows belonging only to the bundle table do not create Item records.
        if not item_name:
            continue

        if has_extra_columns(row):
            errors.append(_("Row {row}: extra values found after the CSV headers.", row=row_number))
            continue

        raw_quantity = row.get('Quantity')
        if raw_quantity is None or str(raw_quantity).strip() == "":
            item_quantity = 1
        else:
            item_quantity = parse_quantity(raw_quantity)
            if item_quantity is None:
                errors.append(_("Row {row}: Quantity must be a positive whole number.", row=row_number))
                continue

        raw_quantity_sold = row.get('Sold Quantity')
        if raw_quantity_sold is None or str(raw_quantity_sold).strip() == "":
            item_quantity_sold = 0
        else:
            item_quantity_sold = parse_non_negative_quantity(raw_quantity_sold)
            if item_quantity_sold is None:
                errors.append(_("Row {row}: Sold Quantity must be a non-negative whole number.", row=row_number))
                continue

        if item_quantity_sold > item_quantity:
            errors.append(_("Row {row}: Sold Quantity cannot exceed Quantity.", row=row_number))
            continue

        raw_status = get_row_clean(row, 'Status')
        item_status = item_status_lookup.get(raw_status.casefold())
        if item_status is None:
            errors.append(_("Row {row}: invalid ItemStatus '{status}'.", row=row_number, status=raw_status))
            continue

        # Blank date remains unassigned
        raw_purchase_date = get_row_clean(row, "Bought date")
        purchase_date = parse_csv_date(raw_purchase_date)
        if raw_purchase_date and purchase_date is None:
            errors.append(_("Row {row}: Invalid purchase date.", row=row_number))
            continue

        raw_sale_date = get_row_clean(row, "Sold date")
        sale_date = parse_csv_date(raw_sale_date)
        if raw_sale_date and sale_date is None:
            errors.append(_("Row {row}: Invalid sale date.", row=row_number))
            continue

        raw_refund_amount = get_row_clean(row, "Refund amount")
        refund_amount = parse_csv_money(raw_refund_amount) if raw_refund_amount else Decimal("0.00")
        if refund_amount is None:
            errors.append(_("Row {row}: Invalid refund amount.", row=row_number))
            continue

        sale_price = parse_csv_money(row.get('Sold price'))
        if item_quantity_sold > 0:
            if sale_price is None:
                errors.append(_("Row {row}: Sold price is required when quantity is sold.", row=row_number))
                continue

        listing_price_total = parse_csv_money(row.get('Sell price (total)'))



        purchase_type = (
            PurchaseType.SINGLE
            if normalise_name(bundle_name) == 'individual'
            else PurchaseType.BUNDLE
        )

        # Record purchase
        if purchase_type is PurchaseType.SINGLE:
            # csv column stores unit price, while Purchase.purchase_price stores the total cost of the purchase.
            item_purchase_price = parse_csv_money(row.get('Buy price (unit)'))
            if item_purchase_price is None:
                errors.append(_("Row {row}: invalid or missing Buy price (unit).", row=row_number))
                continue

            purchase = Purchase(
                user_id=user_id,
                name=item_name,
                seller=None,
                # platform=   CSV currently doesnt have purchase origin
                date=purchase_date,
                purchase_type=PurchaseType.SINGLE,
                purchase_price=item_purchase_price * item_quantity,
            )
            db.session.add(purchase)
            purchases_created += 1
        else:
            if not bundle_name:
                errors.append(_("Row {row}: Bundle is required for a non-Individual item.", row=row_number))
                continue

            bundle_name_key = normalise_name(bundle_name)
            bundle_costs = bundle_costs_by_name.get(bundle_name_key, set())
            if not bundle_costs:
                errors.append(_("Row {row}: no bundle entry found for '{name}'.", row=row_number, name=bundle_name))
                continue
            if len(bundle_costs) > 1:
                errors.append(_("Row {row}: '{name}' has multiple bundle costs, so this item row is ambiguous.", row=row_number, name=bundle_name))
                continue

            bundle_cost = next(iter(bundle_costs))
            bundle_key = (bundle_name_key, bundle_cost)
            purchase = purchases_by_bundle.get(bundle_key)

            if purchase is None:
                bundle = bundles_dict[bundle_key]
                purchase = Purchase(
                    user_id=user_id,
                    name=bundle["name"],
                    seller=None,
                    # platform=   CSV currently doesnt have purchase origin
                    date=purchase_date,
                    purchase_type=PurchaseType.BUNDLE,
                    purchase_price=bundle["cost"],
                )
                db.session.add(purchase)
                purchases_by_bundle[bundle_key] = purchase
                purchases_created += 1


        # Shelf
        shelf = None
        shelf_name = get_row_clean(row, 'Location')
        if shelf_name:
            shelf_key = normalise_name(shelf_name)
            shelf = shelves.get(shelf_key)
            if shelf is None:   # Continues if shelf has not been seen yet
                shelf = Shelf(user_id=user_id, name=shelf_name)
                db.session.add(shelf)
                shelves[shelf_key] = shelf
                shelves_created += 1

        item = Item(
            user_id=user_id,
            purchase=purchase,
            shelf=shelf,
            name=item_name,
            quantity=item_quantity,
            quantity_sold=item_quantity_sold,
            # A written-off item loses all of its unsold units
            # Could expand this later too be able to discriminate how many were refunded
            quantity_written_off=(
                item_quantity - item_quantity_sold
                if item_status == ItemStatus.WRITTEN_OFF
                else 0
            ),
            status=item_status,
            notes=get_row_clean(row, 'Notes') or None,
        )

        # Record listing
        listing = None
        listing_url = get_row_clean(row, 'URL')

        if listing_url:

            sale_platform = get_row_clean(row, 'Sales platform')
            if not sale_platform:
                errors.append(_("Row {row}: Sales platform is required for a Listing.", row=row_number))
                continue

            listing = Listing(
                platform = sale_platform,
                listing_url = listing_url,
                listing_price = listing_price_total,
                date_listed = purchase_date or date.today(),
                status = (
                    # ADD: support for ListingStatus REMOVED and EXPIRED
                    ListingStatus.SOLD
                    if item_quantity_sold == item_quantity
                    else ListingStatus.ACTIVE
                ),
                item = item,
            )

        # Record sale
        if item_quantity_sold > 0:
            sale = Sale(
                sale_date=sale_date,
                sale_price=sale_price,
                quantity=item_quantity_sold,
                refund_amount=(
                    (refund_amount if raw_refund_amount else sale_price)
                    if item_status == ItemStatus.WRITTEN_OFF
                    else Decimal("0.00")
                ),
                item = item,
                listing = listing,
            )

        db.session.add(item)
        if listing is not None:
            db.session.add(listing)
        if item_quantity_sold > 0:
            db.session.add(sale)

        items_created += 1

    # https://stackoverflow.com/a/56305023
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return {
        "purchases_created": purchases_created,
        "items_created": items_created,
        "shelves_created": shelves_created,
        "errors": errors,
    }
