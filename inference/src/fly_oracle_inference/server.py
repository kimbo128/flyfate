"""HTTP API: one question in, a server-sent event stream of real graph frames out. Also serves the web build."""
import base64
import json
import os
import random
import threading
import time
import traceback
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, Query, Request
from fastapi.responses import (HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import about, accounts, archive, runtime, share, stats
from .guard import SERIOUS, SERIOUS_ANSWER, Limits, Queue
from .paths import WEB_DIST

PLAYBACK_SECONDS = 0.06  # per answer token, so the brain animation can follow
state = {'stage': 'starting'}
limits = Limits()
queue = Queue()
store = share.Store()
users = accounts.Accounts(store)
counter = stats.Stats(store, urlparse(os.environ.get('PUBLIC_URL', '')).netloc.removeprefix('www.'))


def warm_up():
    """Fetch data on first start (minutes, on a fresh volume), then load the graph. Runs beside the server."""
    try:
        state['stage'] = 'fetching'
        runtime.ensure()
        state['stage'] = 'loading'
        from .oracle import Oracle
        from .sim import Simulator
        sim = Simulator()
        newline = [i for i in range(sim.tokenizer.get_vocab_size()) if '\n' in sim.tokenizer.decode([i])]
        state['oracle'] = Oracle(sim.embeddings, sim.system_ids, set(newline))
        state['sim'] = sim
        state['stage'] = 'ready'
    except Exception:
        traceback.print_exc()
        state['stage'] = 'failed'


@asynccontextmanager
async def lifespan(_):
    threading.Thread(target=warm_up, daemon=True).start()
    yield
    counter.flush()  # don't lose the last minute's counts on a redeploy


app = FastAPI(lifespan=lifespan)


@app.middleware('http')
async def canonical_host(request: Request, call_next):
    """One address per page for search engines and shared links (301, query kept):
    www.flyfate.com and the Railway address -> PUBLIC_URL, /index.html -> /, a trailing slash -> without.
    /api/ is left alone: Railway's health check calls it on the internal address."""
    host = request.headers.get('host', '')
    path = request.url.path
    query = f'?{request.url.query}' if request.url.query else ''
    public = os.environ.get('PUBLIC_URL', '').rstrip('/')
    canonical = path[:-len('index.html')] if path.endswith('/index.html') else path
    if len(canonical) > 1 and canonical.endswith('/'):
        canonical = canonical.rstrip('/') or '/'
    if not path.startswith('/api/'):
        if public and host and host != urlparse(public).netloc:
            return RedirectResponse(f'{public}{canonical}{query}', status_code=301)
        if host.startswith('www.'):
            return RedirectResponse(f'https://{host[4:]}{canonical}{query}', status_code=301)
        if canonical != path:
            return RedirectResponse(f'{canonical}{query}', status_code=301)
    return await call_next(request)


@app.middleware('http')
async def count_visits(request: Request, call_next):
    """Daily visitor counts (stats.py): only successful GETs, decided by what was actually served."""
    response = await call_next(request)
    if request.method == 'GET' and response.status_code == 200 and request.url.path not in UNCOUNTED:
        html = response.headers.get('content-type', '').startswith('text/html')
        counter.request(request.url.path, request.query_params, request.headers, client_ip(request), html)
    return response


UNCOUNTED = {'/stats', '/me', '/auth'}  # our own and private pages


def event(name, data):
    return f'event: {name}\ndata: {json.dumps(data)}\n\n'


def frames(question, ip):
    refused = limits.allow(ip)
    if refused:
        message, wait = refused
        counter.event('limited')
        yield event('limit', {'message': message, 'retry_after': wait})
        return
    if SERIOUS.search(question):
        counter.event('serious')
        yield event('done', {'answer': SERIOUS_ANSWER, 'reading': [], 'serious': True})
        return
    ticket = queue.join()
    if ticket is None:
        counter.event('limited')
        yield event('limit', {'message': "So many questions at once! I'm a small fly.", 'retry_after': 60})
        return
    try:
        while not queue.wait_turn(ticket, timeout=1):
            yield event('queue', {'position': queue.position(ticket)})
        thought = yield from think(question, ticket)
    finally:
        queue.leave(ticket)
    # Played back outside the queue: the answer is computed, the next question can use the brain meanwhile.
    yield from speak(question, *thought)


def think(question, ticket):
    """Reading (streamed live) and generating the answer: the part that needs the brain, so it holds the queue."""
    sim, oracle = state['sim'], state['oracle']
    question_ids = sim.question_ids(question)
    # `words`: how many reading steps follow, so the page can show real progress.
    yield event('meta', {'neurons': sim.reservoir.n, 'edges': int(sim.graph.matrix.nnz), 'beads': len(sim.beads),
                         'words': len(question_ids)})
    counter.event('ask')
    total, steps = 0, 0  # summed state change per neuron, for the brain reading
    # Reading: the question's tokens pass through the graph, streamed live.
    started = time.perf_counter()
    last = None
    for last in sim.steps(question_ids):
        total, steps = total + last.change, steps + 1
        queue.touch(ticket)
        yield event('step', {'phase': 'reading', **encode(sim.frame(last.change)), 'ms': round(last.seconds * 1000, 1)})

    # Speaking: LFM2.5 + the fly adapter generate the answer, each token stepping this stream's own graph.
    # Generated in one go (llama.cpp has one context), then played back at reading pace.
    x = last.state

    def graph_step(token):
        nonlocal x
        step = sim.step(x, token)
        x = step.state
        return step.features, step.change

    reading_done = time.perf_counter()
    answer = oracle.answer(question_ids, last.features, graph_step, question)
    # Timing only, never the question text: no visitor content in the logs.
    print(f'[answer] reading {len(question_ids)} tok {reading_done - started:.2f}s, '
          f'answer {len(answer)} tok {time.perf_counter() - reading_done:.2f}s {oracle.last_timing}', flush=True)
    return answer, total, steps


def speak(question, answer, total, steps):
    """Plays the answer back at reading pace. Only reads the shared graph data, so it runs beside the queue."""
    sim = state['sim']
    tokens = [t for t, _ in answer]
    spoken = ''
    for k, (_, change) in enumerate(answer):
        raw = sim.tokenizer.decode(tokens[:k + 1])
        # An emoji spans several tokens: until it is complete, the decoded text ends in a replacement character.
        # Hold the piece back until then, and drop emoji altogether (share.printable).
        text = share.printable(raw)
        if raw.endswith('\ufffd') or not text.startswith(spoken):
            piece = ''
        else:
            piece, spoken = text[len(spoken):], text
        total, steps = total + change, steps + 1
        yield event('step', {'phase': 'speaking', 'text': piece, **encode(sim.frame(change))})
        time.sleep(PLAYBACK_SECONDS)
    reading = sim.reading(total, steps)
    answer_text = spoken.strip()
    # Every answer gets its share link; the id is stable per question.
    share_id = store.save(question, answer_text, reading) if answer_text else None
    yield event('done', {'answer': answer_text, 'reading': reading, 'id': share_id})


def encode(frame):
    return {**frame, 'beads': base64.b64encode(frame['beads']).decode()}


def client_ip(request):
    # Railway's proxy puts the visitor first in X-Forwarded-For.
    return request.headers.get('x-forwarded-for', '').split(',')[0].strip() or request.client.host


@app.get('/api/ask')
def ask(request: Request, q: str = Query(min_length=1, max_length=160)):
    if 'sim' not in state:
        return JSONResponse({'stage': state['stage']}, status_code=503)
    ip = client_ip(request)
    question = ' '.join(q.split())  # no control characters or runs of whitespace
    # A sync generator: Starlette runs it in a worker thread, so graph steps don't block the loop.
    return StreamingResponse(frames(question, ip), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.get('/api/health')
def health():
    return {'ready': 'sim' in state, 'stage': state['stage']}


# --- Sharing: pages with full social/SEO tags, cards, sitemap ------------------------------------------------

def base_url(request):
    """The public origin: PUBLIC_URL once a custom domain is set, else what the proxy saw."""
    if os.environ.get('PUBLIC_URL'):
        return os.environ['PUBLIC_URL'].rstrip('/')
    proto = request.headers.get('x-forwarded-proto', request.url.scheme)
    return f'{proto}://{request.headers.get("host", request.url.netloc)}'


def display_host(request):
    """The domain as printed on cards: flyfate.com, not www.flyfate.com."""
    host = urlparse(base_url(request)).netloc
    return host[4:] if host.startswith('www.') else host


def page(request, oracle=None):
    if not TEMPLATE:
        return Response('Web build missing.', status_code=500)
    return HTMLResponse(share.render_page(TEMPLATE, base_url(request), oracle),
                        headers={'Cache-Control': 'public, max-age=300'})


def jpeg(data):
    # Cards never change for an id + CARD_VERSION (the og:image URL carries ?v=), so cache them hard.
    return Response(data, media_type='image/jpeg', headers={'Cache-Control': 'public, max-age=31536000, immutable'})


@app.get('/api/oracle/{oid}')
def oracle_json(oid: str):
    found = store.get(oid)
    if not found:
        return JSONResponse({'error': 'not found'}, status_code=404)
    return {k: found[k] for k in ('id', 'question', 'answer', 'reading')}


@app.get('/api/others')
def others(n: int = Query(3, ge=1, le=6)):
    """A few questions other people asked, for the start page: a random pick from the newest public answers
    (shared or saved, and clean), so the page changes from visit to visit even while the archive is small."""
    rows, _ = store.archive(limit=30)
    picked = random.sample(rows, min(n, len(rows)))
    return JSONResponse([{'id': r['id'], 'question': r['question'], 'kind': r['kind']} for r in picked],
                        headers={'Cache-Control': 'no-store'})


@app.post('/api/oracle/{oid}/shared')
def oracle_shared(request: Request, oid: str):
    """The visitor shared this answer (share sheet, copied link or saved card): it may now be indexed and
    goes into the archive. Its card is drawn right away, so the first link preview doesn't wait for it."""
    ok = store.mark_shared(oid)
    if ok:
        counter.event('share')
        host = display_host(request)
        threading.Thread(target=share.card, args=(store, oid, host), daemon=True).start()
    return {'ok': ok}


@app.get('/o/{oid}.jpg')
def oracle_card(request: Request, oid: str):
    data = share.card(store, oid, display_host(request))
    return jpeg(data) if data else Response(status_code=404)


@app.get('/o/{oid}')
def oracle_page(request: Request, oid: str):
    found = store.get(oid)
    # Unknown or mistyped link: the start page, so visitors still land somewhere useful.
    return page(request, found) if found else RedirectResponse('/', status_code=302)


@app.get('/card.jpg')
def home_card(request: Request):
    return jpeg(share.card(store, None, display_host(request)))


@app.get('/')
def home(request: Request):
    return page(request)


@app.get('/how-it-works')
def how_it_works(request: Request):
    return HTMLResponse(about.render(base_url(request)), headers={'Cache-Control': 'public, max-age=3600'})


def archive_page(request, query, kind_id, page):
    if kind_id and not share.kind(kind_id):  # mistyped decision type: the whole archive instead
        return RedirectResponse('/answers', status_code=302)
    body, status = archive.render(base_url(request), store, query, kind_id, page)
    if body is None:
        return Response('Page not found.', status_code=status)
    return HTMLResponse(body, headers={'Cache-Control': 'public, max-age=120'})


@app.get('/answers')
def answers(request: Request, q: str = Query('', max_length=200), page: int = Query(1, ge=1, le=10000)):
    return archive_page(request, q, None, page)


@app.get('/answers/{kind_id}')
def answers_kind(request: Request, kind_id: str, q: str = Query('', max_length=200),
                 page: int = Query(1, ge=1, le=10000)):
    return archive_page(request, q, kind_id, page)


# --- Accounts: saving to the archive through a confirmed email, and the person's collection -------------------

PRIVATE = {'Cache-Control': 'no-store'}
LINK_ERRORS = {'bad': ("That doesn't look like an email address.", 400),
               'limit': ('That was a lot of links. Try again in a few minutes.', 429),
               'failed': ("We couldn't send the email just now. Please try again.", 502)}


def current_user(request):
    return users.user(request.cookies.get(accounts.COOKIE))


async def form_fields(request):
    return {k: v[0] for k, v in parse_qs((await request.body()).decode(errors='replace')).items()}


def send_link(request, email, oid=None):
    """Mail a confirmation link. Returns 'sent' or a key of LINK_ERRORS."""
    email = email.strip().lower()
    if not accounts.mail_ready():
        return 'failed'
    if not accounts.EMAIL.match(email):
        return 'bad'
    if not users.allow(email, client_ip(request)):
        return 'limit'
    token = users.link(email, oid)
    mail = accounts.link_mail(f'{base_url(request)}/auth?t={token}', store.get(oid) if oid else None)
    return 'sent' if accounts.send(email, *mail) else 'failed'


def saved_now(request, user, oid):
    users.save(user, oid)
    counter.event('save')
    # The card gets drawn right away, like on sharing, so the archive's previews are instant.
    threading.Thread(target=share.card, args=(store, oid, display_host(request)), daemon=True).start()


@app.post('/api/save')
async def api_save(request: Request):
    """Save an answer to the archive: at once when logged in, else by an emailed confirmation link."""
    body = await request.json()
    oid = str(body.get('id', ''))
    if not store.get(oid):
        return JSONResponse({'error': 'not found'}, status_code=404)
    user = current_user(request)
    if user:
        saved_now(request, user['id'], oid)
        return {'saved': True}
    result = await run_in_threadpool(send_link, request, str(body.get('email', '')), oid)
    if result != 'sent':
        message, status = LINK_ERRORS[result]
        return JSONResponse({'error': message}, status_code=status)
    return {'sent': True}


@app.get('/api/me')
def api_me(request: Request, id: str = ''):
    """Who is logged in, whether this answer is in their collection, and whether email links can go out."""
    user = current_user(request)
    if not user:
        return JSONResponse({'user': None, 'mail': accounts.mail_ready()}, headers=PRIVATE)
    return JSONResponse({'user': {'email': user['email']}, 'saved': bool(id) and users.saved(user['id'], id),
                         'mail': accounts.mail_ready()}, headers=PRIVATE)


@app.get('/auth')
def auth(request: Request, t: str = ''):
    """The emailed link: one click saves the answer and logs in, straight to the collection."""
    result = users.redeem(t)
    if not result:
        return HTMLResponse(archive.expired_page(), headers=PRIVATE)
    session, user, oid = result
    if oid:
        saved_now(request, user, oid)
    response = RedirectResponse(f'/me?saved={oid}' if oid else '/me', status_code=303)
    response.set_cookie(accounts.COOKIE, session, max_age=accounts.SESSION_SECONDS, httponly=True,
                        secure=base_url(request).startswith('https'), samesite='lax')
    return response


@app.get('/me')
def me(request: Request, saved: str = ''):
    user = current_user(request)
    if not user:
        return HTMLResponse(archive.login_page(), headers=PRIVATE)
    rows = users.collection(user['id'])
    return HTMLResponse(archive.collection_page(user, rows, saved=bool(saved) and users.saved(user['id'], saved)),
                        headers=PRIVATE)


@app.post('/login')
async def login(request: Request):
    result = await run_in_threadpool(send_link, request, (await form_fields(request)).get('email', ''))
    if result == 'sent':
        return HTMLResponse(archive.login_page(sent=True), headers=PRIVATE)
    message, status = LINK_ERRORS[result]
    return HTMLResponse(archive.login_page(error=message), status_code=status, headers=PRIVATE)


@app.post('/logout')
def logout(request: Request):
    users.logout(request.cookies.get(accounts.COOKIE))
    response = RedirectResponse('/me', status_code=303)
    response.delete_cookie(accounts.COOKIE)
    return response


# --- Stats: our own visitor counts (stats.py), public ----------------------------------------------------------

@app.get('/stats')
def stats_page(days: int = Query(30, ge=1, le=365)):
    return HTMLResponse(stats.render(counter, store, days), headers={'Cache-Control': 'public, max-age=60'})


@app.get('/robots.txt')
def robots(request: Request):
    return PlainTextResponse(f'User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /auth\nDisallow: /me\nDisallow: /stats\nSitemap: {base_url(request)}/sitemap.xml\n')


@app.get('/sitemap.xml')
def sitemap(request: Request):
    base = base_url(request)
    return Response(share.sitemap(base, store, archive.sitemap_urls(base, store)), media_type='application/xml',
                    headers={'Cache-Control': 'public, max-age=3600'})


# The web build, when present (in the Docker image). In development Vite serves it instead.
TEMPLATE = (WEB_DIST / 'index.html').read_text(encoding='utf-8') if (WEB_DIST / 'index.html').exists() else None
if WEB_DIST.is_dir():
    app.mount('/', StaticFiles(directory=WEB_DIST, html=True), name='web')
