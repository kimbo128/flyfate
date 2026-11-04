"""Our own visitor counts: no cookies, no third party, no banner.

Only daily totals are stored (SQLite on the volume, next to the answers): page views, which platform visitors came
from (a fixed list), link previews per platform, crawler visits, and what people did (asked, shared, saved). Never
an IP address, never a question, never free text from a visitor. /stats shows it all publicly. Unique visitors are counted with a hash of IP + browser and a salt that changes every day and
only lives in memory, so yesterday's visitors can't be recognised, not even by us.

Counts are buffered in memory and written once a minute, so a page view costs no disk write.
"""
import hashlib
import html
import re
import secrets
import threading
import time
from collections import Counter
from urllib.parse import urlparse

FLUSH_SECONDS = 60
# Link previews: the platform fetched a card because someone pasted a link there.
PREVIEWS = re.compile(r'(facebookexternalhit|Facebot|Twitterbot|Slackbot|Discordbot|WhatsApp|TelegramBot|LinkedInBot|'
                      r'Pinterest|redditbot|Applebot|SkypeUriPreview|Iframely|Embedly|Mastodon|Bluesky|Signal)', re.I)
CRAWLERS = re.compile(r'(Googlebot|bingbot|DuckDuckBot|YandexBot|Baiduspider|Applebot|GPTBot|ClaudeBot|'
                      r'PerplexityBot|Amazonbot|AhrefsBot|SemrushBot)', re.I)
BOTS = re.compile(r'bot|crawl|spider|slurp|preview|fetch|headless|lighthouse|curl|wget|python|httpx|go-http|'
                  r'axios|node|java/|monitor|scan', re.I)
MOBILE = re.compile(r'Mobi|Android|iPhone|iPad', re.I)
# Where visitors came from, as a fixed list: /stats is public, and both ?ref= and the Referer header are free text
# anyone can set (referrer spam). Matched against ?ref= / ?utm_source= first, then the referring domain.
PLATFORMS = [
    ('Hacker News', ('hn', 'hackernews', 'news.ycombinator.com')),
    ('Reddit', ('reddit', 'reddit.com', 'old.reddit.com', 'out.reddit.com')),
    ('Product Hunt', ('ph', 'producthunt', 'producthunt.com')),
    ('Google', ('google',)),
    ('Bing', ('bing', 'bing.com')),
    ('DuckDuckGo', ('duckduckgo', 'duckduckgo.com')),
    ('X', ('x', 'twitter', 't.co', 'x.com', 'twitter.com')),
    ('Bluesky', ('bluesky', 'bsky', 'bsky.app')),
    ('Mastodon', ('mastodon',)),
    ('Facebook', ('facebook', 'fb', 'facebook.com', 'm.facebook.com', 'l.facebook.com', 'lm.facebook.com')),
    ('Instagram', ('instagram', 'ig', 'instagram.com', 'l.instagram.com')),
    ('TikTok', ('tiktok', 'tiktok.com')),
    ('YouTube', ('youtube', 'yt', 'youtube.com', 'm.youtube.com')),
    ('LinkedIn', ('linkedin', 'linkedin.com', 'lnkd.in')),
    ('Threads', ('threads', 'threads.net', 'threads.com')),
    ('Discord', ('discord', 'discord.com')),
    ('Newsletter', ('newsletter', 'email', 'mail')),
    ('Home screen app', ('app',)),
]
PLATFORM = {key: name for name, keys in PLATFORMS for key in keys}


def platform(source, referrer):
    """The platform a visit came from, or 'Other sites' / None (typed in, bookmark)."""
    if source and source.lower() in PLATFORM:
        return PLATFORM[source.lower()]
    if not referrer:
        return None
    if referrer in PLATFORM:
        return PLATFORM[referrer]
    if re.match(r'(.+\.)?google\.[a-z.]+$', referrer):  # google.ch, google.co.uk, news.google.com
        return 'Google'
    if referrer.endswith('.mastodon.social') or referrer == 'mastodon.social':
        return 'Mastodon'
    return 'Other sites'
# The /stats page shows these, in this order.
EVENTS = [('ask', 'Questions'), ('share', 'Shares'), ('save', 'Saves'), ('limited', 'Hit a limit'),
          ('serious', 'Serious topic')]


def section(path):
    """Page views grouped by kind of page: one row per answer page would drown the rest."""
    if path == '/':
        return 'Start page'
    if path.startswith('/o/'):
        return 'Answer pages'
    if path.startswith('/answers'):
        return 'Archive'
    return path


class Stats:
    def __init__(self, store, own_host=''):
        self.db, self.lock = store.db, store.lock
        self.own_host = own_host
        self.pending = Counter()
        self.pending_lock = threading.Lock()
        self.day, self.salt, self.seen = '', b'', set()
        with self.lock:
            self.db.execute('CREATE TABLE IF NOT EXISTS stats (day TEXT, kind TEXT, key TEXT, n INTEGER, '
                            'PRIMARY KEY (day, kind, key))')
            self.db.commit()
        threading.Thread(target=self.flush_forever, daemon=True).start()

    def add(self, kind, key='', n=1):
        with self.pending_lock:
            self.pending[(time.strftime('%Y-%m-%d', time.gmtime()), kind, key)] += n

    def event(self, name):
        self.add('event', name)

    def visitor(self, ip, agent):
        """Counts a visitor once per day."""
        today = time.strftime('%Y-%m-%d', time.gmtime())
        with self.pending_lock:
            if today != self.day:
                self.day, self.salt, self.seen = today, secrets.token_bytes(16), set()
            mark = hashlib.sha256(self.salt + f'{ip}|{agent}'.encode()).digest()[:12]
            new = mark not in self.seen
            self.seen.add(mark)
        if new:
            self.add('visitors')

    def request(self, path, query, headers, ip, html):
        """One request that went well. Only HTML pages and card images count; everything else is noise."""
        agent = headers.get('user-agent', '')
        card = path == '/card.jpg' or (path.startswith('/o/') and path.endswith('.jpg'))
        if card:
            preview = PREVIEWS.search(agent)
            self.add('preview', preview.group(1).lower() if preview else 'other')
            return
        if not html:
            return
        if BOTS.search(agent) or not agent:
            crawler = CRAWLERS.search(agent)
            self.add('crawler', crawler.group(1).lower() if crawler else 'other bots')
            return
        self.visitor(ip, agent)
        self.add('page', section(path))
        self.add('device', 'mobile' if MOBILE.search(agent) else 'desktop')
        if path.startswith('/o/'):
            self.add('answer', path[3:])
        referrer = urlparse(headers.get('referer', '')).netloc.lower().removeprefix('www.')
        own = self.own_host or headers.get('host', '').removeprefix('www.')
        if referrer == own or referrer.endswith('.railway.app'):
            referrer = ''
        came = platform(query.get('utm_source') or query.get('ref'), referrer)
        if came:
            self.add('from', came)

    def flush(self):
        with self.pending_lock:
            pending, self.pending = self.pending, Counter()
        if not pending:
            return
        with self.lock:
            self.db.executemany('INSERT INTO stats VALUES (?, ?, ?, ?) ON CONFLICT (day, kind, key) '
                                'DO UPDATE SET n = n + excluded.n', [(*k, n) for k, n in pending.items()])
            self.db.commit()

    def flush_forever(self):
        while True:
            time.sleep(FLUSH_SECONDS)
            try:
                self.flush()
            except Exception as error:  # a full disk must not stop the counting thread for good
                print(f'[stats] flush failed: {error}', flush=True)

    def daily(self, days):
        """{day: {(kind, key): n}} for the last `days` days, today included (pending counts too)."""
        self.flush()
        since = time.strftime('%Y-%m-%d', time.gmtime(time.time() - (days - 1) * 86400))
        with self.lock:
            rows = self.db.execute('SELECT day, kind, key, n FROM stats WHERE day >= ?', (since,)).fetchall()
        out = {}
        for day, kind, key, n in rows:
            out.setdefault(day, Counter())[(kind, key)] += n
        return out

    def top(self, kind, days, limit=12):
        self.flush()
        since = time.strftime('%Y-%m-%d', time.gmtime(time.time() - (days - 1) * 86400))
        with self.lock:
            return self.db.execute('SELECT key, SUM(n) AS total FROM stats WHERE kind = ? AND day >= ? '
                                   'GROUP BY key ORDER BY total DESC LIMIT ?', (kind, since, limit)).fetchall()


# --- /stats: the public overview --------------------------------------------------------------------------------

def render(stats, store, days=30):
    from . import archive
    e = html.escape
    daily = stats.daily(days)

    def total(kind, key='', within=days):
        since = time.strftime('%Y-%m-%d', time.gmtime(time.time() - (within - 1) * 86400))
        return sum(c[(kind, key)] for day, c in daily.items() if day >= since)

    def pages(c):
        return sum(n for (kind, _), n in c.items() if kind == 'page')

    tiles = []
    for within in (1, 7, days):
        label = 'today' if within == 1 else f'{within} days'
        views = sum(pages(c) for day, c in daily.items()
                    if day >= time.strftime('%Y-%m-%d', time.gmtime(time.time() - (within - 1) * 86400)))
        tiles.append(f'<div class="tile"><b>{total("visitors", within=within):,}</b><span>visitors {label}</span></div>'
                     f'<div class="tile"><b>{views:,}</b><span>page views {label}</span></div>'
                     f'<div class="tile"><b>{total("event", "ask", within):,}</b><span>questions {label}</span></div>')

    head_cells = ''.join(f'<th>{e(label)}</th>' for _, label in EVENTS)
    rows = []
    for back in range(days):
        day = time.strftime('%Y-%m-%d', time.gmtime(time.time() - back * 86400))
        c = daily.get(day, Counter())
        previews = sum(n for (kind, _), n in c.items() if kind == 'preview')
        rows.append(f'<tr><td>{day}</td><td>{c[("visitors", "")]:,}</td><td>{pages(c):,}</td>'
                    + ''.join(f'<td>{c[("event", name)]:,}</td>' for name, _ in EVENTS)
                    + f'<td>{previews:,}</td></tr>')
    table = (f'<table><thead><tr><th>Day</th><th>Visitors</th><th>Page views</th>{head_cells}<th>Link previews</th>'
             f'</tr></thead><tbody>{"".join(rows)}</tbody></table>')

    def panel(title, kind, note='', label=None, found=None):
        found = stats.top(kind, days) if found is None else found
        if not found:
            body = '<p class="note">Nothing yet.</p>'
        else:
            body = '<table>' + ''.join(f'<tr><td>{label(k) if label else e(k)}</td><td>{n:,}</td></tr>'
                                       for k, n in found) + '</table>'
        return f'<section class="panel"><h2>{e(title)}</h2>{body}{f"<p class=note>{e(note)}</p>" if note else ""}</section>'

    # Only answers that are public anyway (shared or saved, and clean): every answer has a link, most stay private.
    public = [(oid, n) for oid, n in stats.top('answer', days, limit=200) if (store.get(oid) or {}).get('indexable')]

    def answer_label(oid):
        return f'<a href="/o/{e(oid)}">{e(store.get(oid)["question"])}</a>'

    main = f'''
      <section class="intro">
        <span class="tag">Stats</span>
        <h1>Who comes by</h1>
        <p>FlyFate's numbers, open for everyone. Daily totals only: no cookies, no IP addresses, no questions.
        Visitors are counted once per day and browser. Bots and link previews are counted apart.</p>
        <div class="tiles">{"".join(tiles)}</div>
      </section>
      <div class="panels">
        {panel("Came from", "from", "The platform of the link they clicked. Typed in or bookmarked visits don't show.")}
        {panel("Link previews", "preview", "A platform drew a card because someone pasted a link there.")}
        {panel("Pages", "page")}
        {panel("Most viewed answers", "answer", "Only answers people shared or saved to the archive.",
               answer_label, public[:12])}
        {panel("Devices", "device")}
        {panel("Search engines and bots", "crawler")}
        <section class="panel wide"><h2>Last {days} days</h2>{table}</section>
      </div>'''
    head = '<title>Open stats: FlyFate</title><meta name="robots" content="noindex,follow" />'
    return archive.layout(head, main)
