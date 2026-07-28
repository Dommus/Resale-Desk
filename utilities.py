from datetime import datetime, date
from flask_login import LoginManager

# Login Manager
# https://flask-login.readthedocs.io/en/latest/
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to continue.'
login_manager.login_message_category = 'warning'


# Utility to proccess dates
def parse_date(value, default=None):
    if not value:
        return default or date.today()
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return default or date.today()

# Utility to proccess floating numbers
def parse_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default