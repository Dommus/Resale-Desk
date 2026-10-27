// Copies the Resale Desk data into the "App" tab of this spreadsheet.
// Paste into Extensions > Apps Script, then set two Script Properties
// (Project Settings > Script Properties):
//   SYNC_URL    e.g. https://<username>.pythonanywhere.com/sync/sheet
//   SYNC_TOKEN  the same value as SHEETS_SYNC_TOKEN on the server

const TAB_NAME = 'App';
const ITEM_HEADERS = [
  'Bundle', 'Quantity', 'Sold Quantity', 'Item', 'Sold date', 'Status',
  'Sales platform', 'Location', 'Buy price (unit)', 'Sell price (total)',
  'Sold price', 'Profit', 'URL', 'Bought date', 'Refund amount', 'Notes',
];
const BUNDLE_HEADERS = ['Bundle Name', 'Bundle Cost', 'Bundle Revenue', 'Bundle Profit'];
// Same layout as the Vendas tab: items in A-P, a blank column Q, bundles from R
const BUNDLE_COLUMN = 18;
// 1-based columns of the items table
const ITEM_MONEY_COLUMNS = [9, 10, 11, 12, 15];
const ITEM_DATE_COLUMNS = [5, 14];
const MONEY_FORMAT = '[$€]#,##0.00';

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Resale Desk')
    .addItem('Sync from app', 'syncFromApp')
    // From backup.gs
    .addItem('Back up now', 'backupNow')
    .addToUi();
}

function syncFromApp() {
  const props = PropertiesService.getScriptProperties();
  const url = props.getProperty('SYNC_URL');
  const token = props.getProperty('SYNC_TOKEN');
  const ui = SpreadsheetApp.getUi();
  if (!url || !token) {
    ui.alert('Set SYNC_URL and SYNC_TOKEN in Project Settings > Script Properties first.');
    return;
  }

  const response = UrlFetchApp.fetch(url, {
    headers: { Authorization: 'Bearer ' + token },
    muteHttpExceptions: true,
    followRedirects: false,
  });
  if (response.getResponseCode() !== 200) {
    ui.alert('Sync failed: the app answered ' + response.getResponseCode() + '.');
    return;
  }
  const data = JSON.parse(response.getContentText());

  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName(TAB_NAME) || spreadsheet.insertSheet(TAB_NAME);
  sheet.clear();

  const items = data.items.map(row => row.map((value, index) =>
    ITEM_DATE_COLUMNS.includes(index + 1) ? toDate(value) : blank(value)));
  writeTable(sheet, 1, ITEM_HEADERS, items);
  writeTable(sheet, BUNDLE_COLUMN, BUNDLE_HEADERS, data.bundles.map(row => row.map(blank)));

  if (items.length) {
    ITEM_MONEY_COLUMNS.forEach(column =>
      sheet.getRange(2, column, items.length, 1).setNumberFormat(MONEY_FORMAT));
    ITEM_DATE_COLUMNS.forEach(column =>
      sheet.getRange(2, column, items.length, 1).setNumberFormat('yyyy-mm-dd'));
  }
  if (data.bundles.length) {
    sheet.getRange(2, BUNDLE_COLUMN + 1, data.bundles.length, 3).setNumberFormat(MONEY_FORMAT);
  }
  sheet.setFrozenRows(1);

  const time = Utilities.formatDate(new Date(), spreadsheet.getSpreadsheetTimeZone(), 'HH:mm');
  spreadsheet.toast(
    'Synced ' + items.length + ' items and ' + data.bundles.length + ' bundles at ' + time + '.',
    'Resale Desk');
}

function writeTable(sheet, column, headers, rows) {
  sheet.getRange(1, column, 1, headers.length).setValues([headers]).setFontWeight('bold');
  if (rows.length) {
    sheet.getRange(2, column, rows.length, headers.length).setValues(rows);
  }
}

function blank(value) {
  return value === null ? '' : value;
}

// "2026-10-27" -> a sheet date. Built from its parts so the time zone can't shift the day.
function toDate(value) {
  if (!value) return '';
  const [year, month, day] = value.split('-').map(Number);
  return new Date(year, month - 1, day);
}
