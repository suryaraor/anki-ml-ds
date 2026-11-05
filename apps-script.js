// Google Apps Script backend for the flashcards: Google sign-in, user preferences and synced progress.
// Setup steps are in SETUP-SIGNIN.md. After changing this file, paste it into the Apps Script editor and
// use Deploy > Manage deployments > Edit > New version, so the /exec URL stays the same.
//
// Script properties:
//   GOOGLE_CLIENT_ID  required: the OAuth client ID that the page signs in with
//   SESSION_SECRET    created by setup(): signs session tokens. Change it to sign everyone out.
//   ALLOWED_EMAILS    optional: comma-separated list of who may sign in. Empty means any Google account.

const USERS_SHEET = 'Users';
const PREFS_SHEET = 'Preferences';
const PROGRESS_SHEET = 'Progress';
const USERS_HEADERS = ['Google ID', 'Email', 'Name', 'First Sign-in', 'Last Sign-in', 'Sign-ins', 'Last Seen'];
const PREFS_HEADERS = ['Google ID', 'Text Size', 'Last Deck', 'Updated (epoch s)'];
const PROGRESS_HEADERS = ['Google ID', 'Known Cards', 'Card Data', 'Updated'];

const SESSION_DAYS = 30;
const RENEW_DAYS = 15;           // a session with less than this left is replaced on the next call
const MAX_CHANGES = 5000;        // cards accepted in one request
const MAX_CELL_CHARS = 49000;    // a Sheets cell holds at most 50,000 characters

// Run once from the Apps Script editor: creates the tabs and the session secret.
function setup() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  [[USERS_SHEET, USERS_HEADERS], [PREFS_SHEET, PREFS_HEADERS], [PROGRESS_SHEET, PROGRESS_HEADERS]].forEach(([name, headers]) => {
    const sheet = ss.getSheetByName(name) || ss.insertSheet(name);
    if (sheet.getLastRow() === 0) sheet.appendRow(headers);
    sheet.setFrozenRows(1);
  });
  // Keep card data as plain text so Sheets never tries to interpret it.
  ss.getSheetByName(PROGRESS_SHEET).getRange('C:C').setNumberFormat('@');
  const props = PropertiesService.getScriptProperties();
  if (!props.getProperty('SESSION_SECRET')) {
    props.setProperty('SESSION_SECRET', Utilities.getUuid() + Utilities.getUuid());
  }
  if (!props.getProperty('GOOGLE_CLIENT_ID')) {
    Logger.log('Now add GOOGLE_CLIENT_ID in Project Settings > Script properties.');
  }
}

function doGet() {
  return json({ success: true, service: 'flashcards-sync' });
}

// The page posts JSON as text/plain: that needs no CORS preflight, which Apps Script cannot answer.
// POST also keeps tokens out of URLs, and so out of logs and browser history.
function doPost(e) {
  try {
    const body = JSON.parse((e.postData && e.postData.contents) || '{}');
    switch (body.action) {
      case 'signIn': return json(signIn(body));
      case 'sync': return json(sync(body));
      default: return json({ success: false, error: 'Unknown action' });
    }
  } catch (err) {
    return json({ success: false, error: err.message || String(err), code: err.code || 'error' });
  }
}

function json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function fail(message, code) {
  const err = new Error(message);
  err.code = code;
  throw err;
}

function withLock(fn) {
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const result = fn();
    SpreadsheetApp.flush();
    return result;
  } finally {
    lock.releaseLock();
  }
}

function nowSeconds() {
  return Math.floor(Date.now() / 1000);
}

// ---- Actions ----

function signIn(body) {
  const google = verifyGoogleToken(body.idToken);
  const email = String(google.email).toLowerCase();
  const allowed = allowedEmails();
  if (allowed.length && allowed.indexOf(email) === -1) {
    fail('This Google account is not allowed to sign in.', 'forbidden');
  }
  const key = userKey(google.sub);
  const data = withLock(() => {
    recordSignIn(key, email, google.name || '');
    return applySync(key, body, true);
  });
  return Object.assign({ success: true, session: createSession(google.sub), user: { sub: google.sub, email: email, name: google.name || '' } }, data);
}

function sync(body) {
  const session = verifySession(body.session);
  const key = userKey(session.sub);
  const data = withLock(() => {
    if (body.pull) recordSeen(key);
    return applySync(key, body, !!body.pull);
  });
  const result = Object.assign({ success: true }, data);
  if (session.exp - nowSeconds() < RENEW_DAYS * 86400) result.session = createSession(session.sub);
  return result;
}

// Saves the request's changes; returns the user's full data when asked to.
function applySync(key, body, includeData) {
  const progress = saveProgress(key, body.changes);
  const prefs = savePrefs(key, body.prefs);
  return includeData ? { progress: progress, prefs: prefs } : {};
}

// ---- Authentication ----

// Google signs the ID token; only its answer is trusted, never an email sent by the page.
function verifyGoogleToken(idToken) {
  const clientId = PropertiesService.getScriptProperties().getProperty('GOOGLE_CLIENT_ID');
  if (!clientId) fail('GOOGLE_CLIENT_ID is not set in Script properties', 'config');
  if (!idToken) fail('Missing Google token', 'auth');
  const res = UrlFetchApp.fetch('https://oauth2.googleapis.com/tokeninfo?id_token=' + encodeURIComponent(idToken),
    { muteHttpExceptions: true });
  if (res.getResponseCode() !== 200) fail('Google did not accept this sign-in', 'auth');
  const t = JSON.parse(res.getContentText());
  const issuerOk = t.iss === 'accounts.google.com' || t.iss === 'https://accounts.google.com';
  if (t.aud !== clientId || !issuerOk || !t.sub || !t.email) fail('Sign-in token is not for this app', 'auth');
  if (String(t.email_verified) !== 'true') fail('This Google account has no verified email', 'auth');
  if (Number(t.exp) <= nowSeconds()) fail('Sign-in token has expired', 'auth');
  return t;
}

function allowedEmails() {
  return String(PropertiesService.getScriptProperties().getProperty('ALLOWED_EMAILS') || '')
    .split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
}

function sessionSecret() {
  const secret = PropertiesService.getScriptProperties().getProperty('SESSION_SECRET');
  if (!secret) fail('SESSION_SECRET is not set (run setup() once)', 'config');
  return secret;
}

function signSession(payload) {
  return Utilities.base64EncodeWebSafe(Utilities.computeHmacSha256Signature(payload, sessionSecret()));
}

function createSession(sub) {
  const payload = sub + '.' + (nowSeconds() + SESSION_DAYS * 86400);
  return payload + '.' + signSession(payload);
}

function verifySession(token) {
  const parts = String(token || '').split('.');
  if (parts.length !== 3) fail('Please sign in again', 'auth');
  const payload = parts[0] + '.' + parts[1];
  if (signSession(payload) !== parts[2]) fail('Please sign in again', 'auth');
  const exp = Number(parts[1]);
  if (!(exp > nowSeconds())) fail('Please sign in again', 'auth');
  return { sub: parts[0], exp: exp };
}

// ---- Sheet helpers ----

function getSheet(name) {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(name);
  if (!sheet) fail(`Sheet tab '${name}' not found (run setup() once)`, 'config');
  return sheet;
}

// Google IDs are 21-digit numbers, which Sheets would round if stored as numbers; the prefix keeps them text.
function userKey(sub) {
  return 'g-' + sub;
}

// Returns the row number holding this user, or 0.
function findRow(sheet, key) {
  const last = sheet.getLastRow();
  if (last < 2) return 0;
  const ids = sheet.getRange(2, 1, last - 1, 1).getValues();
  for (let i = 0; i < ids.length; i++) {
    if (String(ids[i][0]) === key) return i + 2;
  }
  return 0;
}

// Names come from outside: without this, a value starting with = would run as a formula in the sheet.
function safeText(value, maxLength) {
  const s = String(value == null ? '' : value).slice(0, maxLength);
  return /^[=+\-@]/.test(s) ? "'" + s : s;
}

function recordSignIn(key, email, name) {
  const sheet = getSheet(USERS_SHEET);
  const now = new Date();
  const row = findRow(sheet, key);
  if (!row) {
    sheet.appendRow([key, safeText(email, 200), safeText(name, 200), now, now, 1, now]);
    return;
  }
  const count = Number(sheet.getRange(row, 6).getValue()) || 0;
  sheet.getRange(row, 2, 1, 6).setValues([[safeText(email, 200), safeText(name, 200), sheet.getRange(row, 4).getValue(), now, count + 1, now]]);
}

function recordSeen(key) {
  const sheet = getSheet(USERS_SHEET);
  const row = findRow(sheet, key);
  if (row) sheet.getRange(row, 7).setValue(new Date());
}

// ---- Progress ----
// Card Data is JSON: { cardId: seconds } with a positive time for "known" and a negative time for
// "not known". The most recent change to each card wins, so two devices can't undo each other's work.

function cleanChanges(changes) {
  const clean = {};
  if (!changes || typeof changes !== 'object') return clean;
  const ids = Object.keys(changes);
  if (ids.length > MAX_CHANGES) fail('Too many changes in one request', 'invalid');
  const now = nowSeconds();
  ids.forEach(id => {
    const t = Number(changes[id]);
    if (id.length > 64 || !Number.isFinite(t) || t === 0) return;
    // A device with a fast clock must not be able to beat every later change.
    const seconds = Math.min(Math.floor(Math.abs(t)), now);
    clean[id] = t > 0 ? seconds : -seconds;
  });
  return clean;
}

function saveProgress(key, changes) {
  const clean = cleanChanges(changes);
  const sheet = getSheet(PROGRESS_SHEET);
  const row = findRow(sheet, key);
  // A cell that can't be parsed throws here, so unreadable data is never overwritten.
  const stored = row ? JSON.parse(String(sheet.getRange(row, 3).getValue() || '{}')) : {};
  let changed = false;
  Object.keys(clean).forEach(id => {
    if (!stored[id] || Math.abs(clean[id]) > Math.abs(stored[id])) {
      stored[id] = clean[id];
      changed = true;
    }
  });
  if (!changed) return stored;
  const text = JSON.stringify(stored);
  if (text.length > MAX_CELL_CHARS) fail('Progress is too large for one sheet cell', 'tooLarge');
  const knownCount = Object.keys(stored).filter(id => stored[id] > 0).length;
  const values = [knownCount, text, new Date()];
  if (row) sheet.getRange(row, 2, 1, 3).setValues([values]);
  else sheet.appendRow([key].concat(values));
  return stored;
}

// ---- Preferences ----

function readPrefs(sheet, row) {
  if (!row) return null;
  const r = sheet.getRange(row, 2, 1, 3).getValues()[0];
  return { font: Number(r[0]) || 100, deck: String(r[1] || ''), at: Number(r[2]) || 0 };
}

function savePrefs(key, prefs) {
  const sheet = getSheet(PREFS_SHEET);
  const row = findRow(sheet, key);
  const current = readPrefs(sheet, row);
  if (!prefs || typeof prefs !== 'object') return current;
  const at = Math.min(Math.floor(Number(prefs.at)) || 0, nowSeconds());
  if (at <= 0 || (current && at <= current.at)) return current;
  const font = Math.round(Number(prefs.font));
  if (!(font >= 80 && font <= 200)) fail('Text size is out of range', 'invalid');
  const next = { font: font, deck: String(prefs.deck || '').slice(0, 100), at: at };
  const values = [next.font, safeText(next.deck, 100), next.at];
  if (row) sheet.getRange(row, 2, 1, 3).setValues([values]);
  else sheet.appendRow([key].concat(values));
  return next;
}
