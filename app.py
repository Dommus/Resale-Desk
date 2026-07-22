import os
from models import db
# from sqlalchemy import create_engine
from flask_sqlalchemy import SQLAlchemy
from flask import Flask, render_template, request, redirect, url_for


# Configure App and Database (https://www.geeksforgeeks.org/python/declaring-models-in-flask/)
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Find the absolute path to the directory with the current Python script
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
# Create instance directory
os.makedirs(os.path.join(BASE_DIR, "instance"), exist_ok=True)

# Bind db object to this app instance
db.init_app(app)

# Create the physical database files
with app.app_context():
    db.create_all()

@app.route("/")
def index():
    print("BASE_DIR = " + BASE_DIR)
    return render_template("index.html")

@app.route("/inventory")
def inventory():
    return