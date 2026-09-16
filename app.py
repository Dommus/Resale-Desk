import os
from datetime import datetime, date

# Imports from local python files
from models import db, User, Shelf, Item, Purchase, ItemStatus, PurchaseType, Listing, ListingStatus, Sale
from utilities import login_manager, parse_date, parse_decimal

from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import func, or_, cast, String
from werkzeug.security import generate_password_hash, check_password_hash

from decimal import Decimal


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
# CSV import & export feature
# Change currency symbol all throughout the app
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
                         shelf_id=None, notes=None):
    # Return new Item instance with sanitized inputs
    return Item(
        user_id=user_id,
        purchase_id=purchase.id,
        shelf_id=int(shelf_id) if shelf_id else None,
        name=name.strip(),
        category=category.strip() or None if category else None,
        condition=condition.strip() or None if condition else None,
        brand=brand.strip() or None if brand else None,
        status=ItemStatus.IN_STORAGE,
        notes=notes.strip() or None if notes else None,
    )


##########################
#        ROUTES
##########################

@app.route('/')
@login_required
def index():
    # Queries for dashboard data
    item_count = Item.query.filter_by(user_id=current_user.id).count()
    on_sale_count = Item.query.filter_by(user_id=current_user.id, status=ItemStatus.ON_SALE).count()
    sold_count = Item.query.filter_by(user_id=current_user.id, status=ItemStatus.SOLD).count()
    purchase_count = Purchase.query.filter_by(user_id=current_user.id).count()
    total_spend = (
        db.session.query(func.coalesce(func.sum(Purchase.purchase_price + Purchase.shipping_cost), Decimal("0.00")))
        .filter(Purchase.user_id == current_user.id)
        .scalar() or Decimal("0.00")
    )
    # TODO add total profit?
    recent_items = Item.query.filter_by(user_id=current_user.id).order_by(Item.created_at.desc()).limit(5).all()
    recent_purchases = Purchase.query.filter_by(user_id=current_user.id).order_by(Purchase.date.desc()).limit(5).all()

    return render_template(
        'index.html',
        item_count=item_count,
        on_sale_count=on_sale_count,
        sold_count=sold_count,
        purchase_count=purchase_count,
        total_spend=round(total_spend, 2),
        recent_items=recent_items,
        recent_purchases=recent_purchases,
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
        results.sort(key=lambda i: (i.sale.profit if i.sale else Decimal("-Infinity")), reverse=True)
    elif sort == "lowest_profit":
        results.sort(key=lambda i: (i.sale.profit if i.sale else Decimal("Infinity")))

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
    item.category = request.form.get('category', '').strip() or None
    item.brand = request.form.get('brand', '').strip() or None
    item.condition = request.form.get('condition', '').strip() or None
    shelf_id = request.form.get('shelf_id')
    item.shelf_id = int(shelf_id) if shelf_id else None
    status = request.form.get('status')

    # Change item status
    try:
        # Item should only being set as Sold when recording a sale
        new_status = ItemStatus(status)
        if new_status == ItemStatus.SOLD:
            flash('Items are marked Sold automatically when a sale is recorded.', 'warning')
            return redirect(url_for('view_item', item_id=item.id))
        item.status = new_status
    except (ValueError, TypeError):
        flash(f"Invalid status: {status!r}", "error")
        pass

    item.notes = request.form.get('notes', '').strip()
    db.session.commit()
    flash('Item updated.', 'success')
    return redirect(url_for('view_item', item_id=item.id))


@app.route('/items/<int:item_id>/delete', methods=["POST"])
@login_required
def delete_item(item_id):
    item = Item.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    db.session.delete(item)
    db.session.commit()
    flash("Item deleted.", "success")
    return redirect(url_for("inventory"))


#########################
#       Purchases

@app.route('/purchases', methods=['GET', 'POST'])
@login_required
def purchases():
    purchases = (
        Purchase.query.filter_by(user_id=current_user.id).order_by(Purchase.date.desc()).all()
    )
    return render_template("purchases/purchases.html", purchases=purchases)

@app.route("/purchases/new", methods=["GET", "POST"])
@login_required
def new_purchase():

    # Exported variables
    shelves = (
        Shelf.query.filter_by(user_id=current_user.id).order_by(Shelf.name.desc()).all()
    )
    today = date.today().isoformat()
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

        purchase = Purchase(
            user_id = current_user.id,
            date = parse_date(request.form.get('date')),
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
                return render_template("purchases/purchases_new.html", today=today,
                                       shelves=shelves, purchase_type=purchase_type_label,
                                       **form_options)

            db.session.add(create_purchase_item(
                purchase, current_user.id, name,
                category=request.form.get('category'),
                brand=request.form.get('brand'),
                condition=request.form.get('condition'),
                shelf_id=request.form.get('shelf_id'),
                notes=request.form.get('itemNotes'),
            ))
            flash(f'{name} added to the purchase.', 'success')

        elif checked_add_items and purchase_type == PurchaseType.BUNDLE:
            names = request.form.getlist('itemName[]')
            categories = request.form.getlist('category[]')
            brands = request.form.getlist('brand[]')
            conditions = request.form.getlist('condition[]')
            shelves_for_items = request.form.getlist('shelf_id[]')
            notes = request.form.getlist('itemNotes[]')

            valid_names = [name.strip() for name in names if name.strip()]
            if not valid_names:
                db.session.rollback()
                flash('Add at least one item to this bundle.', 'danger')
                return render_template("purchases/purchases_new.html", today=today,
                                       shelves=shelves, purchase_type=purchase_type_label,
                                       **form_options)

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
                ))
            flash(f'{len(valid_names)} item(s) added to the purchase.', 'success')

        db.session.commit()
        return redirect(url_for('view_purchase', purchase_id=purchase.id))

    
    return render_template("purchases/purchases_new.html", today=today, shelves=shelves,
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
    return render_template("purchases/purchases_view.html", purchase=purchase)

@app.route("/purchases/<int:purchase_id>/add", methods=["GET", "POST"])
@login_required
def add_items(purchase_id):
    purchase = Purchase.query.filter_by(
        id=purchase_id,
        user_id=current_user.id
    ).first_or_404()

    if purchase.purchase_type != PurchaseType.BUNDLE:
        flash('Only bundle purchases can contain multiple items.', 'warning')
        return redirect(url_for('view_purchase', purchase_id=purchase.id))

    if request.method == 'POST':
        names = request.form.getlist('itemName[]')
        categories = request.form.getlist('category[]')
        brands = request.form.getlist('brand[]')
        conditions = request.form.getlist('condition[]')
        shelves_for_items = request.form.getlist('shelf_id[]')
        notes = request.form.getlist('itemNotes[]')

        valid_names = [name.strip() for name in names if name.strip()]
        if not valid_names:
            flash('Add at least one item to this bundle.', 'danger')
        else:
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
                ))
            db.session.commit()
            flash(f'{len(valid_names)} item(s) added to the purchase.', 'success')
            return redirect(url_for('view_purchase', purchase_id=purchase.id))

    return render_template(
        "purchases/purchases_add_items.html",
        purchase=purchase,
        shelves=Shelf.query.filter_by(user_id=current_user.id).order_by(Shelf.name).all(),
        **get_item_form_options(current_user.id),
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
            listing_id=request.form.get("listing_id", "").strip(),
            listing_url=request.form.get("listing_url", "").strip(),
            listing_price=parse_decimal(request.form.get("listing_price")),
            date_listed=parse_date(request.form.get("date_listed")),
            status=ListingStatus.ACTIVE,
        )
        if not listing.platform or not listing.listing_id:
            flash("Platform and listing ID are required.", "danger")
            return render_template("listings/new.html", item=item)

        db.session.add(listing)
        if item.status == ItemStatus.IN_STORAGE:
            item.status = ItemStatus.ON_SALE
        db.session.commit()
        flash("Listing added.", "success")
        return redirect(url_for("view_item", item_id=item.id))

    return render_template("listings/listings_new.html", item=item)


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
    if item.sale is not None:
        flash("This item has already been sold.", "warning")
        return redirect(url_for("view_item", item_id=item.id))

    if request.method == "POST":
        listing_id = request.form.get("listing_id")
        sale = Sale(
            item_id=item.id,
            listing_id=int(listing_id) if listing_id else None,
            sale_date=parse_date(request.form.get("sale_date")),
            sale_price=parse_decimal(request.form.get("sale_price")),
            shipping_received=parse_decimal(request.form.get("shipping_received")),
            shipping_paid=parse_decimal(request.form.get("shipping_paid")),
            platform_fee=parse_decimal(request.form.get("platform_fee")),
            payment_fee=parse_decimal(request.form.get("payment_fee")),
            notes=request.form.get("notes", "").strip(),
        )
        db.session.add(sale)
        item.status = ItemStatus.SOLD
        if sale.listing_id:
            chosen = db.session.get(Listing, sale.listing_id)
            if chosen:
                chosen.status = ListingStatus.SOLD
        for l in item.listings:
            if l.id != sale.listing_id and l.status == ListingStatus.ACTIVE:
                l.status = ListingStatus.REMOVED
        db.session.commit()
        flash("Sale recorded.", "success")
        return redirect(url_for("view_item", item_id=item.id))

    return render_template("sales/new.html", item=item)


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
