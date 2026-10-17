import os, csv
from datetime import datetime, date, timedelta
from urllib.parse import urlparse

# Imports from local python files
from models import db, User, Shelf, Item, Purchase, ItemStatus, PurchaseType, Listing, ListingStatus, Sale
from utilities import login_manager, parse_date, parse_decimal, parse_quantity, process_csv, currency_display, CURRENCY_SYMBOLS

from flask import Flask, Response, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import or_, cast, String
from werkzeug.security import generate_password_hash, check_password_hash

from decimal import Decimal

from io import StringIO


# Configure App and Database (https://www.geeksforgeeks.org/python/declaring-models-in-flask/)
app = Flask(__name__)

# https://flask-sqlalchemy.readthedocs.io/en/stable/config/
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, 'instance', 'database.db')
os.makedirs(os.path.join(BASE_DIR, 'instance'), exist_ok=True)

# App configs
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ECHO'] = False # Set to 'True' for debugging SQL queries
app.secret_key = '4815_THISisCS50_162342'

# Login Manager
# https://flask-login.readthedocs.io/en/latest/
login_manager.init_app(app)

@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return db.session.get(User, user_id)

# Bind db object to this app instance
db.init_app(app)


###################
# FUTURE FEATURES:
# Translate (at least English & Portuguese)
##########################


##########################
#       FUNCTIONS
##########################

# Create test account for debugging
def create_admin_account():
    if not User.query.filter_by(username='admin').first():
        user = User(username='admin', password_hash=generate_password_hash('123'))
        db.session.add(user)
        db.session.commit()

# Create the physical database files
def create_database():
    with app.app_context():
        db.create_all()
        create_admin_account()


create_database()

# Delete and recreate the database
def reset_database():
    db.session.remove()

    # Fixes file being locked, preventing deletion
    if hasattr(db, 'engine'):
        db.engine.dispose()

    for file in (DB_PATH, os.path.join(BASE_DIR, 'database.db')):
        if os.path.exists(file):
            try:
                # Try to grant read/write permission
                os.chmod(file, 0o666)
            except OSError:
                pass
            try:
                os.remove(file)
            except OSError:
                pass

    create_database()

    print(f"Database reset at {DB_PATH}")

# Helper functions
##########################

def get_used_values(model, column_name, user_id):
    items = model.query.filter_by(user_id=user_id).all()
    values = {getattr(item, column_name) for item in items if getattr(item, column_name)}
    return sorted(set(values))


def get_item_form_options(user_id):
    return {
        'used_categories': get_used_values(Item, 'category', user_id),
        'used_brands': get_used_values(Item, 'brand', user_id),
    }


def get_purchase_form_options(user_id):
    options = get_item_form_options(user_id)

    options.update({
        'used_sellers': get_used_values(Purchase, 'seller', user_id),
        'used_platforms': get_used_values(Purchase, 'platform', user_id),
    })
    
    return options


def create_purchase_item(purchase, user_id, name, category=None, brand=None, condition=None, 
                         shelf_id=None, notes=None, quantity=1):
    # Return new Item instance with sanitized inputs
    return Item(
        user_id=user_id,
        purchase_id=purchase.id,
        shelf_id=int(shelf_id) if shelf_id else None,
        name=name.strip(),
        quantity=quantity,
        quantity_sold=0,
        category=category.strip() or None if category else None,
        condition=condition.strip() or None if condition else None,
        brand=brand.strip() or None if brand else None,
        status=ItemStatus.IN_STORAGE,
        notes=notes.strip() or None if notes else None,
    )


def refresh_item_status(item):
    # Keep the item status consistent with its sold, written-off and remaining quantity
    if item.quantity_sold + item.quantity_written_off > item.quantity:
        item.quantity_sold = max(item.quantity - item.quantity_written_off, 0)
    if item.available_quantity == 0:
        item.status = ItemStatus.WRITTEN_OFF if item.is_written_off else ItemStatus.SOLD
    elif item.status in (ItemStatus.SOLD, ItemStatus.WRITTEN_OFF):
        has_active_listing = any(l.status == ListingStatus.ACTIVE for l in item.listings)
        item.status = ItemStatus.ON_SALE if has_active_listing else ItemStatus.IN_STORAGE

@app.context_processor
def inject_today():
    return {"today": date.today().isoformat()}

@app.context_processor
def inject_currency():
    # Every template renders money signs via {{ currency_symbol }}, so
    # user-entered text (item names, bundle names, ...) is never rewritten.
    symbol, code = currency_display()
    return {"currency_symbol": symbol, "currency_code": code}


##########################
#        ROUTES
##########################

@app.route('/')
@login_required
def index():
    items = Item.query.filter_by(user_id=current_user.id).all()
    purchases = Purchase.query.filter_by(user_id=current_user.id).all()
    sales = (
        Sale.query.join(Item)
        .filter(Item.user_id == current_user.id)
        .all()
    )
    listings = (
        Listing.query.join(Item)
        .filter(Item.user_id == current_user.id)
        .all()
    )

    total_units = sum(item.quantity for item in items)
    available_units = sum(item.available_quantity for item in items)
    sold_units = sum(item.quantity_sold for item in items)
    total_spend = sum((purchase.total_cost for purchase in purchases), Decimal("0.00"))
    total_revenue = sum((purchase.total_revenue for purchase in purchases), Decimal("0.00"))
    total_profit = sum((purchase.profit for purchase in purchases), Decimal("0.00"))
    written_off_items = [item for item in items if item.is_written_off]
    write_off_units = sum(item.quantity_written_off for item in written_off_items)
    # Bundle items have no item cost; their loss is already in the bundle profit
    write_off_loss = sum(
        (item.write_off_loss for item in written_off_items if item.write_off_loss is not None),
        Decimal("0.00"),
    )
    kept_sales = [sale for sale in sales if not sale.item_returned]
    sell_through_rate = (
        round((sold_units / total_units) * 100, 1)
        if total_units
        else Decimal("0.0")
    )
    average_sale_value = (
        round(sum((sale.net_proceeds for sale in kept_sales), Decimal("0.00")) / len(kept_sales), 2)
        if kept_sales
        else Decimal("0.00")
    )

    listings_by_item = {}
    for listing in listings:
        listings_by_item.setdefault(listing.item_id, []).append(listing)

    items_without_active_listing = [
        item for item in items
        if item.available_quantity > 0
        and not any(
            listing.status == ListingStatus.ACTIVE
            for listing in listings_by_item.get(item.id, [])
        )
    ]
    attention_items = sorted(
        items_without_active_listing,
        key=lambda item: item.created_at or datetime.min,
        reverse=True,
    )[:6]

    status_summary = [
        (status, sum(item.quantity for item in items if item.status == status))
        for status in ItemStatus
    ]

    recent_sales = sorted(
        sales,
        key=lambda sale: (sale.sale_date or date.min, sale.id or 0),
        reverse=True,
    )[:6]
    top_purchases = sorted(
        purchases,
        key=lambda purchase: purchase.profit,
        reverse=True,
    )[:5]

    # Profit from sales in the last 30 days
    month_ago = date.today() - timedelta(days=30)
    last_month_profit = Decimal("0.00")
    for sale in sales:
        if sale.sale_date and sale.sale_date >= month_ago and sale.profit is not None:
            last_month_profit += sale.profit

    # Profit per month for the chart (the user picks how many months, 0 = all)
    months = request.args.get("months", 6, type=int)
    if months not in (0, 3, 6, 12):
        months = 6

    # "All" spans from the month of the first sale up to the current month
    month_count = months
    if months == 0:
        sale_dates = [sale.sale_date for sale in sales if sale.sale_date]
        first = min(sale_dates) if sale_dates else date.today()
        month_count = (date.today().year - first.year) * 12 + date.today().month - first.month + 1

    # Build the list of month labels, oldest first, e.g. ["2026-05", "2026-06", ...]
    year = date.today().year
    month = date.today().month
    chart_labels = []
    for i in range(month_count):
        chart_labels.insert(0, f"{year}-{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1

    # Add up the profit of each sale into its month
    monthly_profit = {label: 0 for label in chart_labels}
    for sale in sales:
        if sale.sale_date and sale.profit is not None:
            label = sale.sale_date.strftime("%Y-%m")
            if label in monthly_profit:
                monthly_profit[label] += float(sale.profit)
    chart_values = [round(monthly_profit[label], 2) for label in chart_labels]

    return render_template(
        'index.html',
        last_month_profit=round(last_month_profit, 2),
        months=months,
        chart_labels=chart_labels,
        chart_values=chart_values,
        total_units=total_units,
        available_units=available_units,
        sold_units=sold_units,
        purchase_count=len(purchases),
        sales_count=len(kept_sales),
        write_off_count=len(written_off_items),
        write_off_units=write_off_units,
        write_off_loss=round(write_off_loss, 2),
        total_spend=round(total_spend, 2),
        total_revenue=round(total_revenue, 2),
        total_profit=round(total_profit, 2),
        active_listing_count=sum(
            listing.status == ListingStatus.ACTIVE for listing in listings
        ),
        listing_count=len(listings),
        sell_through_rate=sell_through_rate,
        average_sale_value=average_sale_value,
        status_summary=status_summary,
        recent_sales=recent_sales,
        top_purchases=top_purchases,
        attention_items=attention_items,
        attention_count=len(items_without_active_listing),
    )

#########################
#       Inventory

@app.route('/inventory', methods=['GET', 'POST'])
@login_required
def inventory():
    query = Item.query.filter_by(user_id=current_user.id)
    q = request.args.get('q', '').strip()
    if q:
        query = query.outerjoin(Listing).filter(
            or_(
                Item.name.ilike(f'%{q}%'),
                cast(Item.id, String).ilike(f'%{q}%'),
                Item.category.ilike(f'%{q}%'),
                Listing.listing_id.ilike(f'%{q}%'),
            )
        ).distinct()

    status = request.args.get('status')
    if status:
        try:
            status_enum = ItemStatus(status)
        except ValueError:
            status_enum = None
            flash('Status returned None', 'danger')

        print(f'status_enum is {status_enum}')
        if status_enum is not None:
            query = query.filter(Item.status == status_enum)
            print(f'QUERY: {query}')

    shelf_id = request.args.get("shelf_id")
    if shelf_id:
        query = query.filter(Item.shelf_id == int(shelf_id))

    category = request.args.get("category")
    if category:
        query = query.filter(Item.category == category)

    sort = request.args.get("sort", "newest")
    if sort == "oldest":
        query = query.order_by(Item.created_at.asc())
    else:
        query = query.order_by(Item.created_at.desc())

    results = query.all()

    if sort == "highest_profit":
        results.sort(
            key=lambda i: (
                i.realized_profit
                if i.realized_profit is not None
                else Decimal("-Infinity")
            ),
            reverse=True,
        )
    elif sort == "lowest_profit":
        results.sort(
            key=lambda i: (
                i.realized_profit
                if i.realized_profit is not None
                else Decimal("Infinity")
            )
        )

    shelves_list = Shelf.query.filter_by(user_id=current_user.id).order_by(Shelf.name).all()
    categories = sorted({i.category for i in Item.query.filter_by(user_id=current_user.id) if i.category})

    return render_template(
        "inventory/inventory.html",
        items=results,
        shelves=shelves_list,
        categories=categories,
        q=q,
        status=status,
        shelf_id=shelf_id,
        category=category,
        sort=sort,
    )


#    Inventory - Item

@app.route('/inventory/<int:item_id>')
@login_required
def view_item(item_id):

    item = Item.query.filter_by(id=item_id, user_id=current_user.id).first()
    if not item:
        flash('Invalid item', 'danger')
        return redirect("/inventory")
    
    shelves = Shelf.query.filter_by(user_id=current_user.id).order_by(Shelf.name).all()
    return render_template(
        "inventory/inventory_view.html",
        item=item,
        shelves=shelves,
        **get_item_form_options(current_user.id),
        ItemStatus=ItemStatus,
        ListingStatus=ListingStatus,
    )


@app.route("/items/<int:item_id>/edit", methods=["POST"])
@login_required
def edit_item(item_id):
    item = Item.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    item.name = request.form.get('name', item.name).strip()
    raw_quantity = request.form.get('quantity')
    quantity = item.quantity if raw_quantity is None else parse_quantity(raw_quantity)
    minimum_quantity = max(item.quantity_sold + item.quantity_written_off, 1)
    if quantity is None or quantity < minimum_quantity:
        flash(f'Quantity must be a whole number of at least {minimum_quantity}.', 'danger')
        return redirect(url_for('view_item', item_id=item.id))
    item.quantity = quantity
    item.category = request.form.get('category', '').strip() or None
    item.brand = request.form.get('brand', '').strip() or None
    item.condition = request.form.get('condition', '').strip() or None
    shelf_id = request.form.get('shelf_id')
    item.shelf_id = int(shelf_id) if shelf_id else None
    status = request.form.get('status')

    # Change item status. The field is absent when the status is automatic.
    if status is not None:
        try:
            new_status = ItemStatus(status)
        except ValueError:
            flash(f"Invalid status: {status!r}", "danger")
            return redirect(url_for('view_item', item_id=item.id))
        # Sold and Written Off only come from recording a sale or a write-off
        if new_status == ItemStatus.SOLD:
            flash('Items are marked Sold automatically when a sale is recorded.', 'warning')
            return redirect(url_for('view_item', item_id=item.id))
        if new_status == ItemStatus.WRITTEN_OFF:
            flash('Use "Write off" on the item to record it as a loss.', 'warning')
            return redirect(url_for('view_item', item_id=item.id))
        item.status = new_status

    item.notes = request.form.get('notes', '').strip()
    refresh_item_status(item)
    db.session.commit()
    flash('Item updated.', 'success')
    return redirect(url_for('view_item', item_id=item.id))


@app.route('/items/<int:item_id>/delete', methods=["POST"])
@login_required
def delete_item(item_id):
    item = Item.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()

    # Convert purchase type to Single if needed
    purchase = item.purchase
    if (purchase and purchase.purchase_type == PurchaseType.BUNDLE and len(purchase.items) == 2):
        purchase.purchase_type = PurchaseType.SINGLE

    db.session.delete(item)
    db.session.commit()
    flash("Item deleted.", "success")

    # Redirect to current page
    referrer = request.referrer
    if referrer:
        parsed_referrer = urlparse(referrer)
        if parsed_referrer.netloc in ("", request.host):
            return redirect(referrer)

    # Fallback
    return redirect(url_for("inventory"))


#########################
#       Purchases

@app.route('/purchases', methods=['GET', 'POST'])
@login_required
def purchases():
    query = Purchase.query.filter_by(user_id=current_user.id)
    q = request.args.get('q', '').strip()
    if q:
        query = query.outerjoin(Item).filter(or_(
            cast(Purchase.id, String).ilike(f'%{q}%'),
            Purchase.name.ilike(f'%{q}%'),
            Purchase.seller.ilike(f'%{q}%'),
            Purchase.platform.ilike(f'%{q}%'),
            Item.name.ilike(f'%{q}%'),
        )).distinct()

    purchase_type = request.args.get('purchase_type', '')
    if purchase_type:
        try:
            query = query.filter(Purchase.purchase_type == PurchaseType(purchase_type))
        except ValueError:
            purchase_type = ''

    sort = request.args.get('sort', 'newest')
    if sort == 'oldest':
        purchases = query.order_by(Purchase.date.asc()).all()
    else:
        purchases = query.order_by(Purchase.date.desc()).all()

    if sort == 'highest_profit':
        purchases.sort(key=lambda p: p.profit, reverse=True)
    elif sort == 'lowest_profit':
        purchases.sort(key=lambda p: p.profit)

    return render_template(
        "purchases/purchases.html",
        purchases=purchases,
        q=q,
        purchase_type=purchase_type,
        sort=sort,
    )

@app.route("/purchases/new", methods=["GET", "POST"])
@login_required
def new_purchase():

    # Exported variables
    shelves = (
        Shelf.query.filter_by(user_id=current_user.id).order_by(Shelf.name.desc()).all()
    )
    purchase_type = request.args.get('purchase_type', 'single').lower()
    if purchase_type not in ('single', 'bundle'):
        purchase_type = 'single'

    form_options = get_purchase_form_options(current_user.id)

    if request.method == 'POST':

        # Validate the purchase type
        purchase_type_raw = request.form.get('purchase_type', '').strip()
        purchase_type = None
        # Loop through values to validate each
        for enum_value in PurchaseType:
            print(f'checking enum_value {enum_value}')
            if enum_value.value.lower() == purchase_type_raw.lower():
                purchase_type = enum_value
                print(f'purchase_type is {purchase_type}')
                break

        if purchase_type is None:
            flash('Invalid purchase type', 'danger')
            return 'Invalid purchase type submitted', 400

        purchase_type_label = purchase_type.value.lower()
        print(f'Purchase type is {purchase_type.value}')

        raw_purchase_date = request.form.get('date')
        purchase = Purchase(
            user_id = current_user.id,
            date = parse_date(raw_purchase_date) if raw_purchase_date else None,
            name = request.form.get('name', '').strip() or None,
            seller = request.form.get('seller', '').strip(),
            platform = request.form.get('platform', '').strip(),
            purchase_type = purchase_type,
            purchase_price = parse_decimal(request.form.get('purchase_price')),
            shipping_cost = parse_decimal(request.form.get('shipping_cost')),
            notes = request.form.get('purchaseNotes', '').strip(),
        )

        db.session.add(purchase)
        db.session.flush()

        # A single purchase may contain at most one item. A bundle may
        # contain any number of items, but there is no per-item allocation.
        checked_add_items = request.form.get('addItemsToggle') is not None
        if checked_add_items and purchase_type == PurchaseType.SINGLE:
            name = request.form.get('itemName', '').strip()
            if not name:
                db.session.rollback()
                flash('Item name is required.', 'danger')
                return render_template("purchases/purchases_new.html",
                                       shelves=shelves, purchase_type=purchase_type_label,
                                       **form_options)

            quantity = parse_quantity(request.form.get('itemQuantity'))
            if quantity is None:
                db.session.rollback()
                flash('Quantity must be a positive whole number.', 'danger')
                return render_template("purchases/purchases_new.html",
                                       shelves=shelves, purchase_type=purchase_type_label,
                                       **form_options)

            db.session.add(create_purchase_item(
                purchase, current_user.id, name,
                category=request.form.get('category'),
                brand=request.form.get('brand'),
                condition=request.form.get('condition'),
                shelf_id=request.form.get('shelf_id'),
                notes=request.form.get('itemNotes'),
                quantity=quantity,
            ))
            flash(f'{name} added to the purchase.', 'success')

        elif checked_add_items and purchase_type == PurchaseType.BUNDLE:
            names = request.form.getlist('itemName[]')
            categories = request.form.getlist('category[]')
            brands = request.form.getlist('brand[]')
            conditions = request.form.getlist('condition[]')
            shelves_for_items = request.form.getlist('shelf_id[]')
            notes = request.form.getlist('itemNotes[]')
            quantities = request.form.getlist('itemQuantity[]')

            valid_names = [name.strip() for name in names if name.strip()]
            if not valid_names:
                db.session.rollback()
                flash('Add at least one item to this bundle.', 'danger')
                return render_template("purchases/purchases_new.html",
                                       shelves=shelves, purchase_type=purchase_type_label,
                                       **form_options)

            parsed_quantities = {}
            for index, name in enumerate(names):
                if not name.strip():
                    continue
                quantity = parse_quantity(quantities[index] if index < len(quantities) else None)
                if quantity is None:
                    db.session.rollback()
                    flash('Every item quantity must be a positive whole number.', 'danger')
                    return render_template("purchases/purchases_new.html",
                                           shelves=shelves, purchase_type=purchase_type_label,
                                           **form_options)
                parsed_quantities[index] = quantity

            for index, name in enumerate(names):
                name = name.strip()
                if not name:
                    continue
                db.session.add(create_purchase_item(
                    purchase, current_user.id, name,
                    category=categories[index] if index < len(categories) else None,
                    brand=brands[index] if index < len(brands) else None,
                    condition=conditions[index] if index < len(conditions) else None,
                    shelf_id=shelves_for_items[index] if index < len(shelves_for_items) else None,
                    notes=notes[index] if index < len(notes) else None,
                    quantity=parsed_quantities[index],
                ))
            flash(f'{len(valid_names)} item(s) added to the purchase.', 'success')

        db.session.commit()
        return redirect(url_for('view_purchase', purchase_id=purchase.id))

    
    return render_template("purchases/purchases_new.html", shelves=shelves,
                           purchase_type=purchase_type_label if isinstance(purchase_type, PurchaseType) else purchase_type,
                           **form_options)

@app.route("/purchases/new/type")
@login_required
def choose_purchase_type():
    return render_template("purchases/purchases_type.html")


@app.route('/purchases/<int:purchase_id>')
@login_required
def view_purchase(purchase_id):
    purchase = Purchase.query.filter_by(id=purchase_id, user_id=current_user.id).first_or_404()

    # Convert purchase type to Single if needed
    if purchase.purchase_type == PurchaseType.BUNDLE and len(purchase.items) == 1:
        purchase.purchase_type = PurchaseType.SINGLE
        db.session.commit()

    return render_template(
        "purchases/purchases_view.html",
        purchase=purchase,
        **get_purchase_form_options(current_user.id),
    )


@app.route('/purchases/<int:purchase_id>/edit', methods=['POST'])
@login_required
def edit_purchase(purchase_id):
    purchase = Purchase.query.filter_by(
        id=purchase_id,
        user_id=current_user.id,
    ).first_or_404()

    raw_purchase_date = request.form.get('date')
    purchase.date = parse_date(raw_purchase_date) if raw_purchase_date else None
    purchase.name = request.form.get('name', '').strip() or None
    purchase.seller = request.form.get('seller', '').strip() or None
    purchase.platform = request.form.get('platform', '').strip() or None
    purchase.purchase_price = parse_decimal(request.form.get('purchase_price'))
    purchase.shipping_cost = parse_decimal(request.form.get('shipping_cost'))
    purchase.notes = request.form.get('purchaseNotes', '').strip() or None

    db.session.commit()
    flash('Purchase updated.', 'success')
    return redirect(url_for('view_purchase', purchase_id=purchase.id))

@app.route("/purchases/<int:purchase_id>/add", methods=["GET", "POST"])
@login_required
def add_items(purchase_id):
    purchase = Purchase.query.filter_by(
        id=purchase_id,
        user_id=current_user.id
    ).first_or_404()

    single_purchase = purchase.purchase_type == PurchaseType.SINGLE

    if request.method == 'POST':

        names = request.form.getlist('itemName[]')
        categories = request.form.getlist('category[]')
        brands = request.form.getlist('brand[]')
        conditions = request.form.getlist('condition[]')
        shelves_for_items = request.form.getlist('shelf_id[]')
        notes = request.form.getlist('itemNotes[]')
        quantities = request.form.getlist('itemQuantity[]')

        valid_names = [name.strip() for name in names if name.strip()]
        if not valid_names:
            flash('Add at least one item to this bundle.', 'danger')
        else:
            parsed_quantities = {}
            for index, name in enumerate(names):
                if not name.strip():
                    continue
                quantity = parse_quantity(quantities[index] if index < len(quantities) else None)
                if quantity is None:
                    flash('Every item quantity must be a positive whole number.', 'danger')
                    return render_template(
                        "purchases/purchases_add_items.html",
                        purchase=purchase,
                        shelves=Shelf.query.filter_by(user_id=current_user.id).order_by(Shelf.name).all(),
                        **get_item_form_options(current_user.id), single_purchase=single_purchase
                    )
                parsed_quantities[index] = quantity

            # Convert a Single to Bundle when the completed purchase has multiple items.
            if single_purchase and len(purchase.items) + len(valid_names) > 1:
                purchase.purchase_type = PurchaseType.BUNDLE

            for index, name in enumerate(names):
                name = name.strip()
                if not name:
                    continue
                db.session.add(create_purchase_item(
                    purchase, current_user.id, name,
                    category=categories[index] if index < len(categories) else None,
                    brand=brands[index] if index < len(brands) else None,
                    condition=conditions[index] if index < len(conditions) else None,
                    shelf_id=shelves_for_items[index] if index < len(shelves_for_items) else None,
                    notes=notes[index] if index < len(notes) else None,
                    quantity=parsed_quantities[index],
                ))
            db.session.commit()
            flash(f'{len(valid_names)} item(s) added to the purchase.', 'success')
            return redirect(url_for('view_purchase', purchase_id=purchase.id))

    return render_template(
        "purchases/purchases_add_items.html",
        purchase=purchase,
        shelves=Shelf.query.filter_by(user_id=current_user.id).order_by(Shelf.name).all(),
        **get_item_form_options(current_user.id), single_purchase=single_purchase
    )


#########################
#        Shelves

@app.route('/shelves', methods=['GET', 'POST'])
@login_required
def shelves():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()

        if not name:
            flash('Please write a shelf name', 'danger')
        elif Shelf.query.filter_by(user_id=current_user.id, name=name).first() is not None:
            flash('A box with this name already exists.', 'danger')
        else:
            db.session.add(Shelf(user_id=current_user.id, name=name, description=description))
            db.session.commit()
            flash("Shelf added.", "success")
        return redirect(url_for("shelves"))

    all_shelves = Shelf.query.filter_by(user_id=current_user.id).order_by(Shelf.name).all()
    return render_template('shelves.html', shelves=all_shelves)

@app.route('/shelves/<int:shelf_id>/delete', methods=["POST"])
@login_required
def delete_shelf(shelf_id):
    # Also make sure the user id matches for security
    shelf = Shelf.query.filter_by(id=shelf_id, user_id=current_user.id).first_or_404()
    if shelf.items:
        flash("Cannot delete a shelf that still has items on it.", "danger")

    ##############
    ##############
    # ADD option for it to automatically delete all items on the shelf?
    ##############
    ##############
    
    else:
        db.session.delete(shelf)
        db.session.commit()
        flash("Shelf deleted.", "success")
    return redirect(url_for("shelves"))


#########################
#       Listings

@app.route('/items/<int:item_id>/listings/new', methods=["GET", "POST"])
@login_required
def new_listing(item_id):
    item = Item.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()

    if request.method == "POST":
        listing = Listing(
            item_id=item.id,
            platform=request.form.get("platform", "").strip(),
            listing_id=request.form.get("listing_id", "").strip() or None,
            listing_url=request.form.get("listing_url", "").strip() or None,
            listing_price=parse_decimal(request.form.get("listing_price")),
            date_listed=parse_date(request.form.get("date_listed")),
            status=ListingStatus.ACTIVE,
        )
        if not listing.platform:
            flash("Platform is required.", "danger")
            return render_template("listings/listings_new.html", item=item)

        db.session.add(listing)
        if item.status == ItemStatus.IN_STORAGE:
            item.status = ItemStatus.ON_SALE
        db.session.commit()
        flash("Listing added.", "success")
        return redirect(url_for("view_item", item_id=item.id))

    return render_template("listings/listings_new.html", item=item)


@app.route('/listings/<int:listing_id>/edit', methods=["POST"])
@login_required
def edit_listing(listing_id):
    listing = Listing.query.join(Item).filter(
        Listing.id == listing_id, Item.user_id == current_user.id
    ).first_or_404()

    platform = request.form.get("platform", "").strip()
    if not platform:
        flash("Platform is required.", "danger")
        return redirect(url_for("view_item", item_id=listing.item_id))

    listing.platform = platform
    listing.listing_id = request.form.get("listing_id", "").strip() or None
    listing.listing_url = request.form.get("listing_url", "").strip() or None
    listing.listing_price = parse_decimal(request.form.get("listing_price"), default=None)
    listing.date_listed = parse_date(request.form.get("date_listed"), default=listing.date_listed)

    db.session.commit()
    flash("Listing updated.", "success")
    return redirect(url_for("view_item", item_id=listing.item_id))


@app.route('/listings/<int:listing_id>/delete', methods=["POST"])
@login_required
def delete_listing(listing_id):
    listing = Listing.query.join(Item).filter(
        Listing.id == listing_id, Item.user_id == current_user.id
    ).first_or_404()
    item_id = listing.item_id

    db.session.delete(listing)
    db.session.commit()
    flash("Listing deleted.", "success")
    return redirect(url_for("view_item", item_id=item_id))


@app.route('/listings/<int:listing_id>/status', methods=["POST"])
@login_required
def update_listing_status(listing_id):
    listing = Listing.query.join(Item).filter(
        Listing.id == listing_id, Item.user_id == current_user.id
    ).first_or_404()
    status = request.form.get("status")
    try:
        new_status = ListingStatus(status)
        if new_status == ListingStatus.SOLD:
            flash('Listings are marked Sold automatically when a sale is recorded.', 'warning')
            return redirect(url_for('view_item', item_id=listing.item_id))
        listing.status = new_status
    except (ValueError, TypeError):
        flash("Invalid listing status.", "danger")
        return redirect(url_for("view_item", item_id=listing.item_id))

    db.session.commit()
    flash("Listing status updated.", "success")
    return redirect(url_for("view_item", item_id=listing.item_id))


#########################
#       Sales

@app.route("/items/<int:item_id>/sale/new", methods=["GET", "POST"])
@login_required
def new_sale(item_id):
    item = Item.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    if item.available_quantity <= 0:
        flash("There are no available units to sell.", "warning")
        return redirect(url_for("view_item", item_id=item.id))
    if item.sale is not None:
        flash("This item has already been sold.", "warning")
        return redirect(url_for("view_item", item_id=item.id))

    if request.method == "POST":
        listing_id = request.form.get("listing_id")
        sale_quantity = parse_quantity(request.form.get("quantity"))
        if sale_quantity is None or sale_quantity > item.available_quantity:
            flash(f"Sale quantity must be between 1 and {item.available_quantity}.", "danger")
            return render_template("sales/sales_new.html", item=item)

        listing = None
        if listing_id:
            try:
                listing = Listing.query.join(Item).filter(
                    Listing.id == int(listing_id),
                    Listing.item_id == item.id,
                    Item.user_id == current_user.id,
                ).first()
            except (TypeError, ValueError):
                listing = None
            if listing is None:
                flash("Invalid listing selected.", "danger")
                return render_template("sales/sales_new.html", item=item)

        sale = Sale(
            item=item,
            listing_id=listing.id if listing else None,
            sale_date=parse_date(request.form.get("sale_date")),
            sale_price=parse_decimal(request.form.get("sale_price")),
            shipping_collected=parse_decimal(request.form.get("shipping_collected")),
            shipping_paid=parse_decimal(request.form.get("shipping_paid")),
            platform_fee=parse_decimal(request.form.get("platform_fee")),
            payment_fee=parse_decimal(request.form.get("payment_fee")),
            quantity=sale_quantity,
            notes=request.form.get("notes", "").strip(),
        )
        db.session.add(sale)
        item.quantity_sold += sale.quantity
        refresh_item_status(item)
        if listing:
            listing.status = ListingStatus.SOLD if item.available_quantity == 0 else ListingStatus.ACTIVE
        for l in item.listings:
            if item.available_quantity == 0 and l.id != sale.listing_id and l.status == ListingStatus.ACTIVE:
                l.status = ListingStatus.REMOVED
        db.session.commit()
        flash("Sale recorded.", "success")
        return redirect(url_for("view_item", item_id=item.id))

    return render_template("sales/sales_new.html", item=item)


@app.route("/sales/<int:sale_id>/edit", methods=["POST"])
@login_required
def edit_sale(sale_id):
    sale = Sale.query.join(Item).filter(Sale.id == sale_id, Item.user_id == current_user.id).first_or_404()
    item = sale.item

    listing_id = request.form.get("listing_id")
    listing = None
    if listing_id:
        try:
            listing = Listing.query.filter_by(id=int(listing_id), item_id=item.id).first()
        except (TypeError, ValueError):
            listing = None
        if listing is None:
            flash("Invalid listing selected.", "danger")
            return redirect(url_for("view_item", item_id=item.id))

    sale.listing_id = listing.id if listing else None
    sale.sale_date = parse_date(request.form.get("sale_date"), default=sale.sale_date)
    sale.sale_price = parse_decimal(request.form.get("sale_price"))
    sale.shipping_collected = parse_decimal(request.form.get("shipping_collected"))
    sale.shipping_paid = parse_decimal(request.form.get("shipping_paid"))
    sale.platform_fee = parse_decimal(request.form.get("platform_fee"))
    sale.payment_fee = parse_decimal(request.form.get("payment_fee"))
    sale.notes = request.form.get("notes", "").strip() or None

    raw_quantity = request.form.get("quantity")
    if raw_quantity is None:
        sale_quantity = sale.quantity
    else:
        sale_quantity = parse_quantity(raw_quantity)
    # Units held by this sale plus the ones still available
    if sale.item_returned:
        max_quantity = sale.quantity
    else:
        max_quantity = item.available_quantity + sale.quantity
    if sale_quantity is None or sale_quantity > max_quantity:
        flash(f"Sale quantity must be between 1 and {max_quantity}.", "danger")
        return redirect(url_for("view_item", item_id=item.id))
    if sale.item_returned:
        # A returned sale doesn't hold any stock, so it can't change quantities
        sale.quantity = sale_quantity
        db.session.commit()
        flash("Sale updated.", "success")
        return redirect(url_for("view_item", item_id=item.id))
    item.quantity_sold += sale_quantity - sale.quantity
    sale.quantity = sale_quantity
    refresh_item_status(item)

    for listing in item.listings:
        if listing.id == sale.listing_id:
            listing.status = ListingStatus.SOLD if item.available_quantity == 0 else ListingStatus.ACTIVE
        elif item.available_quantity == 0 and listing.status in (ListingStatus.ACTIVE, ListingStatus.SOLD):
            listing.status = ListingStatus.REMOVED

    db.session.commit()
    flash("Sale updated.", "success")
    return redirect(url_for("view_item", item_id=item.id))


@app.route("/sales/<int:sale_id>/refund", methods=["POST"])
@login_required
def refund_sale(sale_id):
    sale = Sale.query.join(Item).filter(Sale.id == sale_id, Item.user_id == current_user.id).first_or_404()
    item = sale.item

    refund_amount = parse_decimal(request.form.get("refund_amount"))
    if refund_amount < 0:
        flash("Refund amount can't be negative.", "danger")
        return redirect(url_for("view_item", item_id=item.id))
    item_returned = request.form.get("item_returned") == "on"

    if item_returned and not sale.item_returned:
        # The units come back into stock and can be sold again
        item.quantity_sold = max(item.quantity_sold - sale.quantity, 0)
        if sale.listing and sale.listing.status == ListingStatus.SOLD:
            sale.listing.status = ListingStatus.REMOVED
    elif sale.item_returned and not item_returned:
        # Undo return
        if item.sale is not None or item.available_quantity < sale.quantity:
            flash("The returned units have been sold or written off since, so this return can't be undone.", "danger")
            return redirect(url_for("view_item", item_id=item.id))
        item.quantity_sold += sale.quantity

    sale.refund_amount = refund_amount
    sale.item_returned = item_returned
    refresh_item_status(item)
    db.session.commit()
    flash("Refund saved." if sale.is_refunded else "Refund removed.", "success")
    return redirect(url_for("view_item", item_id=item.id))


@app.route("/items/<int:item_id>/write-off", methods=["POST"])
@login_required
def write_off_item(item_id):
    item = Item.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    if item.available_quantity <= 0:
        flash("There are no available units to write off.", "warning")
        return redirect(url_for("view_item", item_id=item.id))

    # Whole item only: every remaining unit is written off
    item.quantity_written_off += item.available_quantity
    for listing in item.listings:
        if listing.status == ListingStatus.ACTIVE:
            listing.status = ListingStatus.REMOVED
    refresh_item_status(item)
    db.session.commit()
    flash("Item written off. Its cost now counts as a loss.", "success")
    return redirect(url_for("view_item", item_id=item.id))


@app.route("/items/<int:item_id>/write-off/undo", methods=["POST"])
@login_required
def undo_write_off(item_id):
    item = Item.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    item.quantity_written_off = 0
    refresh_item_status(item)
    db.session.commit()
    flash("Write-off undone. The units are back in inventory.", "success")
    return redirect(url_for("view_item", item_id=item.id))


#########################
#     Authentication

# https://flask-login.readthedocs.io/en/latest/#login-example
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        # Sanitize inputs
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()

        # Validate username and password
        if user is None or not check_password_hash(user.password_hash, password):
            flash('Invalid username or password.', 'danger')
        else:
            # Log-in the user
            login_user(user)
            flash('Logged in successfully.', 'success')
            return redirect(url_for('index'))

    return render_template("login.html")

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == "POST":
        # Sanitize inputs
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        repeat_password = request.form.get('repeat_password', '')

        # Validate the form
        if not username or not password:
            flash('Please insert username and password.', 'danger')
        elif password != repeat_password:
            flash('Passwords do not match.', 'danger')
        elif User.query.filter_by(username=username).first():
            flash('That username is already taken.', 'danger')

        else:
            # Complete registration
            user = User(username=username, password_hash=generate_password_hash(password))
            print(user)
            db.session.add(user)
            db.session.commit()

        # Redirect to login page
        ################################################################### ADD AUTO-LOGIN 
        return redirect(url_for('login'))
            
    
    return render_template('register.html')

#########################
#         User

@app.route('/user', methods=['GET', 'POST'])
@login_required
def user():
    if request.method == 'POST':
        # Persist the chosen cosmetic currency to the user's account.
        currency = request.form.get('currency', '').strip().upper()
        if currency in CURRENCY_SYMBOLS:
            current_user.currency = currency
            db.session.commit()
            flash('Currency preference saved.', 'success')
        else:
            flash('Please choose a valid currency.', 'danger')
    return render_template('user.html')

@app.route('/user/delete-database', methods=['POST'])
@login_required
def delete_database():
    try:
        reset_database()
        flash('Database deleted.', 'success')
    except Exception as exc:
        flash(f'Could not delete database: {exc}', 'danger')

    return redirect(url_for('user'))

@app.route('/user/import-csv', methods=['POST'])
@login_required
def import_csv():
    csv_file = request.files.get('csv_file')
    if csv_file is None or not csv_file.filename:
        flash('Choose a CSV file to import.', 'danger')
        return redirect(url_for('user'))

    try:
        result = process_csv(csv_file, current_user.id)
    except Exception:
        db.session.rollback()
        app.logger.exception('CSV import failed')
        flash('The CSV could not be imported.', 'danger')
        return redirect(url_for('user'))

    message = (
        f"Imported {result['purchases_created']} purchase(s) and "
        f"{result['items_created']} item(s)."
    )
    if result['errors']:
        return render_template('user.html', import_result=result)

    flash(message, 'success')
    return redirect(url_for('user'))

@app.route('/user/export-csv')
@login_required
def export_csv():
    purchases = Purchase.query.filter_by(user_id=current_user.id).all()
    items = Item.query.filter_by(user_id=current_user.id).order_by(Item.id).all()

    def csv_money(value):
        return f"{value:.2f}" if value is not None else ""

    def csv_date(value):
        return value.isoformat() if value else ""

    def item_listing(item):
        if item.sale and item.sale.listing:
            return item.sale.listing
        active_listing = next(
            (listing for listing in item.listings if listing.status == ListingStatus.ACTIVE),
            None,
        )
        return active_listing or (item.listings[0] if item.listings else None)

    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow([
        "Bundle", "Quantity", "Sold Quantity", "Item", "Status",
        "Sales platform", "Bought date", "Sold date", "Buy price (unit)",
        "Sell price (total)", "Sold price", "Profit", "Refund amount", "Notes", "",
        "Bundle Name", "Bundle Cost",
    ])

    for item in items:
        purchase = item.purchase
        listing = item_listing(item)
        platform = (
            listing.platform if listing else None
        ) or (purchase.platform if purchase else None) or ""
        buy_price_unit = ""
        if purchase and purchase.purchase_type == PurchaseType.SINGLE and item.quantity:
            buy_price_unit = csv_money(purchase.total_cost / item.quantity)

        writer.writerow([
            purchase.name if purchase and purchase.purchase_type == PurchaseType.BUNDLE else "Individual",
            item.quantity,
            item.quantity_sold,
            item.name,
            item.status.value,
            platform,
            csv_date(purchase.date if purchase else None),
            csv_date(item.sale.sale_date if item.sale else None),
            buy_price_unit,
            csv_money(listing.listing_price if listing else None),
            csv_money(item.sale.sale_price if item.sale else None),
            csv_money(item.realized_profit),
            csv_money(item.sale.refund_amount if item.sale and item.sale.refund_amount else None),
            item.notes or "",
            "",
            "",
            "",
        ])

    exported_bundles = set()
    for purchase in purchases:
        if purchase.purchase_type != PurchaseType.BUNDLE:
            continue
        bundle_name = purchase.name or ""
        bundle_key = (" ".join(bundle_name.casefold().split()), purchase.total_cost)
        if bundle_key in exported_bundles:
            continue
        exported_bundles.add(bundle_key)
        writer.writerow([
            "", "", "", "", "", "", "", "", "", "", "", "", "", "", "",
            bundle_name,
            csv_money(purchase.total_cost),
        ])

    response = Response("\ufeff" + output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = (
        f"attachment; filename=resale-desk-export-{date.today().isoformat()}.csv"
    )
    return response
