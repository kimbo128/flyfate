"""Accounts without passwords. Saving an answer to the public archive needs a confirmed email address: we send
a link, a click confirms. The same link logs the person in, and their saved answers become their collection.

Tokens and session ids are random and only stored hashed. One click on the link saves and logs in, no extra
button. So links work as often as needed for a day: mail scanners that open every link (Outlook Safe Links and
the like) can't use one up before the person gets to click. A scanner at worst saves what the person asked to save.
"""
import hashlib
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque

LINK_SECONDS = 24 * 3600
SESSION_SECONDS = 365 * 24 * 3600
COOKIE = 'ff_session'
EMAIL = re.compile(r'^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$')
# Links per address and per IP: enough for real use, too few to turn us into a spam cannon.
PER_EMAIL = (3, 600)
PER_IP = (10, 3600)


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Accounts:
    def __init__(self, store):
        self.db, self.lock = store.db, store.lock
        self.sent = defaultdict(deque)
        with self.lock:
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT UNIQUE, created REAL);
                CREATE TABLE IF NOT EXISTS links (token TEXT PRIMARY KEY, email TEXT, oracle TEXT, expires REAL);
                CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user INTEGER, expires REAL);
                CREATE TABLE IF NOT EXISTS saves (user INTEGER, oracle TEXT, created REAL, PRIMARY KEY (user, oracle));
            ''')
            self.db.commit()

    def allow(self, email, ip):
        """Rate limit for sending links, per address and per IP (in memory, like guard.py)."""
        now = time.time()
        for key, (count, window) in ((f'e:{email}', PER_EMAIL), (f'i:{ip}', PER_IP)):
            times = self.sent[key]
            while times and times[0] < now - window:
                times.popleft()
            if len(times) >= count:
                return False
        self.sent[f'e:{email}'].append(now)
        self.sent[f'i:{ip}'].append(now)
        return True

    def link(self, email, oracle=None):
        """A new token for this address, valid for a day, optionally saving an answer when redeemed."""
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.db.execute('DELETE FROM links WHERE expires < ?', (time.time(),))
            self.db.execute('INSERT INTO links VALUES (?, ?, ?, ?)',
                            (digest(token), email, oracle, time.time() + LINK_SECONDS))
            self.db.commit()
        return token

    def redeem(self, token):
        """Use a link: creates the account on first use and saves the answer. Returns (session, user, oracle).
        The link stays valid until it expires (see the module note on mail scanners)."""
        with self.lock:
            row = self.db.execute('SELECT email, oracle FROM links WHERE token = ? AND expires > ?',
                                  (digest(token), time.time())).fetchone()
            if not row:
                return None
            email, oracle = row
            self.db.execute('INSERT OR IGNORE INTO users (email, created) VALUES (?, ?)', (email, time.time()))
            user = self.db.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()[0]
            session = secrets.token_urlsafe(32)
            self.db.execute('INSERT INTO sessions VALUES (?, ?, ?)',
                            (digest(session), user, time.time() + SESSION_SECONDS))
            self.db.commit()
        if oracle:
            self.save(user, oracle)
        return session, user, oracle

    def user(self, session):
        """{'id', 'email'} for a valid session cookie, else None."""
        if not session:
            return None
        with self.lock:
            row = self.db.execute('SELECT users.id, users.email FROM sessions JOIN users ON users.id = sessions.user '
                                  'WHERE sessions.token = ? AND sessions.expires > ?',
                                  (digest(session), time.time())).fetchone()
        return {'id': row[0], 'email': row[1]} if row else None

    def logout(self, session):
        with self.lock:
            self.db.execute('DELETE FROM sessions WHERE token = ?', (digest(session or ''),))
            self.db.commit()

    def save(self, user, oracle):
        """Into the person's collection and the public archive (the archive still skips unclean answers)."""
        with self.lock:
            if not self.db.execute('SELECT 1 FROM oracles WHERE id = ?', (oracle,)).fetchone():
                return False
            self.db.execute('INSERT OR IGNORE INTO saves VALUES (?, ?, ?)', (user, oracle, time.time()))
            self.db.execute('UPDATE oracles SET saved = 1 WHERE id = ?', (oracle,))
            self.db.commit()
        return True

    def saved(self, user, oracle):
        with self.lock:
            return bool(self.db.execute('SELECT 1 FROM saves WHERE user = ? AND oracle = ?', (user, oracle)).fetchone())

    def collection(self, user):
        with self.lock:
            rows = self.db.execute('SELECT oracles.id, question, answer, kind, saves.created FROM saves '
                                   'JOIN oracles ON oracles.id = saves.oracle WHERE saves.user = ? '
                                   'ORDER BY saves.created DESC', (user,)).fetchall()
        return [dict(zip(('id', 'question', 'answer', 'kind', 'created'), r)) for r in rows]


# --- Mail (Resend) ------------------------------------------------------------------------------------------

MAIL_FROM = os.environ.get('MAIL_FROM', 'Melanie from FlyFate <melanie@flyfate.com>')


def mail_ready():
    """Can we send links? With a Resend key, or in development (links go to the log). On Railway without a key
    the save-by-email flow stays hidden instead of failing."""
    return bool(os.environ.get('RESEND_API_KEY')) or 'RAILWAY_ENVIRONMENT' not in os.environ


def send(to, subject, html, text):
    """Send through Resend. Without RESEND_API_KEY (development) the mail goes to the log instead."""
    key = os.environ.get('RESEND_API_KEY')
    if not key:
        print(f'[mail] {subject}\n{text}', flush=True)
        return True
    body = json.dumps({'from': MAIL_FROM, 'to': [to], 'subject': subject, 'html': html, 'text': text}).encode()
    request = urllib.request.Request('https://api.resend.com/emails', data=body, method='POST', headers={
        'Authorization': f'Bearer {key}', 'Content-Type': 'application/json', 'User-Agent': 'flyfate/1.0'})
    try:
        urllib.request.urlopen(request, timeout=15).read()
        return True
    except (urllib.error.URLError, TimeoutError) as error:
        detail = error.read().decode() if isinstance(error, urllib.error.HTTPError) else str(error)
        print(f'[mail] failed: {detail}', flush=True)  # never the address: no visitor data in the logs
        return False


def link_mail(url, oracle=None):
    """(subject, html, text) for a confirmation link, in Melanie's voice and the site's colours."""
    from html import escape as e
    if oracle:
        subject = 'Save your answer from Melanie'
        intro = 'Tap the button to put this answer in the FlyFate archive. It also opens your collection.'
        quote = (f'<p style="margin:0 0 6px;color:#5a4f8a">“{e(oracle["question"])}”</p>'
                 f'<p style="margin:0 0 22px;font-size:20px;font-weight:800">{e(oracle["answer"])}</p>')
        text_quote = f'"{oracle["question"]}"\n{oracle["answer"]}\n\n'
        action = 'Save it to the archive'
    else:
        subject = 'Your FlyFate login link'
        intro = 'Tap the button to log in and see your collection.'
        quote, text_quote, action = '', '', 'Log in'
    html = f'''<div style="background:#a8dbff;padding:28px 12px;font-family:Arial,Helvetica,sans-serif;color:#2e2457">
<div style="max-width:480px;margin:0 auto;background:#fff;border:3px solid #2e2457;border-radius:24px;padding:26px">
<p style="margin:0 0 16px;font-size:26px;font-weight:900">FlyFate</p>
<p style="margin:0 0 18px">Hi, Melanie here! {intro}</p>{quote}
<a href="{e(url)}" style="display:inline-block;background:#ef4537;color:#fff;text-decoration:none;font-weight:800;
padding:14px 22px;border:3px solid #2e2457;border-radius:16px">{action}</a>
<p style="margin:22px 0 0;font-size:13px;color:#5a4f8a">The link works for a day. Didn't ask for this?
Just ignore it, nothing happens.</p></div></div>'''
    text = (f'Hi, Melanie here! {intro}\n\n{text_quote}{action}: {url}\n\n'
            "The link works for a day. Didn't ask for this? Just ignore it, nothing happens.")
    return subject, html, text
