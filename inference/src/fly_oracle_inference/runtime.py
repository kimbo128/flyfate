"""Make sure the runtime data exists under $FLY_ORACLE_HOME, fetching it from public sources once.

On Railway this runs on a volume at first start (a few minutes) and is a no-op afterwards:
- FLM's code, pinned to a commit (MIT)
- the FLM graph, built by FLM's own hash-checked script from the public MaleCNS v1.0 files
- the LFM2.5 tokenizer, and only its input embedding table (byte-range request, 268 MB instead of 2.3 GB)
- Liquid AI's official 4-bit GGUF of LFM2.5 for llama.cpp (731 MB), pinned to a revision
"""
import io
import json
import shutil
import struct
import sys
import tarfile
import urllib.request

import numpy as np

from .paths import DATA, GRAPH, INPUTS, MODEL, VENDOR

FLM_COMMIT = '7251a8921db4f891c39bd75ee5ad827f7031a24b'
FLM_TARBALL = f'https://codeload.github.com/nftechie/flm/tar.gz/{FLM_COMMIT}'
LFM = 'https://huggingface.co/LiquidAI/LFM2.5-1.2B-Instruct/resolve/0f604ada3f766f9f257460c4c9f0b5d6f69d431b/'
EMBEDDINGS = DATA / 'embed_tokens.npy'
GGUF_URL = ('https://huggingface.co/LiquidAI/LFM2.5-1.2B-Instruct-GGUF/resolve/'
            '8ed288026e23958ad9dfa92d53ed773a8eee7125/LFM2.5-1.2B-Instruct-Q4_K_M.gguf')
GGUF = DATA / 'lfm25-q4_k_m.gguf'


def log(message):
    print(f'[runtime] {message}', flush=True)


def fetch(url, headers=None):
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=600) as r:
        return r.read()


def ensure_flm():
    if (VENDOR / 'flm' / 'graph.py').exists():
        return
    log('Fetching FLM code')
    with tarfile.open(fileobj=io.BytesIO(fetch(FLM_TARBALL)), mode='r:gz') as tar:
        root = tar.getmembers()[0].name.split('/')[0]
        VENDOR.parent.mkdir(parents=True, exist_ok=True)
        tar.extractall(VENDOR.parent, filter='data')
    shutil.move(str(VENDOR.parent / root), str(VENDOR))


def ensure_graph():
    if (GRAPH / 'manifest.json').exists():
        return
    log('Building the fly graph from MaleCNS v1.0 (downloads about 1 GB)')
    sys.path.insert(0, str(VENDOR))
    from scripts.prepare_graph import prepare  # FLM's own, hash-checked preparation
    prepare(INPUTS)
    shutil.rmtree(INPUTS, ignore_errors=True)  # the raw files are no longer needed


def ensure_tokenizer():
    MODEL.mkdir(parents=True, exist_ok=True)
    for name in ('tokenizer.json', 'LICENSE'):
        if not (MODEL / name).exists():
            log(f'Fetching LFM2.5 {name}')
            (MODEL / name).write_bytes(fetch(LFM + name))


def ensure_embeddings():
    """Only model.embed_tokens.weight (bfloat16, kept as raw uint16), via HTTP range requests."""
    if EMBEDDINGS.exists():
        return
    log('Fetching the LFM2.5 input embedding table')
    url = LFM + 'model.safetensors'
    size = struct.unpack('<Q', fetch(url, {'Range': 'bytes=0-7'}))[0]
    header = json.loads(fetch(url, {'Range': f'bytes=8-{7 + size}'}))
    info = header['model.embed_tokens.weight']
    assert info['dtype'] == 'BF16'
    start, end = (8 + size + o for o in info['data_offsets'])
    raw = fetch(url, {'Range': f'bytes={start}-{end - 1}'})
    table = np.frombuffer(raw, np.uint16).reshape(info['shape'])
    partial = EMBEDDINGS.with_suffix('.partial.npy')
    np.save(partial, table)
    partial.replace(EMBEDDINGS)


def ensure_gguf():
    if GGUF.exists():
        return
    log('Fetching the LFM2.5 GGUF (731 MB)')
    partial = GGUF.with_suffix('.partial')
    with urllib.request.urlopen(GGUF_URL, timeout=600) as r, open(partial, 'wb') as f:
        shutil.copyfileobj(r, f, 16 * 1024 * 1024)
    partial.replace(GGUF)


def ensure():
    ensure_flm()
    ensure_graph()
    ensure_tokenizer()
    ensure_embeddings()
    ensure_gguf()
