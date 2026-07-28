import os
from datetime import datetime, date

# Imports from local python files
from models import db, User, Shelf, Item, Purchase, ItemStatus
from utilities import login_manager, parse_date, parse_float


from flask import Flask, render_template, request, redirect, url_for, flash
# from sqlalchemy import create_engine
from flask_sqlalchemy import SQLAlchemy
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import func, or_
from werkzeug.security import generate_password_hash, check_password_hash


# Configure App and Database (https://www.geeksforgeeks.org/python/declaring-models-in-flask/)
app = Flask(__name__)

# https://flask-sqlalchemy.readthedocs.io/en/stable/config/
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, 'instance', 'database.db')
os.makedirs(os.path.join(BASE_DIR, 'instance'), exist_ok=True)

# App configs
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ECHO'] = False # 'True' for debugging SQL queries
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



# #################
# FUTURE FEATURES:
# CSV import feature
# Change currency symbol all throughout the app
# ########################


# Bind db object to this app instance
db.init_app(app)

# Delete and recreate the database
def reset_database():
    db.session.remove()

    if hasattr(db, 'engine'):
        db.engine.dispose()

    for candidate in (DB_PATH, os.path.join(BASE_DIR, 'database.db')):
        if os.path.exists(candidate):
            try:
                os.chmod(candidate, 0o666)
            except OSError:
                pass
            os.remove(candidate)

    with app.app_context():
        db.create_all()
        create_admin_account()

    print(f"Database reset at {DB_PATH}")

# Create test account for debugging
def create_admin_account():
    if not User.query.filter_by(username='admin').first():
        user = User(username='admin', password_hash=generate_password_hash('123'))
        db.session.add(user)
        db.session.commit()

# Create the physical database files

with app.app_context():
    db.create_all()
    create_admin_account()

# Routes
# ------
@app.route('/')
@login_required
def index():
    item_count = Item.query.filter_by(user_id=current_user.id).count()
    on_sale_count = Item.query.filter_by(user_id=current_user.id, status=ItemStatus.ON_SALE).count()
    sold_count = Item.query.filter_by(user_id=current_user.id, status=ItemStatus.SOLD).count()
    purchase_count = Purchase.query.filter_by(user_id=current_user.id).count()
    total_spend = (
        db.session.query(func.coalesce(func.sum(Purchase.purchase_price + Purchase.shipping_cost), 0.0))
        .filter(Purchase.user_id == current_user.id)
        .scalar() or 0.0
    )
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

# INVENTORY
@app.route('/inventory', methods=['GET', 'POST'])
@login_required
def inventory():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        purchase_id = request.form.get('purchase_id', type=int)
        if not name:
            flash('Please provide an item name.', 'danger')
        elif not purchase_id:
            flash('Choose a purchase before adding an item.', 'danger')
        else:
            status_name = request.form.get('status', 'ON_SALE')
            status = ItemStatus[status_name] if status_name in ItemStatus.__members__ else ItemStatus.ON_SALE
            item = Item(
                user_id=current_user.id,
                name=name,
                category=request.form.get('category', '').strip() or None,
                condition=request.form.get('condition', '').strip() or None,
                code=request.form.get('code', '').strip() or None,
                brand=request.form.get('brand', '').strip() or None,
                status=status,
                purchase_id=purchase_id,
                shelf_id=request.form.get('shelf_id', type=int) or None,
            )
            db.session.add(item)
            db.session.commit()
            flash('Item added to inventory.', 'success')
        return redirect(url_for('inventory'))

    query = request.args.get('q', '').strip()
    shelf_id = request.args.get('shelf_id', type=int)

    inventory_query = Item.query.filter_by(user_id=current_user.id)
    if shelf_id:
        inventory_query = inventory_query.filter_by(shelf_id=shelf_id)
    if query:
        search_pattern = f'%{query}%'
        inventory_query = inventory_query.filter(
            or_(
                Item.name.ilike(search_pattern),
                Item.category.ilike(search_pattern),
                Item.brand.ilike(search_pattern),
                Item.code.ilike(search_pattern),
            )
        )

    items = inventory_query.order_by(Item.created_at.desc()).all()
    shelves = Shelf.query.filter_by(user_id=current_user.id).order_by(Shelf.name).all()
    purchases = Purchase.query.filter_by(user_id=current_user.id).order_by(Purchase.date.desc()).all()
    return render_template(
        'inventory/inventory.html',
        items=items,
        shelves=shelves,
        purchases=purchases,
        selected_shelf_id=shelf_id,
        search_query=query,
    )

# @app.route("/inventory/<int:item_id>")


# PURCHASES
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

    if request.method == 'POST':

        # Get data from request
        purchase_type = request.form.get('purchase_type')
        print('Purchase type is '+ purchase_type)

        purchase = Purchase(
            user_id = current_user.id,
            date = parse_date(request.form.get('date')),
            seller = request.form.get('seller', '').strip(),
            platform = request.form.get('platform', '').strip(),
            purchase_type = purchase_type,
            purchase_price = parse_float(request.form.get('purchase_price')),
            shipping_cost = parse_float(request.form.get('shipping_cost')),
            notes = request.form.get("notes", "").strip(),
        )

        db.session.add(purchase)
        db.session.flush()

        # Begin proccessing purchase
        if purchase_type == 'single':
            db.session.commit()
            print('BEGIN SINGLE PURCHASE')

        elif purchase_type == 'bundle':
            print('BEGIN BUNDLE PURCHASE')
            db.session.commit()
        else:
            print('ERROR: NO PURCHASE TYPE SELECTED')
            flash('Select a purchase type', 'danger')
    

    # Exported variables
    shelves = (
        Shelf.query.filter_by(user_id=current_user.id).order_by(Shelf.name.desc()).all()
    )
    today = date.today().isoformat()
    return render_template ("purchases/purchases_new.html", today=today, shelves=shelves)


@app.route("/purchases/<int:purchase_id>")
@login_required
def view_purchase(purchase_id):
    purchase = Purchase.query.filter_by(id=purchase_id, user_id=current_user.id).first_or_404()
    return render_template("purchases/purchases_view.html", purchase=purchase)



# SHELVES
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

@app.route("/shelves/<int:shelf_id>/delete", methods=["POST"])
@login_required
def delete_shelf(shelf_id):
    # Also make sure the user id matches for security
    shelf = Shelf.query.filter_by(id=shelf_id, user_id=current_user.id).first_or_404()
    if shelf.items:
        flash("Cannot delete a shelf that still has items on it.", "danger")

    ##############
    # ADD option for it to automatically delete all items on the shelf?
    ##############
    
    else:
        db.session.delete(shelf)
        db.session.commit()
        flash("Shelf deleted.", "success")
    return redirect(url_for("shelves"))


# SALES




# Authentication
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
        # ADD AUTO-LOGIN 
        return redirect(url_for('login'))
            
    
    return render_template('register.html')

# User

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