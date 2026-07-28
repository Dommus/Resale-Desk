import os
from datetime import date as datetime_date
from models import db, User, Shelf, Item, Purchase, ItemStatus

from flask import Flask, render_template, request, redirect, url_for, flash
# from sqlalchemy import create_engine
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from sqlalchemy import func, or_
from werkzeug.security import generate_password_hash, check_password_hash


# Configure App and Database (https://www.geeksforgeeks.org/python/declaring-models-in-flask/)
app = Flask(__name__)

# https://flask-sqlalchemy.readthedocs.io/en/stable/config/
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ECHO'] = True
app.secret_key = '4815_THISisCS50_162342'

# Login Manager
# https://flask-login.readthedocs.io/en/latest/
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to continue.'
login_manager.login_message_category = 'warning'

@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return db.session.get(User, user_id)



# #################
# FUTURE FEATURES:
# CSV import feature
# ########################


# Find the absolute path to the directory with the current Python script
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
# Create instance directory
os.makedirs(os.path.join(BASE_DIR, 'instance'), exist_ok=True)

# Bind db object to this app instance
db.init_app(app)

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
        'inventory.html',
        items=items,
        shelves=shelves,
        purchases=purchases,
        selected_shelf_id=shelf_id,
        search_query=query,
    )

@app.route('/purchases', methods=['GET', 'POST'])
@login_required
def purchases():
    if request.method == 'POST':
        try:
            purchase_date = datetime_date.fromisoformat(request.form.get('date', '').strip() or datetime_date.today().isoformat())
        except ValueError:
            purchase_date = datetime_date.today()

        purchase = Purchase(
            user_id=current_user.id,
            date=purchase_date,
            seller=request.form.get('seller', '').strip() or None,
            platform=request.form.get('platform', '').strip() or None,
            purchase_type=request.form.get('purchase_type', 'single').strip() or 'single',
            purchase_price=float(request.form.get('purchase_price', 0) or 0),
            shipping_cost=float(request.form.get('shipping_cost', 0) or 0),
            notes=request.form.get('notes', '').strip() or None,
        )
        db.session.add(purchase)
        db.session.commit()
        flash('Purchase recorded.', 'success')
        return redirect(url_for('purchases'))

    all_purchases = Purchase.query.filter_by(user_id=current_user.id).order_by(Purchase.date.desc(), Purchase.id.desc()).all()
    today = datetime_date.today().isoformat()
    return render_template('purchases.html', purchases=all_purchases, today=today)

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
