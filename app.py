import os
from models import db, User

from flask import Flask, render_template, request, redirect, url_for, flash
# from sqlalchemy import create_engine
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash


# Configure App and Database (https://www.geeksforgeeks.org/python/declaring-models-in-flask/)
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
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

# Create the physical database files
with app.app_context():
    db.create_all()

# Routes
# ------
@app.route('/')
@login_required
def index():
    return render_template('index.html')

# Placeholder routes
@app.route('/inventory')
@login_required
def inventory():
    return render_template('index.html')

@app.route('/purchases')
@login_required
def purchases():
    return render_template('index.html')

@app.route('/shelves')
@login_required
def shelves():
    return render_template('index.html')


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
