# Resale Desk

#### Video Demo:  https://www.youtube.com/watch?v=MQevm5aZ92I

#### Description:

  

Resale Desk is a web application for people who buy second-hand items and resell them on marketplaces such as Vinted, eBay, OLX, etc. My family members have a reselling gig and everything was being tracked on a spreadsheet, but as the number of items grew it became hard to answer simple questions: how much profit did they make this month, which purchases paid off, what is sitting on a shelf without being listed anywhere, and how much money was lost on items that were damaged or refunded. Resale Desk replaces that spreadsheet with an inventory and sales system built with Python, Flask, SQLAlchemy and SQLite.

  

Each user has their own account. The workflow follows the life-cycle of an item: First you record a **purchase**: either a single item, or a bundle of several items bought together for one price. Items can be placed on **shelves** so you know where they are physically. Each item can have one or more **listings** on different platforms, with a price, URL and status (Active, Removed, Expired, Sold). When an item sells, you record a **sale** with the sale price, shipping collected and paid, and platform and payment fees. The app then calculates net proceeds, profit, ROI and margin. If a buyer gets a **refund**, you record it on the sale, and say whether the item came back or not. If an item will never sell because it was lost, damaged or kept, you **write it off**, and its cost is counted as a loss.

  

The **dashboard** brings it all together: realized profit, profit over the last 30 days, a monthly profit chart, net revenue, total invested, sell-through rate, average sale value, write-off losses, inventory by status, recent sales, the most profitable purchases, and a list of items that have stock but no active listing. Data can be **imported from and exported to CSV**, which is how I moved my existing spreadsheet into the app. Users can also pick the currency symbol used throughout the interface, and switch between light and dark themes.

  

#### Files

  

**`app.py`** is the Flask application. It configures the app, the SQLite database and Flask-Login, creates the tables on startup, and defines every route: the dashboard; the inventory list (with search, status, shelf and category filters, and sorting by date or profit) and the item page; creating purchases and adding items to them; shelves; creating, editing and deleting listings; recording and editing sales; refunds; write-offs and undoing them; login, logout and registration; and the user page with currency settings, CSV import, CSV export and database reset. It also contains `refresh_item_status`, which keeps an item's status consistent with how many units have been sold or written off.

  

**`models.py`** defines the database with SQLAlchemy's ORM: `User`, `Shelf`, `Purchase`, `Item`, `Listing` and `Sale`, plus the `ItemStatus`, `ListingStatus` and `PurchaseType` enums. Most of the business logic lives here as properties, for example `Purchase.total_cost`, `Purchase.profit`, `Item.available_quantity`, `Item.unit_cost`, `Item.write_off_loss`, `Item.realized_profit`, and `Sale.net_proceeds`, `Sale.profit`, `Sale.roi` and `Sale.margin`. Keeping the calculations in the models means every page shows the same numbers.

  

**`utilities.py`** holds the helpers shared by the routes: the login manager, currency symbols, functions that safely parse dates, money and quantities from forms, and `process_csv`. The importer reads a CSV with an items table and a separate bundles table, validates every row, creates purchases, items, shelves, listings and sales, and reports any rows it had to skip along with the reason.

  

**`templates/`** contains the Jinja templates. `layout.html` is the shared page with the navigation bar and theme toggle. `index.html` is the dashboard. `inventory/` has the inventory table and the item detail page, where listings, the sale, refunds and write-offs are managed. `purchases/` holds the purchase list, the purchase type choice, the forms for a new purchase and for adding items, and the purchase detail page. `listings/` and `sales/` hold the forms for new listings and sales. `shelves.html`, `user.html`, `login.html` and `register.html` cover the remaining pages, and `helpers/form_macros.html` has a macro for inputs that suggest values used before.

  

**`static/style.css`** is the app's styling on top of Bootstrap, including the colours for each status and the dark theme. **`static/js/suggestions.js`** powers the dropdowns that suggest previously used categories and brands. **`static/js/table_controls.js`** adds filtering, sorting, and draggable, hideable columns to the data tables, and remembers each table's column layout in the browser.

  

#### Design choices

  

**Purchases, items, listings and sales are separate tables.** It would have been simpler to have one big "item" row, like my spreadsheet. But an item can be listed on several platforms at once, and one purchase can contain many items, so modelling each concept separately avoids duplicated data and makes the profit calculations reliable.

  

**Bundle costs are not split between items.** When I buy ten items for €50, any split (€5 each, by weight, by expected value) would be invented. So a bundle's cost belongs to the purchase, and its profit is calculated as total revenue minus total cost. Single purchases calculate profit per item. This is why bundle items show "Bundle" instead of a profit figure.

  

**Money uses `Decimal`, never floats.** All amounts are stored with `Numeric(x, y)` and handled as Python `Decimal` values, to avoid the rounding errors floating point numbers can cause with currency. In fact, this was a later addition to address that very problem.

  

**Some statuses are automatic.** "Sold" and "Written Off" cannot be chosen by hand. They are set when a sale or write-off is recorded, so an item can never show as sold without a sale behind it.

  

**Losses are recorded as events, not just statuses.** At first I had "Refunded" and "Not Sold" statuses, but they did not affect the numbers, so unsold items quietly disappeared from the profit. Now a refund is part of the sale it belongs to (amount, and whether the item came back), and a write-off removes the remaining units and counts their cost as a loss. This follows how sales software usually treats returns and inventory write-offs.

  

**SQLAlchemy instead of raw SQL.** The course used the CS50 SQL library, but I wanted to learn an ORM. It let me define the relationships once and put calculations on the models as properties.

  

**Settings live in the database.** The currency preference used to be stored in a cookie, which meant it was lost on another browser. I moved it to the `User` table so it follows the account.

  

#### How to run it

  

```

python -m venv .venv

source .venv/bin/activate

pip install -r requirements.txt

flask run

```

  

The database includes a demo account. Log in as `demo` with password `cs50` to explore it, or simply create a fresh empty account.

Your own data can be cleared on the `/user` page.

#### Deploying

On a public server (e.g. PythonAnywhere), set these environment variables:

- `RESALE_DESK_PRODUCTION=1`: closes registration, skips the demo data and sends cookies over HTTPS only
- `SECRET_KEY`: a long random string, e.g. from `python -c "import secrets; print(secrets.token_hex(32))"`
- `ALLOW_REGISTRATION=1` (optional): reopen registration temporarily to create an account

  

#### Use of AI

  

As allowed for the final project, I used AI tools to help with parts of this project, and those parts are cited in the code comments. The script `static/js/table_controls.js` was AI-generated, because it is a quality-of-life feature that would have taken a lot of time (complex with big scope) without teaching me much about my main goals for this project. Most CSS was AI generated. I also initially used Claude to outline the project's skeleton and ensure usage of the correct tools. The overall design, the data model and the rest of the application are my own work.