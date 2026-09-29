import csv
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from flask_login import LoginManager, current_user
from io import StringIO
from datetime import date as datetime_date, datetime

from models import Purchase, Item, PurchaseType, ItemStatus

# Login Manager
# https://flask-login.readthedocs.io/en/latest/
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to continue.'
login_manager.login_message_category = 'warning'


# Proccess dates
def parse_date(value, default=None):
    if not value:
        return default or date.today()
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return default or date.today()

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
    # Basically parse_decimal but for handling money from csv file
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

        return Decimal(clean_money).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


################################ CHECK IF PARSE_CSV_MONEY IS NEEDED OR I CAN JUST USE PARSE DECIMAl

# Process and save csv files
# Currently this only works with my own Google Sheet table
# This sheet contains two tables, one for items and another for bundle info
def process_csv(file, user_id):

    # Decode into text
    stream = StringIO(file.read().decode('utf-8-sig')) 
    reader = csv.DictReader(stream) # Could instead use TextIOWrapper? Need to search which would be better
    rows = list(reader)

    rows_iterated = 0
    bundles_dict = {}
    purchases_by_bundle = {} # Stores all the purchases 
    item_status_lookup = { status.value.casefold(): status for status in ItemStatus } # Store all ItemStatus options

    # Catalogue every bundle on the table
    for row in rows:

        bundle_name = row.get('Bundle Name', '').strip()
        bundle_cost = parse_csv_money(row.get("Bundle Cost"))

        # Skip rows without bundle
        if not row.get('Bundle Name'):
            continue

        # Skip rows without title
        if row.get(None):
            print(f'ERROR: ROW IS None in row {rows_iterated}')
            #### RECORD AN ERROR
            continue

        # Make it so Bundles are identified by having the same name and cost
        if bundle_name in bundles_dict:
            if bundles_dict[bundle_name] != bundle_cost:
                print(f'ERROR: BUNDLE NAME NOT MATCH BUNDLE COST in row {rows_iterated}')
                # IMPLEMENT ERROR
                continue
        else:
            bundles_dict[bundle_name] = bundle_cost 

    # Catalogue items
    for row in rows:

        # Grab data from columns
        bundle_name = (row.get('Bundle') or '').strip()
        item_name = (row.get('Item') or '').strip()

        item_quantity = parse_quantity(row.get('Quantity'))
        if item_quantity is None:
            item_quantity = 1 #Default to 1

        item_quantity_sold = parse_quantity(row.get('Sold Quantity'))
        if item_quantity_sold is None:
            item_quantity_sold = 0 # Default to 0

        if item_quantity_sold > item_quantity:    # Check if quantity values make sense
            print(f'ERROR: QUANTITY MISMATCH in row {rows_iterated}')
            # report an error
            continue

        # Skip rows without an item
        if not item_name:
            print(f'ERROR: ROW WITHOUT ITEM NAME in row {rows_iterated}')
            continue

        # Skip rows without title
        if row.get(None):
            print(f'ERROR: ROW WITHOUT TITLE in row {rows_iterated}')
            continue

        raw_status = (row.get("Status") or "").strip()
        item_status = item_status_lookup.get(raw_status.casefold())

        if item_status is None:
            print(f"ERROR: Invalid ItemStatus {raw_status} {item_status}")




        # I need to group all the items based on its box.
        # Check if box already exists (name? possibly also cost)

        purchase_type = (
            PurchaseType.SINGLE if bundle_name == 'Individual'
            else PurchaseType.BUNDLE
        )

        purchase_name = (
            bundle_name if purchase_type is PurchaseType.BUNDLE
            else None
        )

        purchase_price = parse_csv_money(row.get('Buy price (unit)'))
        if purchase_price is None:
            print(f"ERROR: Invalid purchase price ({purchase_price}) in row {rows_iterated}")

        # ADD PURCHASES
        if purchase_type is PurchaseType.SINGLE:
            purchase = Purchase(
                user_id = user_id,
                name = purchase_name,
                seller = None, # My current CSV doesn't have a column for seller
                platform = 'Vinted', # CHANGE LATER. Currently my CSV only has 'Vinted', and is somewhat mixed with Status

                # date = datetime_date.fromisoformat(raw_purchase_date) if raw_purchase_date else None,

                purchase_type = PurchaseType.SINGLE,
                purchase_price = purchase_price
                # No shipping cost currently in CSV file
            )
            #### db.session.add(purchase)

        
        else: # If type is Bundle
            bundle_cost = bundles_dict.get(bundle_name)
            if bundle_cost is None:
                print(f'ERROR 1: bundle_cost is None in row {rows_iterated}')
                # REPORT ERROR
                continue

            purchase = purchases_by_bundle.get(bundle_name)
            if purchase is None:
                bundle_cost = bundles_dict.get(bundle_name)

                if bundle_cost is None:
                    print(f'ERROR 2: bundle_cost is None in row {rows_iterated}')
                    # REPORT ERROR
                    continue

                purchase = Purchase(
                    user_id = user_id,
                    name = bundle_name,
                    purchase_type = PurchaseType.BUNDLE,
                    purchase_price = bundle_cost
            )
            #### db.session.add(purchase)
            purchases_by_bundle[bundle_name] = purchase

        
        # ADD ITEMS
        item = Item(
            user_id = user_id,
            purchase = purchase,
            name = item_name,
            quantity = item_quantity,
            quantity_sold = item_quantity_sold,
            status = item_status,
            notes = (row.get("Notes") or "").strip()
        )
        #### db.session.add(item)


        # print(bundles_dict, "XXXXXXXXXXXXXXXXXXXXXXXXX", bundle_name)

        #print({
        #    column.name: getattr(new_purchase, column.name)
        #    for column in new_purchase.__table__.columns
        #})

        rows_iterated += 1

    # Instead of db.session.add():
    # Possibly use SQLAlchemy's faster batch method: db.session.bulk_insert_mappings(Product, list_of_dicts).