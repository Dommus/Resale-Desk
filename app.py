import os, csv, re, secrets, sqlite3, gzip, tempfile
from datetime import datetime, date, timedelta
from urllib.parse import urlparse

# Imports from local python files
from models import db, User, Shelf, Item, Purchase, ItemStatus, PurchaseType, Listing, ListingStatus, Sale
from utilities import login_manager, parse_date, parse_decimal, parse_quantity, process_csv, currency_display, CURRENCY_SYMBOLS
from translations import _, get_language, js_translations, LANGUAGES, LANGUAGE_COOKIE, HTML_LANG

from flask import Flask, Response, abort, jsonify, render_template, request, redirect, url_for, flash, g, send_from_directory
from flask_login import login_user, logout_user, login_required, current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from sqlalchemy import or_, and_, case, cast, func, select, String
from sqlalchemy.orm import joinedload, selectinload
from markupsafe import Markup, escape
from werkzeug.security import generate_password_hash, check_password_hash

from decimal import Decimal

from io import StringIO


# Configure App and Database (https://www.geeksforgeeks.org/python/declaring-models-in-flask/)
app = Flask(__name__)

# https://flask-sqlalchemy.readthedocs.io/en/stable/config/
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, 'instance', 'database.db')
# Demo data shipped with the app, copied in as the database on first run
DEMO_DB_PATH = os.path.join(BASE_DIR, 'demo.db')
os.makedirs(os.path.join(BASE_DIR, 'instance'), exist_ok=True)

# Set RESALE_DESK_PRODUCTION=1 and SECRET_KEY on a public server.
# Production mode closes registration, skips the demo data and only sends cookies over HTTPS.
PRODUCTION = os.environ.get('RESALE_DESK_PRODUCTION') == '1'
ALLOW_REGISTRATION = os.environ.get('ALLOW_REGISTRATION', '0' if PRODUCTION else '1') == '1'
# One-click login to the public demo account from demo.db. Off in production unless DEMO_LOGIN=1.
DEMO_LOGIN = os.environ.get('DEMO_LOGIN', '0' if PRODUCTION else '1') == '1'
DEMO_USERNAME, DEMO_PASSWORD = 'demo', 'cs50'
# Google Sheets sync: the sheet's script fetches this user's data with the token.
# Leave either unset to turn the sync endpoint off.
SHEETS_SYNC_TOKEN = os.environ.get('SHEETS_SYNC_TOKEN')
SHEETS_SYNC_USER = os.environ.get('SHEETS_SYNC_USER')
# Database backups: the sheet's script downloads a full copy with this token.
# It is separate from the sync token because the copy holds every account.
BACKUP_TOKEN = os.environ.get('BACKUP_TOKEN')

# App configs
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ECHO'] = False # Set to 'True' for debugging SQL queries

# Signs the session cookie, so it must be secret. Locally a random key is fine (logins reset on restart).
secret_key = os.environ.get('SECRET_KEY')
if PRODUCTION and not secret_key:
    raise RuntimeError('SECRET_KEY must be set when RESALE_DESK_PRODUCTION=1')
app.secret_key = secret_key or secrets.token_hex(32)

# https://flask.palletsprojects.com/en/stable/security/#set-cookie-options
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['REMEMBER_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = PRODUCTION
app.config['REMEMBER_COOKIE_SECURE'] = PRODUCTION
app.config['REMEMBER_COOKIE_HTTPONLY'] = True
# "Remember me" keeps users logged in after closing the browser
app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=90)
# Limit uploads (CSV import) to 5 MB
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024

# Login Manager
# https://flask-login.readthedocs.io/en/latest/
login_manager.init_app(app)
login_manager.localize_callback = _

# Rate limiting, to slow down password guessing
# https://flask-limiter.readthedocs.io/en/stable/
# Counters live in memory, so they reset on restart and are per worker process.
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

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
# Change currency symbol all throughout the app
##########################


##########################
#       FUNCTIONS
##########################

# Create the physical database files
def create_database(with_demo_data=True):
    if with_demo_data and not os.path.exists(DB_PATH) and os.path.exists(DEMO_DB_PATH):
        with open(DEMO_DB_PATH, 'rb') as source, open(DB_PATH, 'wb') as copy:
            copy.write(source.read())
    with app.app_context():
        db.create_all()


# The demo data has accounts with public passwords, so never load it on a public server
create_database(with_demo_data=not PRODUCTION)

# Delete the user's own data, keeping their account and everyone else's data
def reset_user_data(user):
    # Deleting a purchase also deletes its items, listings and sales
    for purchase in user.purchases:
        db.session.delete(purchase)
    db.session.flush()
    for record in Item.query.filter_by(user_id=user.id).all() + user.shelves:
        db.session.delete(record)
    db.session.commit()


# Only the shelves the user owns can be assigned to their items
def owned_shelf_id(shelf_id, user_id):
    try:
        shelf_id = int(shelf_id)
    except (TypeError, ValueError):
        return None
    return shelf_id if Shelf.query.filter_by(id=shelf_id, user_id=user_id).first() else None

# Helper functions
##########################

def get_used_values(model, column_name, user_id):
    # Let the database return the distinct values instead of loading every row
    column = getattr(model, column_name)
    rows = db.session.query(column).filter(model.user_id == user_id).distinct()
    return sorted(value for (value,) in rows if value)


COMMON_LISTING_PLATFORMS = ['Vinted', 'eBay', 'OLX', 'Facebook Marketplace']


def get_item_form_options(user_id):
    # Listings have no user_id, so their platforms are found through the items
    listing_platforms = db.session.query(Listing.platform).join(Item).filter(Item.user_id == user_id).distinct()
    return {
        'used_categories': get_used_values(Item, 'category', user_id),
        'used_brands': get_used_values(Item, 'brand', user_id),
        'used_listing_platforms': sorted(set(COMMON_LISTING_PLATFORMS) | {value for (value,) in listing_platforms if value}),
    }


def get_purchase_form_options(user_id):
    options = get_item_form_options(user_id)

    options.update({
        'used_sellers': get_used_values(Purchase, 'seller', user_id),
        'used_platforms': get_used_values(Purchase, 'platform', user_id),
    })
    
    return options


def parse_item_code(q):
    # "42", "I-000042" and "i42" all point to item 42
    match = re.fullmatch(r'(?:i-?)?(\d{1,9})', q, re.IGNORECASE)
    return int(match.group(1)) if match else None


def item_search_filter(q):
    # Inventory search: name, category, inventory ID or code, or listing ID.
    # Shared by the inventory page and the navbar search preview, so both find the same items.
    pattern = f'%{q}%'
    conditions = [
        Item.name.ilike(pattern),
        cast(Item.id, String).ilike(pattern),
        Item.category.ilike(pattern),
        Item.id.in_(select(Listing.item_id).where(Listing.listing_id.ilike(pattern))),
    ]
    code = parse_item_code(q)
    if code is not None:
        conditions.append(Item.id == code)
    return or_(*conditions)


def create_purchase_item(purchase, user_id, name, category=None, brand=None, condition=None, 
                         shelf_id=None, notes=None, quantity=1):
    # Return new Item instance with sanitized inputs
    return Item(
        user_id=user_id,
        purchase_id=purchase.id,
        shelf_id=owned_shelf_id(shelf_id, user_id),
        name=name.strip(),
        quantity=quantity,
        quantity_sold=0,
        # Set here rather than left to the column default, so a sale can be
        # recorded on the new item before it is flushed
        quantity_written_off=0,
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


# Shared by the listing form and the purchase form. fields uses the listing form's names.
def add_listing(item, fields):
    listing = Listing(
        platform=fields.get("platform", "").strip(),
        listing_id=fields.get("listing_id", "").strip() or None,
        listing_url=fields.get("listing_url", "").strip() or None,
        listing_price=parse_decimal(fields.get("listing_price")),
        date_listed=parse_date(fields.get("date_listed")),
        status=ListingStatus.ACTIVE,
    )
    item.listings.append(listing)
    if item.status == ItemStatus.IN_STORAGE:
        item.status = ItemStatus.ON_SALE
    return listing


# Shared by the sale form and the purchase form. fields uses the sale form's names.
def add_sale(item, fields, quantity, listing=None):
    sale = Sale(
        item=item,
        listing=listing,
        sale_date=parse_date(fields.get("sale_date")),
        sale_price=parse_decimal(fields.get("sale_price")),
        shipping_collected=parse_decimal(fields.get("shipping_collected")),
        shipping_paid=parse_decimal(fields.get("shipping_paid")),
        platform_fee=parse_decimal(fields.get("platform_fee")),
        payment_fee=parse_decimal(fields.get("payment_fee")),
        quantity=quantity,
        notes=fields.get("notes", "").strip(),
    )
    db.session.add(sale)
    item.quantity_sold += quantity
    refresh_item_status(item)
    if listing:
        listing.status = ListingStatus.SOLD if item.available_quantity == 0 else ListingStatus.ACTIVE
    for l in item.listings:
        if item.available_quantity == 0 and l is not listing and l.status == ListingStatus.ACTIVE:
            l.status = ListingStatus.REMOVED
    return sale


# Item cards on the purchase forms
#
# Each card's fields are numbered, so the server can tell which listings and
# sale belong to which item:
#   items-<i>-name, items-<i>-quantity, ...
#   items-<i>-listings-<j>-platform, ...  (the listing form's names)
#   items-<i>-sale-on, items-<i>-sale-sale_price, ...  (the sale form's names)

ITEM_CARD_NAME = re.compile(r'items-(\d+)-name')
LISTING_FIELDS = ('platform', 'listing_id', 'listing_url', 'listing_price')


def form_group(form, prefix):
    # The fields under one prefix, without it: "items-0-name" -> "name"
    return {key[len(prefix):]: value for key, value in form.items() if key.startswith(prefix)}


def parse_item_cards(form):
    cards = []
    indices = sorted({int(match.group(1)) for key in form if (match := ITEM_CARD_NAME.fullmatch(key))})
    for i in indices:
        prefix = f'items-{i}-'
        listing_name = re.compile(rf'{prefix}listings-(\d+)-platform')
        listing_indices = sorted({int(match.group(1)) for key in form if (match := listing_name.fullmatch(key))})
        cards.append({
            'index': i,
            'fields': form_group(form, prefix),
            'listings': [{'index': j, 'fields': form_group(form, f'{prefix}listings-{j}-')} for j in listing_indices],
            'sale': form_group(form, f'{prefix}sale-') if form.get(f'{prefix}sale-on') else None,
        })
    return cards


def listing_is_blank(fields):
    # The date is filled in for you, so it doesn't count
    return not any(fields.get(field, '').strip() for field in LISTING_FIELDS)


def card_is_blank(card):
    # A card left empty is skipped, like an empty spreadsheet row
    return (not card['fields'].get('name', '').strip()
            and card['sale'] is None
            and all(listing_is_blank(listing['fields']) for listing in card['listings']))


def validate_item_cards(cards):
    # Check every card before saving anything, so a mistake never saves half a purchase
    errors = []
    for number, card in enumerate(cards, start=1):
        if card_is_blank(card):
            continue
        fields = card['fields']
        name = fields.get('name', '').strip()
        label = name or _('Item {number}', number=number)
        if not name:
            errors.append(_('{item}: the item name is required.', item=label))

        quantity = parse_quantity(fields.get('quantity'))
        if quantity is None:
            errors.append(_('{item}: quantity must be a positive whole number.', item=label))

        if any(not listing_is_blank(l['fields']) and not l['fields'].get('platform', '').strip()
               for l in card['listings']):
            errors.append(_('{item}: every listing needs a platform.', item=label))

        sale = card['sale']
        if sale is not None:
            if not sale.get('sale_price', '').strip():
                errors.append(_('{item}: the sale needs a sale price.', item=label))
            sale_quantity = parse_quantity(sale.get('quantity'))
            if quantity is not None and (sale_quantity is None or sale_quantity > quantity):
                errors.append(_('{item}: sale quantity must be between 1 and {maximum}.', item=label, maximum=quantity))
    return errors


def save_item_cards(purchase, user_id, cards):
    # Run validate_item_cards first. Returns the number of items added.
    count = 0
    for card in cards:
        if card_is_blank(card):
            continue
        fields = card['fields']
        item = create_purchase_item(
            purchase, user_id, fields.get('name', ''),
            category=fields.get('category'),
            brand=fields.get('brand'),
            condition=fields.get('condition'),
            shelf_id=fields.get('shelf_id'),
            notes=fields.get('notes'),
            quantity=parse_quantity(fields.get('quantity')),
        )
        db.session.add(item)

        listings = {}
        for listing in card['listings']:
            if not listing_is_blank(listing['fields']):
                listings[str(listing['index'])] = add_listing(item, listing['fields'])

        sale = card['sale']
        if sale is not None:
            # The sale picks one of this card's listings by its number
            add_sale(item, sale, parse_quantity(sale.get('quantity')), listings.get(sale.get('listing', '')))
        count += 1
    return count

@app.context_processor
def inject_today():
    return {"today": date.today().isoformat()}

@app.context_processor
def inject_currency():
    # Every template renders money signs via {{ currency_symbol }}, so
    # user-entered text (item names, bundle names, ...) is never rewritten.
    symbol, code = currency_display()
    return {"currency_symbol": symbol, "currency_code": code}

@app.context_processor
def inject_registration():
    return {"allow_registration": ALLOW_REGISTRATION}

# CSRF protection: refuse form posts sent from another website
# https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html#using-standard-headers-to-verify-origin
@app.before_request
def check_same_origin():
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        return
    source = request.headers.get('Origin') or request.headers.get('Referer')
    if not source or urlparse(source).netloc != request.host:
        abort(403)

# Templates translate their UI text with {{ _('...') }}. A global (rather than
# a context processor) so imported macros can use it too.
app.jinja_env.globals["_"] = _

# Wrap the parts of text that match the search in <mark>, escaping the rest
@app.template_filter('highlight')
def highlight(text, q):
    if not text or not q:
        return text
    parts = re.split(f'({re.escape(q)})', str(text), flags=re.IGNORECASE)
    return Markup('').join(
        Markup('<mark>{}</mark>').format(part) if i % 2 else escape(part)
        for i, part in enumerate(parts)
    )

@app.context_processor
def inject_language():
    language = get_language()
    return {
        "current_language": language,
        "html_lang": HTML_LANG[language],
        "languages": LANGUAGES,
        "js_translations": js_translations(),
    }

# Rate limit hit: show a message on the page instead of a bare 429 error.
# The redirect is a GET, which is never limited, so it cannot loop.
@app.errorhandler(429)
def too_many_requests(error):
    # The sheet sync and backup are limited GETs, so redirecting them would loop
    if request.endpoint in ('sync_sheet', 'backup_database'):
        return error
    flash(_('Too many attempts. Please wait a moment and try again.'), 'danger')
    return redirect(request.path)


##########################
#        ROUTES
##########################

# Installable app (PWA): https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps
# The service worker only controls pages at or below its own URL, so it is
# served from the site root instead of /static/.
@app.route('/sw.js')
def service_worker():
    response = send_from_directory(app.static_folder, 'sw.js', mimetype='text/javascript')
    response.headers['Cache-Control'] = 'no-cache'
    return response

# Fallback page the service worker shows when there is no connection
@app.route('/offline')
def offline():
    return render_template('offline.html')

@app.route('/')
@login_required
def index():
    # Load the related rows up front, so the profit calculations below
    # don't run a separate query for every item and purchase
    items = Item.query.filter_by(user_id=current_user.id).options(
        selectinload(Item.purchase), selectinload(Item.sales), selectinload(Item.listings),
    ).all()
    purchases = Purchase.query.filter_by(user_id=current_user.id).options(
        selectinload(Purchase.items).selectinload(Item.sales),
    ).all()
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

    # Bundle sales have no profit of their own, since the cost belongs to the
    # whole bundle. Each one only counts as profit for the part of its proceeds
    # that comes after the bundle's revenue has covered its cost.
    bundle_sale_profit = {}
    bundle_sales = {}
    for sale in sales:
        if sale.item.is_bundle:
            bundle_sales.setdefault(sale.item.purchase, []).append(sale)
    for purchase, purchase_sales in bundle_sales.items():
        cost = purchase.total_cost
        revenue = Decimal("0.00")
        # Undated sales still count towards the cost, after the dated ones
        for sale in sorted(purchase_sales, key=lambda s: (s.sale_date is None, s.sale_date or date.min, s.id)):
            before = max(revenue - cost, Decimal("0.00"))
            revenue += sale.net_proceeds
            bundle_sale_profit[sale.id] = max(revenue - cost, Decimal("0.00")) - before

    # Add up the profit and net revenue of each sale into its month.
    monthly_profit = {label: 0 for label in chart_labels}
    monthly_bundle_profit = {label: 0 for label in chart_labels}
    monthly_revenue = {label: 0 for label in chart_labels}
    monthly_bundle_revenue = {label: 0 for label in chart_labels}
    for sale in sales:
        if not sale.sale_date:
            continue
        label = sale.sale_date.strftime("%Y-%m")
        if label not in monthly_profit:
            continue
        if sale.item.is_bundle:
            monthly_bundle_revenue[label] += float(sale.net_proceeds)
            monthly_bundle_profit[label] += float(bundle_sale_profit[sale.id])
        else:
            monthly_revenue[label] += float(sale.net_proceeds)
        if sale.profit is not None:
            monthly_profit[label] += float(sale.profit)
    # Profit is split the same way as revenue, so bundles stack on top
    chart_values = [round(monthly_profit[label], 2) for label in chart_labels]
    bundle_chart_values = [round(monthly_bundle_profit[label], 2) for label in chart_labels]
    # Revenue is split so the chart can stack bundle sales on top of single items
    revenue_values = [round(monthly_revenue[label], 2) for label in chart_labels]
    bundle_revenue_values = [round(monthly_bundle_revenue[label], 2) for label in chart_labels]

    return render_template(
        'index.html',
        last_month_profit=round(last_month_profit, 2),
        months=months,
        chart_labels=chart_labels,
        chart_values=chart_values,
        bundle_chart_values=bundle_chart_values,
        revenue_values=revenue_values,
        bundle_revenue_values=bundle_revenue_values,
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
        query = query.filter(item_search_filter(q))

    # Bare /inventory shows items on sale; links and searches with filters show all statuses
    status = request.args.get('status', 'all' if request.args else ItemStatus.ON_SALE.value)
    if status and status != 'all':
        try:
            status_enum = ItemStatus(status)
        except ValueError:
            status_enum = None
            flash(_('Status returned None'), 'danger')

        if status_enum is not None:
            query = query.filter(Item.status == status_enum)

    shelf_id = request.args.get("shelf_id")
    if shelf_id and shelf_id != 'all':
        try:
            query = query.filter(Item.shelf_id == int(shelf_id))
        except ValueError:
            shelf_id = None

    category = request.args.get("category")
    if category and category != 'all':
        query = query.filter(Item.category == category)

    sort = request.args.get("sort", "newest")
    if sort == "oldest":
        query = query.order_by(Item.created_at.asc())
    else:
        query = query.order_by(Item.created_at.desc())

    results = query.options(
        selectinload(Item.purchase), selectinload(Item.shelf),
        selectinload(Item.sales), selectinload(Item.listings),
    ).all()

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
    categories = get_used_values(Item, 'category', current_user.id)

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


#    Inventory - Search preview

# Suggestions shown under the navbar search while typing (AI-generated with Claude, see
# static/js/search_preview.js). Returns an HTML fragment, so it reuses the templates'
# translations and badges.
@app.route('/search/preview')
@login_required
def search_preview():
    q = request.args.get('q', '').strip()[:100]
    if not q:
        return ''
    pattern = f'%{q}%'
    match = item_search_filter(q)

    # Best matches first: the exact ID, name or listing ID, then names that
    # start with the text, then names with a word that starts with it
    exact = [
        func.lower(Item.name) == q.lower(),
        Item.id.in_(select(Listing.item_id).where(func.lower(Listing.listing_id) == q.lower())),
    ]
    code = parse_item_code(q)
    if code is not None:
        exact.append(Item.id == code)
    relevance = case(
        (or_(*exact), 0),
        (Item.name.ilike(f'{q}%'), 1),
        (Item.name.ilike(f'% {q}%'), 2),
        else_=3,
    )
    # Items that can still be sold come before sold and written-off ones
    finished = case((Item.status.in_([ItemStatus.SOLD, ItemStatus.WRITTEN_OFF]), 1), else_=0)
    items = (
        Item.query.filter(Item.user_id == current_user.id, match)
        .options(joinedload(Item.shelf))
        .order_by(relevance, finished, Item.created_at.desc())
        .limit(5)
        .all()
    )

    # How many items match in each status, for the "See results" links
    status_counts = dict(
        db.session.query(Item.status, func.count(Item.id))
        .filter(Item.user_id == current_user.id, match)
        .group_by(Item.status)
        .all()
    )

    # The listing whose ID matched, shown under the item name
    matched_listings = {}
    if items:
        listings = Listing.query.filter(
            Listing.item_id.in_([item.id for item in items]),
            Listing.listing_id.ilike(pattern),
        )
        for listing in listings:
            matched_listings.setdefault(listing.item_id, listing)

    # Bundles by name or seller. A single purchase is named after its item,
    # which is already listed above, so those only match by seller.
    item_count = select(func.count(Item.id)).where(Item.purchase_id == Purchase.id).scalar_subquery()
    purchases = (
        db.session.query(Purchase, item_count)
        .filter(
            Purchase.user_id == current_user.id,
            or_(
                Purchase.seller.ilike(pattern),
                and_(Purchase.purchase_type == PurchaseType.BUNDLE, Purchase.name.ilike(pattern)),
            ),
        )
        .order_by(Purchase.date.desc(), Purchase.id.desc())
        .limit(3)
        .all()
    )

    shelves = (
        Shelf.query.filter(Shelf.user_id == current_user.id, Shelf.name.ilike(pattern))
        .order_by(Shelf.name)
        .limit(3)
        .all()
    )
    categories = [
        category for (category,) in
        db.session.query(Item.category)
        .filter(Item.user_id == current_user.id, Item.category.ilike(pattern))
        .distinct()
        .order_by(Item.category)
        .limit(3)
    ]

    return render_template(
        'search_preview.html',
        q=q,
        items=items,
        matched_listings=matched_listings,
        total_count=sum(status_counts.values()),
        on_sale_count=status_counts.get(ItemStatus.ON_SALE, 0),
        purchases=purchases,
        shelves=shelves,
        categories=categories,
    )


#    Inventory - Item

@app.route('/inventory/<int:item_id>')
@login_required
def view_item(item_id):

    item = Item.query.filter_by(id=item_id, user_id=current_user.id).first()
    if not item:
        flash(_('Invalid item'), 'danger')
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
        flash(_('Quantity must be a whole number of at least {minimum}.', minimum=minimum_quantity), 'danger')
        return redirect(url_for('view_item', item_id=item.id))
    item.quantity = quantity
    item.category = request.form.get('category', '').strip() or None
    item.brand = request.form.get('brand', '').strip() or None
    item.condition = request.form.get('condition', '').strip() or None
    item.shelf_id = owned_shelf_id(request.form.get('shelf_id'), current_user.id)
    status = request.form.get('status')

    # Change item status. The field is absent when the status is automatic.
    if status is not None:
        try:
            new_status = ItemStatus(status)
        except ValueError:
            flash(_("Invalid status: {status}", status=repr(status)), "danger")
            return redirect(url_for('view_item', item_id=item.id))
        # Sold and Written Off only come from recording a sale or a write-off
        if new_status == ItemStatus.SOLD:
            flash(_('Items are marked Sold automatically when a sale is recorded.'), 'warning')
            return redirect(url_for('view_item', item_id=item.id))
        if new_status == ItemStatus.WRITTEN_OFF:
            flash(_('Use "Write off" on the item to record it as a loss.'), 'warning')
            return redirect(url_for('view_item', item_id=item.id))
        item.status = new_status

    item.notes = request.form.get('notes', '').strip()
    refresh_item_status(item)
    db.session.commit()
    flash(_('Item updated.'), 'success')
    return redirect(url_for('view_item', item_id=item.id))


@app.route('/items/<int:item_id>/delete', methods=["POST"])
@login_required
def delete_item(item_id):
    item = Item.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()

    purchase = item.purchase
    purchase_page = url_for("view_purchase", purchase_id=purchase.id)
    # A purchase left without items would only hold a stray cost, so it goes too
    # (deleting the purchase also deletes the item)
    deleting_purchase = len(purchase.items) == 1
    if deleting_purchase:
        db.session.delete(purchase)
    else:
        # Convert purchase type to Single if needed
        if purchase.purchase_type == PurchaseType.BUNDLE and len(purchase.items) == 2:
            purchase.purchase_type = PurchaseType.SINGLE
        db.session.delete(item)
    db.session.commit()
    flash(_("Item and its purchase deleted.") if deleting_purchase else _("Item deleted."), "success")

    # Redirect to current page, unless that page was deleted
    referrer = request.referrer
    if referrer:
        parsed_referrer = urlparse(referrer)
        if parsed_referrer.netloc in ("", request.host):
            if deleting_purchase and parsed_referrer.path == purchase_page:
                return redirect(url_for("purchases"))
            if parsed_referrer.path != url_for("view_item", item_id=item_id):
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
    query = query.options(selectinload(Purchase.items).selectinload(Item.sales))
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
    shelves = Shelf.query.filter_by(user_id=current_user.id).order_by(Shelf.name).all()
    purchase_type = request.args.get('purchase_type', 'single').lower()
    if purchase_type not in ('single', 'bundle'):
        purchase_type = 'single'
    cards = []

    if request.method == 'POST':
        purchase_type = next((t for t in PurchaseType
                              if t.value.lower() == request.form.get('purchase_type', '').strip().lower()), None)
        if purchase_type is None:
            return _('Invalid purchase type submitted'), 400

        # "Save without items" leaves the items for later, on the add-items page
        save_items = 'no_items' not in request.form
        cards = parse_item_cards(request.form)
        filled_cards = [card for card in cards if not card_is_blank(card)]
        errors = validate_item_cards(cards) if save_items else []
        if save_items and not filled_cards:
            errors.insert(0, _('Add at least one item, or save the purchase without items.'))

        if not errors:
            # A single purchase holds one item, so more than one makes it a bundle
            if save_items and len(filled_cards) > 1:
                purchase_type = PurchaseType.BUNDLE

            raw_purchase_date = request.form.get('date')
            purchase = Purchase(
                user_id=current_user.id,
                date=parse_date(raw_purchase_date) if raw_purchase_date else None,
                name=request.form.get('name', '').strip() or None,
                seller=request.form.get('seller', '').strip() or None,
                platform=request.form.get('platform', '').strip() or None,
                purchase_type=purchase_type,
                purchase_price=parse_decimal(request.form.get('purchase_price')),
                shipping_cost=parse_decimal(request.form.get('shipping_cost')),
                notes=request.form.get('purchaseNotes', '').strip() or None,
            )
            db.session.add(purchase)
            db.session.flush()

            count = save_item_cards(purchase, current_user.id, cards) if save_items else 0
            db.session.commit()
            if count:
                flash(_('{count} item(s) added to the purchase.', count=count), 'success')
            else:
                flash(_('Purchase saved.'), 'success')
            return redirect(url_for('view_purchase', purchase_id=purchase.id))

        # Show the form again with everything that was typed
        for error in errors:
            flash(error, 'danger')
        purchase_type = purchase_type.value.lower()

    return render_template(
        "purchases/purchases_new.html",
        shelves=shelves,
        purchase_type=purchase_type,
        form=request.form,
        cards=cards,
        **get_purchase_form_options(current_user.id),
    )

# The type is now picked on the new purchase page itself
@app.route("/purchases/new/type")
@login_required
def choose_purchase_type():
    return redirect(url_for('new_purchase'))


@app.route('/purchases/<int:purchase_id>')
@login_required
def view_purchase(purchase_id):
    purchase = Purchase.query.filter_by(id=purchase_id, user_id=current_user.id).options(
        selectinload(Purchase.items).selectinload(Item.sales),
    ).first_or_404()

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
    flash(_('Purchase updated.'), 'success')
    return redirect(url_for('view_purchase', purchase_id=purchase.id))

@app.route("/purchases/<int:purchase_id>/add", methods=["GET", "POST"])
@login_required
def add_items(purchase_id):
    purchase = Purchase.query.filter_by(
        id=purchase_id,
        user_id=current_user.id
    ).first_or_404()

    single_purchase = purchase.purchase_type == PurchaseType.SINGLE
    cards = []

    if request.method == 'POST':
        cards = parse_item_cards(request.form)
        filled_count = sum(1 for card in cards if not card_is_blank(card))
        errors = validate_item_cards(cards)
        if not filled_count:
            errors.insert(0, _('Add at least one item to this bundle.'))

        if not errors:
            # Convert a Single to Bundle when the completed purchase has multiple items.
            if single_purchase and len(purchase.items) + filled_count > 1:
                purchase.purchase_type = PurchaseType.BUNDLE

            count = save_item_cards(purchase, current_user.id, cards)
            db.session.commit()
            flash(_('{count} item(s) added to the purchase.', count=count), 'success')
            return redirect(url_for('view_purchase', purchase_id=purchase.id))

        for error in errors:
            flash(error, 'danger')

    return render_template(
        "purchases/purchases_add_items.html",
        purchase=purchase,
        shelves=Shelf.query.filter_by(user_id=current_user.id).order_by(Shelf.name).all(),
        form=request.form,
        cards=cards,
        single_purchase=single_purchase,
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
            flash(_('Please write a shelf name'), 'danger')
        elif Shelf.query.filter_by(user_id=current_user.id, name=name).first() is not None:
            flash(_('A box with this name already exists.'), 'danger')
        else:
            db.session.add(Shelf(user_id=current_user.id, name=name, description=description))
            db.session.commit()
            flash(_("Shelf added."), "success")
        return redirect(url_for("shelves"))

    all_shelves = Shelf.query.filter_by(user_id=current_user.id).order_by(Shelf.name).all()
    return render_template('shelves.html', shelves=all_shelves)

@app.route('/shelves/<int:shelf_id>/delete', methods=["POST"])
@login_required
def delete_shelf(shelf_id):
    # Also make sure the user id matches for security
    shelf = Shelf.query.filter_by(id=shelf_id, user_id=current_user.id).first_or_404()
    if shelf.items:
        flash(_("Cannot delete a shelf that still has items on it."), "danger")

    ##############
    ##############
    # ADD option for it to automatically delete all items on the shelf?
    ##############
    ##############
    
    else:
        db.session.delete(shelf)
        db.session.commit()
        flash(_("Shelf deleted."), "success")
    return redirect(url_for("shelves"))


#########################
#       Listings

@app.route('/items/<int:item_id>/listings/new', methods=["GET", "POST"])
@login_required
def new_listing(item_id):
    item = Item.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()

    if request.method == "POST":
        if not request.form.get("platform", "").strip():
            flash(_("Platform is required."), "danger")
            return render_template("listings/listings_new.html", item=item)

        add_listing(item, request.form)
        db.session.commit()
        flash(_("Listing added."), "success")
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
        flash(_("Platform is required."), "danger")
        return redirect(url_for("view_item", item_id=listing.item_id))

    listing.platform = platform
    listing.listing_id = request.form.get("listing_id", "").strip() or None
    listing.listing_url = request.form.get("listing_url", "").strip() or None
    listing.listing_price = parse_decimal(request.form.get("listing_price"), default=None)
    listing.date_listed = parse_date(request.form.get("date_listed"), default=listing.date_listed)

    db.session.commit()
    flash(_("Listing updated."), "success")
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
    flash(_("Listing deleted."), "success")
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
            flash(_('Listings are marked Sold automatically when a sale is recorded.'), 'warning')
            return redirect(url_for('view_item', item_id=listing.item_id))
        listing.status = new_status
    except (ValueError, TypeError):
        flash(_("Invalid listing status."), "danger")
        return redirect(url_for("view_item", item_id=listing.item_id))

    db.session.commit()
    flash(_("Listing status updated."), "success")
    return redirect(url_for("view_item", item_id=listing.item_id))


#########################
#       Sales

@app.route("/items/<int:item_id>/sale/new", methods=["GET", "POST"])
@login_required
def new_sale(item_id):
    item = Item.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    if item.available_quantity <= 0:
        flash(_("There are no available units to sell."), "warning")
        return redirect(url_for("view_item", item_id=item.id))
    if item.sale is not None:
        flash(_("This item has already been sold."), "warning")
        return redirect(url_for("view_item", item_id=item.id))

    if request.method == "POST":
        listing_id = request.form.get("listing_id")
        sale_quantity = parse_quantity(request.form.get("quantity"))
        if sale_quantity is None or sale_quantity > item.available_quantity:
            flash(_("Sale quantity must be between 1 and {maximum}.", maximum=item.available_quantity), "danger")
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
                flash(_("Invalid listing selected."), "danger")
                return render_template("sales/sales_new.html", item=item)

        add_sale(item, request.form, sale_quantity, listing)
        db.session.commit()
        flash(_("Sale recorded."), "success")
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
            flash(_("Invalid listing selected."), "danger")
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
        flash(_("Sale quantity must be between 1 and {maximum}.", maximum=max_quantity), "danger")
        return redirect(url_for("view_item", item_id=item.id))
    if sale.item_returned:
        # A returned sale doesn't hold any stock, so it can't change quantities
        sale.quantity = sale_quantity
        db.session.commit()
        flash(_("Sale updated."), "success")
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
    flash(_("Sale updated."), "success")
    return redirect(url_for("view_item", item_id=item.id))


@app.route("/sales/<int:sale_id>/refund", methods=["POST"])
@login_required
def refund_sale(sale_id):
    sale = Sale.query.join(Item).filter(Sale.id == sale_id, Item.user_id == current_user.id).first_or_404()
    item = sale.item

    refund_amount = parse_decimal(request.form.get("refund_amount"))
    if refund_amount < 0:
        flash(_("Refund amount can't be negative."), "danger")
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
            flash(_("The returned units have been sold or written off since, so this return can't be undone."), "danger")
            return redirect(url_for("view_item", item_id=item.id))
        item.quantity_sold += sale.quantity

    sale.refund_amount = refund_amount
    sale.item_returned = item_returned
    refresh_item_status(item)
    db.session.commit()
    flash(_("Refund saved.") if sale.is_refunded else _("Refund removed."), "success")
    return redirect(url_for("view_item", item_id=item.id))


# For sales recorded by mistake. A sale that really happened and was undone is a refund.
@app.route("/sales/<int:sale_id>/delete", methods=["POST"])
@login_required
def delete_sale(sale_id):
    sale = Sale.query.join(Item).filter(Sale.id == sale_id, Item.user_id == current_user.id).first_or_404()
    item = sale.item

    if not sale.item_returned:
        # Its units go back into stock, and its listing is live again
        item.quantity_sold = max(item.quantity_sold - sale.quantity, 0)
        if sale.listing and sale.listing.status == ListingStatus.SOLD:
            sale.listing.status = ListingStatus.ACTIVE

    item.sales.remove(sale)
    db.session.delete(sale)
    refresh_item_status(item)
    db.session.commit()
    flash(_("Sale deleted."), "success")
    return redirect(url_for("view_item", item_id=item.id))


@app.route("/items/<int:item_id>/write-off", methods=["POST"])
@login_required
def write_off_item(item_id):
    item = Item.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    if item.available_quantity <= 0:
        flash(_("There are no available units to write off."), "warning")
        return redirect(url_for("view_item", item_id=item.id))

    # Whole item only: every remaining unit is written off
    item.quantity_written_off += item.available_quantity
    for listing in item.listings:
        if listing.status == ListingStatus.ACTIVE:
            listing.status = ListingStatus.REMOVED
    refresh_item_status(item)
    db.session.commit()
    flash(_("Item written off. Its cost now counts as a loss."), "success")
    return redirect(url_for("view_item", item_id=item.id))


@app.route("/items/<int:item_id>/write-off/undo", methods=["POST"])
@login_required
def undo_write_off(item_id):
    item = Item.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    item.quantity_written_off = 0
    refresh_item_status(item)
    db.session.commit()
    flash(_("Write-off undone. The units are back in inventory."), "success")
    return redirect(url_for("view_item", item_id=item.id))


#########################
#     Authentication

# Language toggle on the login page, so the language can be picked before logging in
@app.route('/language', methods=['POST'])
def set_language():
    language = request.form.get('language', '').strip()
    response = redirect(url_for('login'))
    if language in LANGUAGES:
        response.set_cookie(LANGUAGE_COOKIE, language, max_age=60 * 60 * 24 * 365, samesite='Lax')
    return response

# https://flask-login.readthedocs.io/en/latest/#login-example
@app.route('/login', methods=['GET', 'POST'])
# Only failed attempts count (a successful login redirects), per IP and per username
@limiter.limit("5 per minute;20 per hour", methods=["POST"],
               deduct_when=lambda response: response.status_code != 302)
@limiter.limit("10 per hour", methods=["POST"],
               key_func=lambda: request.form.get('username', '').strip().lower(),
               deduct_when=lambda response: response.status_code != 302)
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
            flash(_('Invalid username or password.'), 'danger')
        else:
            # Log-in the user
            login_user(user, remember=bool(request.form.get('remember')))
            flash(_('Logged in successfully.'), 'success')
            return redirect(url_for('index'))

    # Only offer the button when the demo account actually exists in this database
    demo_login = None
    if DEMO_LOGIN and User.query.filter_by(username=DEMO_USERNAME).first():
        demo_login = {'username': DEMO_USERNAME, 'password': DEMO_PASSWORD}
    return render_template("login.html", demo_login=demo_login)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash(_('Logged out successfully.'), 'success')
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
@limiter.limit("3 per hour", methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if not ALLOW_REGISTRATION:
        flash(_('Registration is closed.'), 'warning')
        return redirect(url_for('login'))

    if request.method == "POST":
        # Sanitize inputs
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        repeat_password = request.form.get('repeat_password', '')

        # Validate the form
        if not username or not password:
            flash(_('Please insert username and password.'), 'danger')
        elif len(password) < 8:
            flash(_('Password must be at least 8 characters.'), 'danger')
        elif password != repeat_password:
            flash(_('Passwords do not match.'), 'danger')
        elif User.query.filter_by(username=username).first():
            flash(_('That username is already taken.'), 'danger')

        else:
            # Complete registration
            user = User(username=username, password_hash=generate_password_hash(password))
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
        currency = request.form.get('currency', '').strip().upper()
        language = request.form.get('language', '').strip()
        if currency not in CURRENCY_SYMBOLS:
            flash(_('Please choose a valid currency.'), 'danger')
            return redirect(url_for('user'))
        if language not in LANGUAGES:
            flash(_('Please choose a valid language.'), 'danger')
            return redirect(url_for('user'))

        # Persist the chosen cosmetic currency to the user's account.
        current_user.currency = currency
        db.session.commit()

        # The language lives in a cookie, so no database column is needed.
        # Setting g.language makes the flash below use the new language.
        g.language = language
        flash(_('Preferences saved.'), 'success')
        response = redirect(url_for('user'))
        response.set_cookie(LANGUAGE_COOKIE, language, max_age=60 * 60 * 24 * 365, samesite='Lax')
        return response
    return render_template('user.html')

@app.route('/user/delete-database', methods=['POST'])
@login_required
def delete_database():
    try:
        reset_user_data(current_user)
        flash(_('Your data was deleted.'), 'success')
    except Exception:
        db.session.rollback()
        app.logger.exception('Data reset failed')
        flash(_('Could not delete your data.'), 'danger')

    return redirect(url_for('user'))

@app.route('/user/import-csv', methods=['POST'])
@login_required
@limiter.limit("10 per hour", key_func=lambda: str(current_user.id))
def import_csv():
    csv_file = request.files.get('csv_file')
    if csv_file is None or not csv_file.filename:
        flash(_('Choose a CSV file to import.'), 'danger')
        return redirect(url_for('user'))

    try:
        result = process_csv(csv_file, current_user.id)
    except Exception:
        db.session.rollback()
        app.logger.exception('CSV import failed')
        flash(_('The CSV could not be imported.'), 'danger')
        return redirect(url_for('user'))

    message = _(
        "Imported {purchases} purchase(s) and {items} item(s).",
        purchases=result['purchases_created'],
        items=result['items_created'],
    )
    if result['errors']:
        return render_template('user.html', import_result=result)

    flash(message, 'success')
    return redirect(url_for('user'))

# The listing an exported item row shows: the one it sold on, else an active one, else any
def item_listing(item):
    if item.sale and item.sale.listing:
        return item.sale.listing
    active_listing = next(
        (listing for listing in item.listings if listing.status == ListingStatus.ACTIVE),
        None,
    )
    return active_listing or (item.listings[0] if item.listings else None)

@app.route('/user/export-csv')
@login_required
def export_csv():
    purchases = Purchase.query.filter_by(user_id=current_user.id).all()
    items = Item.query.filter_by(user_id=current_user.id).order_by(Item.id).options(
        selectinload(Item.purchase), selectinload(Item.listings),
        selectinload(Item.sales).selectinload(Sale.listing),
    ).all()

    def csv_money(value):
        return f"{value:.2f}" if value is not None else ""

    def csv_date(value):
        return value.isoformat() if value else ""

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


# Rows for the "App" tab of the Google Sheet, in the same column order as its Vendas tab
def sheet_rows(user_id):
    def money(value):
        return float(value) if value is not None else None

    def iso(value):
        return value.isoformat() if value else None

    items = Item.query.filter_by(user_id=user_id).order_by(Item.id).options(
        selectinload(Item.purchase), selectinload(Item.shelf), selectinload(Item.listings),
        selectinload(Item.sales).selectinload(Sale.listing),
    ).all()
    item_rows = []
    for item in items:
        purchase = item.purchase
        listing = item_listing(item)
        sale = item.sale
        single = purchase.purchase_type == PurchaseType.SINGLE
        item_rows.append([
            "Individual" if single else purchase.display_name,
            item.quantity,
            item.quantity_sold,
            item.name,
            iso(sale.sale_date if sale else None),
            item.status.value,
            (listing.platform if listing else None) or purchase.platform,
            item.shelf.name if item.shelf else None,
            money(purchase.total_cost / item.quantity) if single and item.quantity else None,
            money(listing.listing_price if listing else None),
            money(sale.sale_price if sale else None),
            money(item.realized_profit),
            listing.listing_url if listing else None,
            iso(purchase.date),
            money(sale.refund_amount if sale and sale.refund_amount else None),
            item.notes or None,
        ])

    bundles = Purchase.query.filter_by(user_id=user_id, purchase_type=PurchaseType.BUNDLE).order_by(Purchase.id).options(
        selectinload(Purchase.items).selectinload(Item.sales),
    ).all()
    bundle_rows = [
        [purchase.display_name, money(purchase.total_cost), money(purchase.total_revenue), money(purchase.profit)]
        for purchase in bundles
    ]
    return {"items": item_rows, "bundles": bundle_rows}


# Checks the "Authorization: Bearer <token>" header sent by the sheet's script
def bearer_token_matches(expected):
    token = request.headers.get('Authorization', '').removeprefix('Bearer ').strip()
    return secrets.compare_digest(token.encode(), expected.encode())


@app.route('/sync/sheet')
@limiter.limit("30 per hour")
def sync_sheet():
    if not SHEETS_SYNC_TOKEN or not SHEETS_SYNC_USER:
        abort(404)
    if not bearer_token_matches(SHEETS_SYNC_TOKEN):
        abort(401)
    user = User.query.filter_by(username=SHEETS_SYNC_USER).first_or_404()
    return jsonify(sheet_rows(user.id))


@app.route('/backup/database')
@limiter.limit("5 per hour")
def backup_database():
    if not BACKUP_TOKEN:
        abort(404)
    if not bearer_token_matches(BACKUP_TOKEN):
        abort(401)

    # SQLite's backup API takes a consistent copy even while other requests are writing
    handle, copy_path = tempfile.mkstemp(suffix='.db')
    os.close(handle)
    try:
        source = sqlite3.connect(DB_PATH)
        copy = sqlite3.connect(copy_path)
        try:
            source.backup(copy)
            check = copy.execute('PRAGMA integrity_check').fetchone()[0]
        finally:
            copy.close()
            source.close()
        # Never hand out a broken copy, or it would replace good backups
        if check != 'ok':
            app.logger.error('Backup integrity check failed: %s', check)
            abort(500)
        with open(copy_path, 'rb') as file:
            data = gzip.compress(file.read())
    finally:
        os.remove(copy_path)

    response = Response(data, mimetype='application/gzip')
    response.headers['Content-Disposition'] = (
        f'attachment; filename=resale-desk-{date.today().isoformat()}.db.gz'
    )
    return response
