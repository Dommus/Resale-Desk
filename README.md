# Resale Desk

A simple web app for keeping track of things you buy second-hand and resell on sites like Vinted, eBay or OLX. It shows what you have, where it is, what sold, and how much money you actually made.

It started as my CS50 final project ([video demo](https://www.youtube.com/watch?v=MQevm5aZ92I)) and is now the tool I use day to day.

## What it does

- **Purchases:** record what you bought and what it cost. A purchase can be one item, or a bundle of many items bought together for one price.
- **Shelves:** say where each item is stored, so you can find it later.
- **Listings:** note where an item is for sale, at what price, with a link to the ad.
- **Sales:** record the sale price, shipping and fees. The app works out the profit for you.
- **Refunds and write-offs:** if a buyer gets a refund, or an item gets lost, broken or kept, record it so your profit stays honest.
- **Dashboard:** your profit, a monthly chart, recent sales, best purchases, and items that still need listing.
- **Your data, your way:**
  - import from and export to CSV
  - optionally copy everything into a Google Sheet
  - pick your currency symbol
  - use it in English or Portuguese
  - light or dark theme
- **Works on your phone:** the tables turn into simple lists on small screens, and you can install it like an app.

## Try it on your computer

You need Python 3.

```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask run
```

Open the address it prints. To look around, log in as `demo` with password `cs50`, or create your own account.

## Put it online

It runs on a free [PythonAnywhere](https://www.pythonanywhere.com) account. Set these environment variables there:

| Variable | What it's for |
|---|---|
| `RESALE_DESK_PRODUCTION=1` | Turns on "live" mode: no sign-ups, no demo data, secure cookies |
| `SECRET_KEY` | A long random password the app uses to keep logins safe. Make one with `python -c "import secrets; print(secrets.token_hex(32))"` |
| `ALLOW_REGISTRATION=1` | Optional. Opens sign-ups for a moment, e.g. to create your own account |
| `DEMO_LOGIN=1` | Optional. Adds a one-click demo login. Anyone can then change the demo account's data |
| `SHEETS_SYNC_TOKEN`, `SHEETS_SYNC_USER` | Optional. Turn on the Google Sheets copy (see below) |

## Copy your data into Google Sheets

You can copy one account's data into a tab called `App` in a Google Sheet, whenever you click a button. Your other tabs aren't touched.

1. Make a token (a long random password): `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
2. On the server, set `SHEETS_SYNC_TOKEN` to that token and `SHEETS_SYNC_USER` to your username, then reload the app.
3. In your sheet, open **Extensions → Apps Script** and paste in [`sheets/sync.gs`](sheets/sync.gs).
4. In the script's **Project Settings → Script Properties**, add:
   - `SYNC_URL`: e.g. `https://<username>.pythonanywhere.com/sync/sheet`
   - `SYNC_TOKEN`: the same token
5. Reload the sheet and click **Resale Desk → Sync from app**. The first time, Google asks for permission.

Each sync replaces what's in the `App` tab.

## How it's built

- **Flask** (Python) for the web app, and **SQLite** for the database, through **SQLAlchemy**.
- **Bootstrap** for the look, plus a little custom CSS and JavaScript.

| File | What's in it |
|---|---|
| `app.py` | All the pages and what happens when you click things |
| `models.py` | The database tables, and the profit maths |
| `utilities.py` | Small helpers, and the CSV import |
| `translations.py` | The Portuguese translation |
| `templates/` | The HTML pages |
| `static/` | Styles, scripts, icons and the installable-app files |
| `sheets/sync.gs` | The Google Sheets script |

A few choices worth knowing:
- **A bundle's cost isn't split between its items.** If ten things cost €50 together, any split per item would be made up. So profit for a bundle is counted on the whole bundle.
- **Money is stored exactly** (as decimals, not floating point), so cents never go missing.
- **"Sold" and "Written off" are set automatically** when you record a sale or a write-off, so the numbers always match.

## Credits

Parts of this project were written with help from AI tools, mainly `static/js/table_controls.js` and most of the CSS. The design, data model and the rest of the app are my own work.
