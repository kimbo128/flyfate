"""Shared answers: a stable link per question, a crawlable page with full SEO/social tags, and a 1200x630 card.

The link id comes from the question (plus VERSION), and answers are deterministic per question, so the same
question always lands on the same page: no duplicate pages, and asking again reproduces what was shared.
Bump VERSION whenever the model, prompt or adapter change, so old links keep their old answers.
"""
import hashlib
import html
import io
import json
import re
import sqlite3
import threading
import time
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .paths import ASSETS, DATA, WEB_BRAIN, WEB_DIST

SITE = 'FlyFate'
VERSION = 'v1'
CARD_VERSION = '4'  # bump to make platforms refetch every card after a design change
BASE62 = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'

# Shareable, but kept out of search engines: we don't want these indexed under the site's name.
PROFANE = re.compile(
    r'\b(fuck\w*|shit\w*|cunts?|dicks?|cocks?|puss(y|ies)|porn\w*|sex\w*|nazis?|hitler|nigg\w*|fag\w*|'
    r'retard\w*|whores?|sluts?|bitch\w*|rap(e|ed|ist)|tits?|boobs?|nude\w*|naked)\b', re.I)

GRAPE, GRAPE_SOFT, FLY_RED, WHITE = (46, 36, 87), (90, 79, 138), (239, 69, 55), (255, 255, 255)
SKY_TOP, SKY_BOTTOM = (168, 219, 255), (255, 227, 199)
W, H = 1200, 630


def share_id(question):
    """Stable 9-character id; the same key the answer's sampling seed is derived from."""
    n = int.from_bytes(hashlib.sha256(f'{VERSION}:{question.lower().strip()}'.encode()).digest()[:8], 'big')
    out = ''
    for _ in range(9):
        n, r = divmod(n, 62)
        out += BASE62[r]
    return out


class Store:
    """SQLite on the volume. One small row per answer.

    Every answer has its link (the address bar shows it), but a page only goes into search engines, the
    sitemap and the public archive once someone actually shares it, and only if it's clean. Asking is
    private; sharing is public.
    """

    # Public = clean, and shared by someone or saved to the archive through a confirmed email (accounts.py).
    PUBLIC = 'indexable = 1 AND (shared = 1 OR saved = 1)'

    def __init__(self):
        DATA.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(DATA / 'oracles.db', check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.db.execute('CREATE TABLE IF NOT EXISTS oracles (id TEXT PRIMARY KEY, question TEXT, answer TEXT, '
                            'reading TEXT, created REAL, indexable INTEGER, shared INTEGER DEFAULT 0, kind TEXT)')
            columns = [row[1] for row in self.db.execute('PRAGMA table_info(oracles)')]
            if 'kind' not in columns:  # rows from before decision types
                self.db.execute('ALTER TABLE oracles ADD COLUMN kind TEXT')
            if 'saved' not in columns:  # rows from before accounts
                self.db.execute('ALTER TABLE oracles ADD COLUMN saved INTEGER DEFAULT 0')
            for oid, reading in self.db.execute('SELECT id, reading FROM oracles WHERE kind IS NULL').fetchall():
                found = decision(json.loads(reading))
                self.db.execute('UPDATE oracles SET kind = ? WHERE id = ?', (found and found['id'], oid))
            self.db.execute('CREATE INDEX IF NOT EXISTS public_by_date ON oracles (indexable, shared, created)')
            self.db.commit()

    def mark_shared(self, oid):
        with self.lock:
            changed = self.db.execute('UPDATE oracles SET shared = 1 WHERE id = ?', (oid,)).rowcount
            self.db.commit()
        return bool(changed)

    def save(self, question, answer, reading):
        oid = share_id(question)
        indexable = not (PROFANE.search(question) or PROFANE.search(answer))
        found = decision(reading)
        with self.lock:
            self.db.execute('INSERT OR IGNORE INTO oracles (id, question, answer, reading, created, indexable, shared, '
                            'kind) VALUES (?, ?, ?, ?, ?, ?, 0, ?)',
                            (oid, question, answer, json.dumps(reading), time.time(), int(indexable),
                             found and found['id']))
            self.db.commit()
        return oid

    def get(self, oid):
        with self.lock:
            row = self.db.execute(f'SELECT question, answer, reading, created, {self.PUBLIC} FROM oracles '
                                  'WHERE id = ?', (oid,)).fetchone()
        if not row:
            return None
        return {'id': oid, 'question': row[0], 'answer': row[1], 'reading': json.loads(row[2]),
                'created': row[3], 'indexable': bool(row[4])}

    def indexable(self, limit=5000):
        with self.lock:
            return self.db.execute(f'SELECT id, created FROM oracles WHERE {self.PUBLIC} '
                                   'ORDER BY created DESC LIMIT ?', (limit,)).fetchall()

    def archive(self, query='', kind=None, offset=0, limit=30):
        """Shared, clean answers, newest first, optionally searched and filtered by decision type.
        Returns (rows, total)."""
        where, args = [self.PUBLIC], []
        for word in query.split()[:8]:
            # Every word must appear in the question or the answer. LIKE is plenty at this size.
            pattern = '%' + re.sub(r'([\\%_])', r'\\\1', word) + '%'
            where.append("(question LIKE ? ESCAPE '\\' OR answer LIKE ? ESCAPE '\\')")
            args += [pattern, pattern]
        if kind:
            where.append('kind = ?')
            args.append(kind)
        sql = ' AND '.join(where)
        with self.lock:
            total = self.db.execute(f'SELECT COUNT(*) FROM oracles WHERE {sql}', args).fetchone()[0]
            rows = self.db.execute(f'SELECT id, question, answer, kind, created FROM oracles WHERE {sql} '
                                   'ORDER BY created DESC LIMIT ? OFFSET ?', args + [limit, offset]).fetchall()
        return [dict(zip(('id', 'question', 'answer', 'kind', 'created'), r)) for r in rows], total

    def kind_counts(self):
        with self.lock:
            return dict(self.db.execute(f'SELECT kind, COUNT(*) FROM oracles WHERE {self.PUBLIC} '
                                        'GROUP BY kind').fetchall())


# --- Brain legend (shared with the web app) -------------------------------------------------------------

def web_file(name):
    """A file from the web build (Docker) or, in development, from web/public."""
    built = WEB_DIST / 'brain' / name
    return built if built.exists() else WEB_BRAIN / name


@lru_cache
def legend():
    data = json.loads(web_file('legend.json').read_text(encoding='utf-8'))
    regions = [r['name'] for r in json.loads(web_file('regions.json').read_text())['regions']]
    return data, regions


def base_roi(roi):
    return re.sub(r'\((L|R)\)$', '', roi)


def group_of(roi):
    groups = legend()[0]['groups']
    return next((g for g in groups if base_roi(roi) in g['rois']), groups[-1])


def roi_label(roi):
    """'gL(R)' -> 'Mushroom body γ lobe, right'"""
    side = re.search(r'\((L|R)\)$', roi)
    name = legend()[0]['roi_names'].get(base_roi(roi), base_roi(roi))
    return f'{name}, {"left" if side.group(1) == "L" else "right"}' if side else name


def cell_family(cell_type):
    """'KCg-m' -> "Kenyon cells, the memory centre's short-term keepers"; None for families we don't explain."""
    for prefix, text in sorted(legend()[0]['cells'], key=lambda c: -len(c[0])):
        if cell_type.startswith(prefix):
            return text
    return None


def kinds():
    """Every decision type, in legend order, with its brain system's colour and explanation."""
    return [{**g['kind'], 'color': g['color'], 'group': g['name'], 'about': g['about']} for g in legend()[0]['groups']]


def kind(kind_id):
    return next((k for k in kinds() if k['id'] == kind_id), None)


def decision(reading):
    """The decision type, named after the brain system of the region that stood out most (as in the app)."""
    if not reading:
        return None
    return kind(group_of(legend()[1][reading[0]['region']])['kind']['id'])


def reading_lines(reading):
    """The brain reading in plain words, with the scientific names alongside, like the app's stickers."""
    data, regions = legend()
    out = []
    for r in reading:
        roi = regions[r['region']]
        info = data['rois'].get(base_roi(roi), {})
        percent = round((r['factor'] - 1) * 100)
        types = [name for name, _ in r['types']]
        out.append({
            'plain': info.get('plain', roi_label(roi)), 'label': roi_label(roi), 'color': group_of(roi)['color'],
            'about': info.get('about', group_of(roi)['about']), 'percent': percent,
            'buzz': f'+{percent}%' if percent > 0 else '±0%', 'types': types,
            'family': cell_family(types[0]) if types else None, 'active': r['active'], 'neurons': r['neurons'],
        })
    return out


# --- Card -------------------------------------------------------------------------------------------------

@lru_cache
def font(name, size):
    return ImageFont.truetype(str(ASSETS / 'fonts' / name), size)


def display(size):
    return font('BagelFatOne-Regular.ttf', size)


def heavy(size):
    return font('MPLUSRounded1c-ExtraBold.ttf', size)


def medium(size):
    return font('MPLUSRounded1c-Medium.ttf', size)


def hex_rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def wrap(draw, text, face, width, max_lines):
    """Greedy word wrap; the last line ends in an ellipsis if the text doesn't fit."""
    words, lines, line = text.split(), [], ''
    for word in words:
        trial = f'{line} {word}'.strip()
        if draw.textlength(trial, font=face) <= width:
            line = trial
            continue
        if line:
            lines.append(line)
        line = word
        if len(lines) == max_lines:
            break
    if line and len(lines) < max_lines:
        lines.append(line)
    if len(lines) == max_lines and ' '.join(lines) != ' '.join(words):
        last = lines[-1]
        while last and draw.textlength(last + '…', font=face) > width:
            last = last[:-1]
        lines[-1] = last.rstrip() + '…'
    return lines


def background():
    t = np.linspace(0, 1, H)[:, None, None]
    sky = (np.array(SKY_TOP) * (1 - t) + np.array(SKY_BOTTOM) * t).repeat(W, axis=1).astype(np.uint8)
    img = Image.fromarray(sky, 'RGB').convert('RGBA')
    dots = Image.new('RGBA', (W, H))
    d = ImageDraw.Draw(dots)
    for y in range(13, H, 26):
        for x in range(13, W, 26):
            d.ellipse((x - 1.6, y - 1.6, x + 1.6, y + 1.6), fill=(255, 255, 255, 115))
    return Image.alpha_composite(img, dots)


def pill(text, face, fill, ink, pad=(18, 8), border=5, angle=0.0, stroke=False):
    """A rounded sticker with text, optionally tilted; `stroke` outlines the letters like the app's logo."""
    probe = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
    width = 5 if stroke else 0
    l, t, r, b = probe.textbbox((0, 0), text, font=face, stroke_width=width)
    w, h = r - l + 2 * pad[0] + 2 * border, b - t + 2 * pad[1] + 2 * border
    img = Image.new('RGBA', (w, h + 5))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 5, w - 1, h + 4), radius=h // 2, fill=GRAPE)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 2, fill=fill, outline=GRAPE, width=border)
    d.text((border + pad[0] - l, border + pad[1] - t), text, font=face, fill=ink, stroke_width=width,
           stroke_fill=GRAPE)
    return img.rotate(angle, expand=True, resample=Image.BICUBIC) if angle else img


def render_card(oracle, host):
    """1200x630 JPEG. `oracle` None renders the site's default card."""
    img = background()
    d = ImageDraw.Draw(img)

    # Logo, outlined like in the app.
    d.text((50, 42), SITE, font=display(52), fill=GRAPE, stroke_width=7, stroke_fill=GRAPE)
    d.text((48, 36), SITE, font=display(52), fill=WHITE, stroke_width=7, stroke_fill=GRAPE)

    # Melanie and her brain, right.
    hero = Image.open(ASSETS / 'card-hero.png').convert('RGBA')
    scale = 590 / hero.width
    hero = hero.resize((590, round(hero.height * scale)), Image.LANCZOS)
    img.alpha_composite(hero, (W - hero.width - 14, 128))

    # The dialog card, left.
    box = (48, 150, 600, 548)
    d.rounded_rectangle((box[0], box[1] + 9, box[2], box[3] + 9), radius=34, fill=GRAPE)
    d.rounded_rectangle(box, radius=34, fill=WHITE, outline=GRAPE, width=5)
    tag = pill('Melanie', display(30), FLY_RED, WHITE, angle=3)
    img.alpha_composite(tag, (box[0] + 22, box[1] - 30))

    x, width, y = box[0] + 36, box[2] - box[0] - 72, box[1] + 50
    if oracle:
        q = wrap(d, f'“{oracle["question"]}”', medium(28), width, 2)
        for line in q:
            d.text((x, y), line, font=medium(28), fill=GRAPE_SOFT)
            y += 38
        y += 14
        answer = oracle['answer']
    else:
        answer = "Ask me anything. My real fruit fly brain decides!"
    room = box[3] - 30 - y
    for size in (56, 50, 46, 42, 38, 34, 30):
        lines = wrap(d, answer, heavy(size), width, 8)
        if len(lines) * size * 1.18 <= room and not lines[-1].endswith('…'):
            break
    lines = wrap(d, answer, heavy(size), width, max(1, int(room // (size * 1.18))))
    for line in lines:
        d.text((x, y), line, font=heavy(size), fill=GRAPE)
        y += size * 1.18

    # The decision type as a banner over the brain, the reading as stickers under it; the pitch on the default card.
    found = decision(oracle['reading']) if oracle else None
    if found:
        banner = pill(found['title'], display(46), hex_rgb(found['color']), WHITE, pad=(26, 10), border=5, angle=-3,
                      stroke=True)
        img.alpha_composite(banner, (W - 46 - banner.width, 30))
    if oracle and oracle['reading']:
        sy = 430
        for i, line in enumerate(reading_lines(oracle['reading'])[:3]):
            text = f'{line["plain"]}  {line["buzz"]}' if line['percent'] > 0 else line['plain']
            tint = tuple(round(c * 0.35 + 255 * 0.65) for c in hex_rgb(line['color']))
            chip = pill(text, heavy(22), tint, GRAPE, pad=(14, 6), border=3, angle=(i - 1) * 1.2)
            img.alpha_composite(chip, (W - 40 - chip.width, sy))
            sy += chip.height - 2
    else:
        line = '166,700 real neurons. 25.6 million connections.'
        d.text((W - 40 - d.textlength(line, font=heavy(24)), 460), line, font=heavy(24), fill=GRAPE)

    footer = f'Ask a real fruit fly brain at {host}'
    d.text((50, 572), footer, font=heavy(25), fill=GRAPE)

    out = io.BytesIO()
    img.convert('RGB').save(out, 'JPEG', quality=88, optimize=True, progressive=True)
    return out.getvalue()


def card(store_or_none, oid, host):
    """Cached on the volume: a card never changes for a given id, CARD_VERSION and the domain printed on it
    (a card drawn before the custom domain was set must not keep the old address)."""
    folder = DATA / 'cards'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'{oid or "home"}-{CARD_VERSION}-{re.sub(r"[^a-z0-9.-]", "_", host.lower())}.jpg'
    if path.exists():
        return path.read_bytes()
    oracle = store_or_none.get(oid) if oid else None
    if oid and not oracle:
        return None
    data = render_card(oracle, host)
    path.write_bytes(data)
    return data


# --- Pages ------------------------------------------------------------------------------------------------

HOME_TITLE = 'FlyFate: ask a real fruit fly brain'
HOME_DESCRIPTION = ('Ask Melanie anything. Every word runs through the real wiring diagram of a fruit fly, '
                    '166,700 neurons and 25.6 million connections, and she decides.')


def clip(text, limit):
    return text if len(text) <= limit else text[:limit - 1].rsplit(' ', 1)[0] + '…'


def head_tags(title, description, url, image, robots='index,follow', og_type='website', ld=None):
    e = html.escape
    tags = [
        f'<title>{e(title)}</title>',
        f'<meta name="description" content="{e(description)}" />',
        f'<meta name="robots" content="{robots}" />',
        f'<link rel="canonical" href="{e(url)}" />',
        f'<meta property="og:site_name" content="{SITE}" />',
        f'<meta property="og:type" content="{og_type}" />',
        f'<meta property="og:title" content="{e(title)}" />',
        f'<meta property="og:description" content="{e(description)}" />',
        f'<meta property="og:url" content="{e(url)}" />',
        f'<meta property="og:image" content="{e(image)}" />',
        '<meta property="og:image:type" content="image/jpeg" />',
        f'<meta property="og:image:width" content="{W}" />',
        f'<meta property="og:image:height" content="{H}" />',
        f'<meta property="og:image:alt" content="{e(description)}" />',
        '<meta name="twitter:card" content="summary_large_image" />',
        f'<meta name="twitter:title" content="{e(title)}" />',
        f'<meta name="twitter:description" content="{e(description)}" />',
        f'<meta name="twitter:image" content="{e(image)}" />',
    ]
    if ld:
        # JSON in a script tag: escape "</" so a question can't close the tag.
        tags.append('<script type="application/ld+json">' + json.dumps(ld).replace('</', '<\\/') + '</script>')
    return '\n    '.join(tags)


def render_page(template, base, oracle=None):
    """index.html with the page's head tags, and crawlable content inside #root (React replaces it)."""
    e = html.escape
    if oracle:
        url = f'{base}/o/{oracle["id"]}'
        title = clip(f'“{oracle["question"]}” Melanie the fruit fly says: {oracle["answer"]}', 90)
        found = decision(oracle['reading'])
        verdict = f'{found["title"]}: {found["line"][0].lower()}{found["line"][1:]} ' if found else ''
        description = clip(f'{oracle["answer"]} {verdict}Asked a real fruit fly brain: 166,700 neurons decided. '
                           f'Ask Melanie your own question.', 200)
        created = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(oracle['created']))
        ld = {'@context': 'https://schema.org', '@type': 'QAPage', 'mainEntity': {
            '@type': 'Question', 'name': oracle['question'], 'text': oracle['question'], 'answerCount': 1,
            'dateCreated': created,
            'acceptedAnswer': {'@type': 'Answer', 'text': oracle['answer'], 'dateCreated': created, 'url': url,
                               'author': {'@type': 'Organization', 'name': 'Melanie, the FlyFate fruit fly'}}}}
        tags = head_tags(title, description, url, f'{base}/o/{oracle["id"]}.jpg?v={CARD_VERSION}',
                         'index,follow' if oracle['indexable'] else 'noindex,follow', 'article', ld)
        items = ''.join(
            f'<li><strong>{e(r["plain"])}</strong> ({e(r["label"])}) {e(r["buzz"])}: {e(r["about"])}'
            f'{f" Led by {e(r["types"][0])} cells." if r["types"] else ""}</li>'
            for r in reading_lines(oracle['reading']))
        kind_html = (f'<h2><a href="/answers/{found["id"]}">{e(found["title"])}</a></h2><p>{e(found["line"])}</p>'
                     if found else '')
        body = (f'<main class="seo"><p>Someone asked Melanie, the fruit fly oracle:</p>'
                f'<h1>{e(oracle["question"])}</h1><p><strong>Melanie:</strong> {e(oracle["answer"])}</p>'
                f'{kind_html}{"<ul>" + items + "</ul>" if items else ""}'
                f'<p><a href="/">Ask Melanie your own question</a> or <a href="/answers">browse her answers</a></p>'
                '</main>')
    else:
        ld = {'@context': 'https://schema.org', '@type': 'WebApplication', 'name': SITE, 'url': f'{base}/',
              'applicationCategory': 'EntertainmentApplication', 'operatingSystem': 'Any',
              'description': HOME_DESCRIPTION, 'offers': {'@type': 'Offer', 'price': '0', 'priceCurrency': 'USD'}}
        tags = head_tags(HOME_TITLE, HOME_DESCRIPTION, f'{base}/', f'{base}/card.jpg?v={CARD_VERSION}', ld=ld)
        body = (f'<main class="seo"><h1>{HOME_TITLE}</h1><p>{HOME_DESCRIPTION}</p>'
                '<p>Melanie answers in a second or two, and you can share her verdict with a link.</p>'
                '<p><a href="/answers">Browse the answers people shared</a> or read '
                '<a href="/how-it-works">how a fruit fly connectome answers questions</a>.</p></main>')
    # A function, not a string, as replacement: the tags contain backslashes (JSON) that re would interpret.
    page = re.sub(r'<title>.*?</title>\s*<meta name="description"[^>]*/>', lambda _: tags, template, count=1,
                  flags=re.S)
    return page.replace('<div id="root"></div>', f'<div id="root">{body}</div>', 1)


def sitemap(base, store, extra=()):
    urls = [f'<url><loc>{base}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>', *extra]
    for oid, created in store.indexable():
        day = time.strftime('%Y-%m-%d', time.gmtime(created))
        urls.append(f'<url><loc>{base}/o/{oid}</loc><lastmod>{day}</lastmod></url>')
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + ''.join(urls) + '</urlset>\n')
