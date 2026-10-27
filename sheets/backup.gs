// Saves a daily copy of the Resale Desk database to Google Drive.
// Add this file to the same Apps Script project as sync.gs, then set two
// Script Properties (Project Settings > Script Properties):
//   BACKUP_URL    e.g. https://<username>.pythonanywhere.com/backup/database
//   BACKUP_TOKEN  the same value as BACKUP_TOKEN on the server
// Finally run installDailyBackup once from the editor.

const BACKUP_FOLDER = 'Resale Desk backups';
const KEEP_DAYS = 30;

function backupDatabase() {
  const props = PropertiesService.getScriptProperties();
  const url = props.getProperty('BACKUP_URL');
  const token = props.getProperty('BACKUP_TOKEN');
  if (!url || !token) {
    throw new Error('Set BACKUP_URL and BACKUP_TOKEN in Project Settings > Script Properties first.');
  }

  const response = UrlFetchApp.fetch(url, {
    headers: { Authorization: 'Bearer ' + token },
    muteHttpExceptions: true,
    followRedirects: false,
  });
  // Throwing makes Google email you when the nightly backup fails
  if (response.getResponseCode() !== 200) {
    throw new Error('Backup failed: the app answered ' + response.getResponseCode() + '.');
  }
  const blob = response.getBlob();
  if (blob.getBytes().length === 0) {
    throw new Error('Backup failed: the app sent an empty file.');
  }

  const folder = backupFolder();
  const day = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd');
  const file = folder.createFile(blob.setName('resale-desk-' + day + '.db.gz'));
  deleteOldBackups(folder);
  return file;
}

// Menu item: back up now and say so
function backupNow() {
  const file = backupDatabase();
  SpreadsheetApp.getActiveSpreadsheet().toast(
    'Saved ' + file.getName() + ' to "' + BACKUP_FOLDER + '" in Google Drive.', 'Resale Desk');
}

// Run once by hand. Running it again replaces the trigger instead of adding a second one.
function installDailyBackup() {
  ScriptApp.getProjectTriggers()
    .filter(trigger => trigger.getHandlerFunction() === 'backupDatabase')
    .forEach(trigger => ScriptApp.deleteTrigger(trigger));
  ScriptApp.newTrigger('backupDatabase').timeBased().everyDays(1).atHour(3).create();
}

function backupFolder() {
  const folders = DriveApp.getFoldersByName(BACKUP_FOLDER);
  return folders.hasNext() ? folders.next() : DriveApp.createFolder(BACKUP_FOLDER);
}

function deleteOldBackups(folder) {
  const cutoff = new Date(Date.now() - KEEP_DAYS * 24 * 60 * 60 * 1000);
  const files = folder.getFiles();
  while (files.hasNext()) {
    const file = files.next();
    if (file.getName().startsWith('resale-desk-') && file.getDateCreated() < cutoff) {
      file.setTrashed(true);
    }
  }
}
