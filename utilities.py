from datetime import datetime, date
from decimal import Decimal, InvalidOperation
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

# Utility to process currency values without introducing binary floating-point
# rounding errors.
def parse_decimal(value, default=Decimal("0.00")):
    if value is None or value == '':
        return default
    try:
        parsed = Decimal(str(value))
        return parsed if parsed.is_finite() else default
    except (InvalidOperation, TypeError, ValueError):
        return default
