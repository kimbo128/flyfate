"""The public archive: every shared, clean answer, searchable and grouped by decision type.

Plain server-rendered HTML (no 3D, no JavaScript): fast, and every answer is a real link for crawlers.
  /answers               newest first, paginated (?page=2)
  /answers/{kind}        one decision type, e.g. /answers/memory-call, with what that brain system does
  /answers?q=pizza       search; results are noindex (thin, endless variants), the pages they link to are not
"""
import html
import math
import time
from urllib.parse import urlencode

from . import share

PER_PAGE = 30
# The maker's credit in every footer, tagged so the blog's analytics see where visitors came from (as in App.tsx).
AUTHOR_URL = 'https://arturmarkus.com/?utm_source=flyfate&amp;utm_medium=referral&amp;utm_campaign=credit'
REPO_URL = 'https://github.com/kimbo128/flyfate'

CSS = """
:root{--grape:#2e2457;--grape-soft:#5a4f8a;--fly-red:#ef4537;--cloud:#fff;--lavender:#f3efff;--edge:3px solid var(--grape);
--display:'Bagel Fat One','Arial Rounded MT Bold','Trebuchet MS',sans-serif;
--ui:'M PLUS Rounded 1c','Arial Rounded MT Bold','Segoe UI',system-ui,sans-serif;color-scheme:light;color:var(--grape);
font:700 1rem/1.45 var(--ui);-webkit-font-smoothing:antialiased}
*{box-sizing:border-box}
html{min-height:100%;background:radial-gradient(circle at 1px 1px,rgb(255 255 255/.45) 1.5px,transparent 0) 0 0/26px 26px,
linear-gradient(#a8dbff,#ffe3c7)}
body{margin:0;padding:calc(env(safe-area-inset-top,0px) + 1rem) clamp(1rem,4vw,2.5rem) 3rem}
a{color:inherit}
.bar{display:flex;justify-content:space-between;align-items:center;gap:1rem;max-width:72rem;margin:0 auto}
.links{display:flex;gap:.6rem}
form.out{display:block}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}
.note{font-weight:500;font-size:.875rem;color:var(--grape-soft);margin:.9rem 0 0}
.done{font-weight:800;font-size:1.15rem}
blockquote{margin:0 0 1rem;padding:.9rem 1.1rem;background:var(--lavender);border:2.5px solid var(--grape);border-radius:18px}
blockquote q{display:block;color:var(--grape-soft);font-weight:500;margin-bottom:.3rem}blockquote p{margin:0;font-weight:800}
.mark{font:2rem/1 var(--display);color:var(--cloud);-webkit-text-stroke:6px var(--grape);paint-order:stroke fill;
text-shadow:0 4px 0 var(--grape);text-decoration:none}
.button{display:inline-block;font:800 1rem/1 var(--ui);color:var(--cloud);background:var(--fly-red);border:var(--edge);
border-radius:16px;padding:.8em 1.3em;box-shadow:0 5px 0 var(--grape);text-decoration:none;cursor:pointer;white-space:nowrap}
.button:hover{background:#ff5a4c}.button:active{transform:translateY(4px);box-shadow:0 1px 0 var(--grape)}
.button.soft{background:var(--cloud);color:var(--grape)}.button.soft:hover{background:var(--lavender)}
a:focus-visible,button:focus-visible,input:focus-visible{outline:3px solid var(--fly-red);outline-offset:3px}
main{max-width:72rem;margin:2rem auto 0}
.intro{background:var(--cloud);border:var(--edge);border-radius:28px;box-shadow:0 6px 0 var(--grape);
padding:1.75rem 1.6rem 1.5rem;max-width:44rem;position:relative}
.intro .tag{position:absolute;top:-1.05rem;left:1.4rem;font:1.15rem/1 var(--display);color:var(--cloud);border:var(--edge);
border-radius:999px;padding:.35rem .9rem .4rem;transform:rotate(-3deg);background:var(--tint,var(--fly-red))}
h1{font:clamp(1.9rem,1.4rem + 2vw,2.8rem)/1.05 var(--display);margin:.2rem 0 .6rem;letter-spacing:.01em}
h1.stamp{color:var(--tint);-webkit-text-stroke:7px var(--grape);paint-order:stroke fill;text-shadow:0 4px 0 var(--grape);
transform:rotate(-2deg);transform-origin:left center;margin:.5rem 0 .8rem}
.intro p{margin:0 0 1rem;font-weight:500;max-width:38rem}
.intro .line{font-weight:800;font-size:1.15rem}
form{display:flex;gap:.6rem;margin-top:.25rem}
input{flex:1;min-width:0;font:700 1rem/1 var(--ui);color:var(--grape);background:var(--lavender);border:var(--edge);
border-radius:16px;padding:.85rem 1rem}
input::placeholder{color:var(--grape-soft);opacity:.7}
.kinds{list-style:none;display:flex;flex-wrap:wrap;gap:.55rem;margin:1.6rem 0 0;padding:0}
.kinds a{display:inline-flex;gap:.4rem;align-items:baseline;text-decoration:none;font-weight:800;font-size:.9375rem;
background:color-mix(in srgb,var(--tint) 30%,white);border:2.5px solid var(--grape);border-radius:999px;padding:.35rem .8rem;
box-shadow:0 3px 0 var(--grape)}
.kinds a:hover{background:color-mix(in srgb,var(--tint) 50%,white)}
.kinds a[aria-current]{background:var(--tint);color:var(--cloud);-webkit-text-stroke:3px var(--grape);paint-order:stroke fill}
.kinds small{font-weight:500;font-size:.8125rem;-webkit-text-stroke:0}
.status{margin:1.6rem 0 .8rem;font-weight:500;color:var(--grape-soft)}
.status strong{color:var(--grape)}
.answers{list-style:none;margin:0;padding:0;display:grid;gap:1.1rem;grid-template-columns:repeat(auto-fill,minmax(min(19rem,100%),1fr))}
.answers li{display:flex;padding-top:.9rem}
.answers a{display:block;position:relative;text-decoration:none;background:var(--cloud);border:var(--edge);border-radius:22px;
box-shadow:0 5px 0 var(--grape);padding:1.55rem 1.2rem 1.1rem;flex:1;transition:transform .12s}
.answers a:hover{transform:translateY(-3px) rotate(-.4deg)}
.answers .kind{position:absolute;top:-.9rem;left:1rem;font:1rem/1 var(--display);color:var(--cloud);background:var(--tint);
-webkit-text-stroke:3px var(--grape);paint-order:stroke fill;border:2.5px solid var(--grape);border-radius:999px;
padding:.3rem .75rem .35rem;transform:rotate(-2.5deg)}
.answers q{display:block;color:var(--grape-soft);font-weight:500;margin-bottom:.35rem}
.answers p{margin:0;font-weight:800;font-size:1.15rem;line-height:1.3;text-wrap:pretty}
.empty{background:var(--cloud);border:var(--edge);border-radius:22px;padding:1.4rem;max-width:36rem;font-weight:500}
.empty p{margin:0 0 1rem}
nav.pages{display:flex;gap:.75rem;justify-content:center;margin-top:1.5rem}
footer{max-width:72rem;margin:2.5rem auto 0;font-weight:500;font-size:.8125rem;color:var(--grape-soft)}
.faq{display:grid;gap:1.1rem;margin-top:1.8rem;max-width:44rem}
.qa{background:var(--cloud);border:var(--edge);border-radius:22px;box-shadow:0 5px 0 var(--grape);padding:1.2rem 1.3rem}
.qa h2{font:1.3rem/1.15 var(--display);margin:0 0 .5rem;letter-spacing:.01em}
.qa p{margin:0;font-weight:500}.qa ul{margin:0;padding-left:1.1rem;font-weight:500}.qa li{margin:.2rem 0}
.panels{display:grid;gap:1.1rem;margin-top:1.4rem;grid-template-columns:repeat(auto-fill,minmax(min(19rem,100%),1fr))}
.panel{background:var(--cloud);border:var(--edge);border-radius:22px;box-shadow:0 5px 0 var(--grape);padding:1.1rem 1.2rem;
overflow-x:auto}
.panel h2{font:1.2rem/1.1 var(--display);margin:0 0 .6rem}
.panel.wide{grid-column:1/-1}
table{border-collapse:collapse;width:100%;font-size:.9375rem}
th,td{text-align:right;padding:.3rem .5rem;border-bottom:2px solid var(--lavender);white-space:nowrap}
th:first-child,td:first-child{text-align:left;white-space:normal;overflow-wrap:anywhere}
th{color:var(--grape-soft);font-weight:800;font-size:.8125rem}
.tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:.6rem;margin-top:1rem}
.tile{background:var(--lavender);border:2.5px solid var(--grape);border-radius:18px;padding:.6rem .9rem;min-width:0}
.tile b{display:block;font:1.6rem/1.1 var(--display)}.tile span{font-weight:500;font-size:.8125rem}
@media (max-width:30rem){.mark{font-size:1.45rem;-webkit-text-stroke-width:5px}.bar .button{padding:.6em .8em;font-size:.85rem}
.links{gap:.4rem}
form{flex-direction:column}.intro{padding:1.6rem 1.2rem 1.2rem}}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
"""


def href(path, **params):
    params = {k: v for k, v in params.items() if v not in (None, '', 1)}
    return path + ('?' + urlencode(params) if params else '')


def layout(head, main):
    """A full page in the site's look: the archive, the collection, login and confirmation pages."""
    return f'''<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
    <meta name="theme-color" content="#a8dbff" />
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <link rel="apple-touch-icon" href="/icon-180.png" />
    {head}
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=Bagel+Fat+One&family=M+PLUS+Rounded+1c:wght@500;700;800&display=swap" rel="stylesheet" />
    <style>{CSS}</style>
  </head>
  <body>
    <header class="bar">
      <a class="mark" href="/">FlyFate</a>
      <nav class="links"><a class="button soft" href="/me">My collection</a><a class="button" href="/">Ask Melanie</a></nav>
    </header>
    <main>{main}
    </main>
    <footer>Brain data: MaleCNS v1.0, FlyEM / HHMI Janelia and partners, CC BY 4.0. Answers by LFM2.5 with a fly-brain adapter. Just for fun. <a href="/how-it-works">How it works</a><br />
    A project by <a href="{AUTHOR_URL}" target="_blank" rel="noopener">AI Unfiltered</a> · <a href="{REPO_URL}" target="_blank" rel="noopener">★ Star FlyFate on GitHub</a></footer>
  </body>
</html>
'''


def answer_items(rows):
    """Answer tiles linking to their pages, each with its decision-type badge."""
    e = html.escape
    items = []
    for r in rows:
        k = share.kind(r['kind'])
        badge = f'<span class="kind" style="--tint:{k["color"]}">{e(k["title"])}</span>' if k else ''
        items.append(f'<li><a href="/o/{r["id"]}">{badge}<q>{e(r["question"])}</q><p>{e(r["answer"])}</p></a></li>')
    return f'<ul class="answers">{"".join(items)}</ul>'


def render(base, store, query='', kind_id=None, page=1):
    """(html, status). Unknown decision types are 404s; pages past the end too."""
    e = html.escape
    query = ' '.join(query.split())[:80]
    found = share.kind(kind_id) if kind_id else None
    if kind_id and not found:
        return None, 404
    path = f'/answers/{kind_id}' if kind_id else '/answers'
    rows, total = store.archive(query, kind_id, (page - 1) * PER_PAGE, PER_PAGE)
    pages = max(1, math.ceil(total / PER_PAGE))
    if page > pages:
        return None, 404
    counts = store.kind_counts()

    if found:
        title = f'{found["title"]}: fruit fly answers from the {found["group"].lower()}'
        heading = found['title']
        description = (f'{found["line"]} Questions where Melanie\'s {found["group"].lower()} stood out. '
                       f'{found["about"]}')
    else:
        title = "Melanie's answers: questions asked to a real fruit fly brain"
        heading = "Melanie's answers"
        description = ('Questions people asked Melanie, the fruit fly with a real brain wiring diagram, and her '
                       'verdicts. Search them, or browse by how her brain decided.')
    if page > 1:
        title += f' (page {page})'
    url = base + href(path, page=page)
    # Search results are endless thin variants, and empty pages say nothing: keep them out of the index,
    # but let crawlers follow the links.
    robots = 'noindex,follow' if query or not total else 'index,follow'
    image = f'{base}/card.jpg?v={share.CARD_VERSION}'
    crumbs = [{'@type': 'ListItem', 'position': 1, 'name': 'FlyFate', 'item': f'{base}/'},
              {'@type': 'ListItem', 'position': 2, 'name': "Melanie's answers", 'item': f'{base}/answers'}]
    if found:
        crumbs.append({'@type': 'ListItem', 'position': 3, 'name': found['title'], 'item': f'{base}{path}'})
    ld = [
        {'@context': 'https://schema.org', '@type': 'CollectionPage', 'name': title, 'url': url,
         'description': description, 'isPartOf': {'@type': 'WebSite', 'name': share.SITE, 'url': f'{base}/'},
         'mainEntity': {'@type': 'ItemList', 'numberOfItems': len(rows), 'itemListElement': [
             {'@type': 'ListItem', 'position': i + 1, 'url': f'{base}/o/{r["id"]}', 'name': r['question']}
             for i, r in enumerate(rows)]}},
        {'@context': 'https://schema.org', '@type': 'BreadcrumbList', 'itemListElement': crumbs},
    ]
    head = share.head_tags(share.clip(title, 90), share.clip(description, 200), url, image, robots, ld=ld)
    links = []
    if page > 1:
        links.append(f'<link rel="prev" href="{e(base + href(path, q=query, page=page - 1))}" />')
    if page < pages:
        links.append(f'<link rel="next" href="{e(base + href(path, q=query, page=page + 1))}" />')

    chips = [f'<li><a href="/answers"{" aria-current=page" if not found else ""} style="--tint:#ef4537">'
             f'All <small>{sum(counts.values())}</small></a></li>']
    for k in share.kinds():
        if not counts.get(k['id']) and k['id'] != kind_id:
            continue
        current = ' aria-current="page"' if k['id'] == kind_id else ''
        chips.append(f'<li><a href="/answers/{k["id"]}"{current} style="--tint:{k["color"]}">{e(k["title"])} '
                     f'<small>{counts.get(k["id"], 0)}</small></a></li>')


    if query:
        status = (f'<strong>{total:,}</strong> {"answer" if total == 1 else "answers"} for '
                  f'<strong>“{e(query)}”</strong>. <a href="{e(path)}">Clear search</a>')
    else:
        status = f'<strong>{total:,}</strong> {"answer" if total == 1 else "answers"}, newest first.'

    if rows:
        listing = answer_items(rows)
    elif query:
        listing = ('<div class="empty"><p>Nothing in the archive about that yet. Ask Melanie yourself and '
                   'save her answer to be the first.</p><a class="button" href="/">Ask Melanie</a></div>')
    else:
        listing = ('<div class="empty"><p>Nothing here yet. Ask Melanie a question and save her verdict to the '
                   'archive.</p><a class="button" href="/">Ask Melanie</a></div>')

    nav = []
    if page > 1:
        nav.append(f'<a class="button soft" href="{e(href(path, q=query, page=page - 1))}">Newer answers</a>')
    if page < pages:
        nav.append(f'<a class="button soft" href="{e(href(path, q=query, page=page + 1))}">Older answers</a>')

    tag = (f'<span class="tag" style="--tint:{found["color"]}">{e(found["group"])}</span>' if found
           else '<span class="tag">Archive</span>')
    intro_text = (f'<p class="line">{e(found["line"])}</p><p>Answers where Melanie\'s {e(found["group"].lower())} '
                  f'stood out most. {e(found["about"])}</p>' if found else
                  '<p>Real questions, real verdicts. Each answer ran through the wiring diagram of a fruit fly '
                  'brain, 166,700 neurons, and the person who asked chose to share or save it.</p>')
    main = f'''
      <section class="intro">
        {tag}
        {f'<h1 class="stamp" style="--tint:{found["color"]}">' if found else '<h1>'}{e(heading)}</h1>
        {intro_text}
        <form action="{e(path)}" method="get" role="search">
          <label for="q" class="sr">Search answers</label>
          <input id="q" name="q" type="search" value="{e(query)}" placeholder="Search questions and answers" maxlength="80" />
          <button class="button" type="submit">Search</button>
        </form>
      </section>
      <ul class="kinds" aria-label="Decision types">{"".join(chips)}</ul>
      <p class="status">{status}</p>
      {listing}
      {f'<nav class="pages" aria-label="Pages">{"".join(nav)}</nav>' if nav else ''}'''
    page_html = layout(head + ''.join(links), main)
    return page_html, 200


def sitemap_urls(base, store):
    """The archive's own entries for the sitemap: the index and every decision type that has answers."""
    day = time.strftime('%Y-%m-%d')
    urls = [f'<url><loc>{base}/how-it-works</loc><changefreq>monthly</changefreq></url>',
            f'<url><loc>{base}/answers</loc><lastmod>{day}</lastmod><changefreq>daily</changefreq></url>']
    for kind_id, count in store.kind_counts().items():
        if kind_id and count:
            urls.append(f'<url><loc>{base}/answers/{kind_id}</loc><changefreq>daily</changefreq></url>')
    return urls



# --- Account pages: the person's collection, login, confirming a link -----------------------------------------

def private_head(title):
    e = html.escape
    return f'<title>{e(title)}</title><meta name="robots" content="noindex,nofollow" />'


def login_form(note=''):
    return ('<form action="/login" method="post"><label for="email" class="sr">Your email</label>'
            '<input id="email" name="email" type="email" required autocomplete="email" maxlength="200" '
            'placeholder="you@example.com" /><button class="button" type="submit">Send me a link</button></form>'
            f'<p class="note">{note or "No password. We email you a link, one tap and you are in."}</p>')


def collection_page(user, rows, saved=None):
    e = html.escape
    if saved:
        intro = ('<p class="done">Saved! Your answer is in the archive and in your collection.</p>'
                 f'<p>Logged in as {e(user["email"])}. Only the question and the answer go public, never your '
                 'email.</p>')
    else:
        intro = f'<p>Every answer you saved to the archive, newest first. Logged in as {e(user["email"])}.</p>'
    listing = answer_items(rows) if rows else (
        '<div class="empty"><p>Nothing saved yet. Ask Melanie something and tap Save to archive under her '
        'answer.</p><a class="button" href="/">Ask Melanie</a></div>')
    count = f'<strong>{len(rows)}</strong> {"answer" if len(rows) == 1 else "answers"} saved.'
    main = f'''
      <section class="intro">
        <span class="tag">Your account</span>
        <h1>My collection</h1>
        {intro}
        <form class="out" action="/logout" method="post"><button class="button soft" type="submit">Log out</button></form>
      </section>
      <p class="status">{count} <a href="/answers">See the whole archive</a></p>
      {listing}'''
    return layout(private_head('My collection: FlyFate'), main)


def login_page(sent=False, error=''):
    if sent:
        body = ('<p class="done">Check your inbox!</p><p>We sent you a link. Tap it to log in. It works for a '
                'day.</p>')
    else:
        body = ('<p>Log in to see the answers you saved. New here? Save an answer to the archive first, the '
                'link in that email makes your account.</p>' + login_form(error))
    main = f'''
      <section class="intro">
        <span class="tag">Your account</span>
        <h1>My collection</h1>
        {body}
      </section>'''
    return layout(private_head('Log in: FlyFate'), main)


def expired_page():
    main = '''
      <section class="intro">
        <span class="tag">Oops</span>
        <h1>That link has expired</h1>
        <p>Links work for a day. Ask for a new one:</p>''' + login_form() + '''
      </section>'''
    return layout(private_head('Link expired: FlyFate'), main)
