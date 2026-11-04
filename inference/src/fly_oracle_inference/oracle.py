"""Melanie's answers: LFM2.5 (GGUF via llama.cpp) plus FLM's trained fly adapter, as in FLM's generate().

Per answer token: the fly graph steps on the previous token, the adapter turns the graph's 128 readout
features into a hidden-size delta, and the logit change is delta @ E^T (LFM2.5 ties its output layer to the
input embeddings E), bounded to an RMS of 0.25 over the whole vocabulary, then added to the model's logits.

Two shortcuts keep the server small, both documented here:
- The RMS over all 65,536 tokens is computed exactly from the Gram matrix E^T E (2048 x 2048), so the full
  change vector is never needed.
- The change itself is only computed for the 1,024 most likely tokens. With top-k 50 sampling and a change
  bounded this tightly, a token outside those 1,024 cannot realistically be picked.
The backbone runs 4-bit quantized (Q4_K_M); FLM trained its adapter against the full-precision model.
"""
import os
import threading
import time
import zlib

import llama_cpp
import numpy as np
from scipy.special import erf

from .paths import ASSETS, DATA
from .runtime import GGUF

# FLM's conversation settings (flm/conversation_config.py).
SAMPLING = {'temperature': 0.4, 'top_k': 50, 'top_p': 0.9, 'repetition_penalty': 1.05}
ADAPTER_SCALE = 0.03
MAX_LOGIT_RMS = 0.25
CANDIDATES = 1024
MAX_ANSWER_TOKENS = 60
EOS = 7  # <|im_end|>
GRAM = DATA / 'embed_gram.npy'


class Adapter:
    """FLM's FlyAdapter in numpy: scale * tanh(W_out @ gelu(W_in @ features)), exact-erf GELU as in torch."""

    def __init__(self, path):
        weights = np.load(path)
        self.w_in = weights['input'].astype(np.float32)   # (128, 128)
        self.w_out = weights['output'].astype(np.float32)  # (2048, 128)

    def __call__(self, features):
        h = self.w_in @ features.astype(np.float32)
        h = 0.5 * h * (1 + erf(h / np.float32(np.sqrt(2))))
        # float32 throughout: a float64 delta would make every product below copy its float32 matrix.
        return (ADAPTER_SCALE * np.tanh(self.w_out @ h)).astype(np.float32)


def bf16_rows(table, rows):
    return (table[rows].astype(np.uint32) << 16).view(np.float32)


def gram(table):
    """E^T E over the bf16 embedding table, in chunks, cached on the volume."""
    if GRAM.exists():
        return np.load(GRAM)
    g = np.zeros((table.shape[1], table.shape[1]), np.float64)
    for start in range(0, table.shape[0], 8192):
        chunk = bf16_rows(table, slice(start, start + 8192)).astype(np.float64)
        g += chunk.T @ chunk
    g = g.astype(np.float32)
    np.save(GRAM, g)
    return g


class Oracle:
    def __init__(self, embeddings, prefix_ids, stop_ids):
        self.embeddings = embeddings  # raw bf16 bits, (65536, 2048)
        self.vocab = embeddings.shape[0]
        self.gram = gram(embeddings)
        self.adapter = Adapter(ASSETS / 'adapter.npz')
        self.stop_ids = stop_ids  # tokens that start a new line: an oracle answer is one line
        threads = int(os.environ.get('LLM_THREADS', min(8, os.cpu_count() or 4)))
        self.llm = llama_cpp.Llama(model_path=str(GGUF), n_ctx=1024, n_threads=threads, verbose=False)
        # The fixed system prompt and examples are evaluated once; each answer restarts from a snapshot.
        # LFM2 is a hybrid (convolution + attention) model: its recurrent state can't be rewound by
        # trimming the KV cache, so the whole state is saved and restored.
        self.prefix = list(prefix_ids)
        self.llm.eval(self.prefix)
        self.prefix_state = self.llm.save_state()
        # One llama.cpp context: answers are generated one at a time, without yielding inside.
        self.lock = threading.Lock()

    def logits(self):
        return np.ctypeslib.as_array(llama_cpp.llama_get_logits_ith(self.llm.ctx, -1), shape=(self.vocab,)).copy()

    def fly_change(self, features, candidates):
        """Bounded logit change for the candidate tokens, from the graph's readout features."""
        delta = self.adapter(features)
        rms = np.sqrt(max(float(delta @ self.gram @ delta) / self.vocab, 0.0) + 1e-12)
        return (bf16_rows(self.embeddings, candidates) @ delta) * min(1.0, MAX_LOGIT_RMS / rms)

    def sample(self, logits, candidates, change, seen, rng):
        """FLM's sample_token on the candidate set: repetition penalty, temperature, top-k, top-p."""
        values = logits[candidates] + change
        repeated = np.isin(candidates, seen)
        values = np.where(repeated, np.where(values < 0, values * SAMPLING['repetition_penalty'],
                                             values / SAMPLING['repetition_penalty']), values)
        top = np.argsort(values)[::-1][:SAMPLING['top_k']]
        scaled = values[top] / SAMPLING['temperature']
        p = np.exp(scaled - scaled.max())
        p /= p.sum()
        # Keep the first token crossing the nucleus threshold, as well as all before it.
        p[(np.cumsum(p) - p) > SAMPLING['top_p']] = 0
        p /= p.sum()
        return int(candidates[top[rng.choice(len(top), p=p)]])

    def answer(self, question_ids, features, graph_step, seed_text):
        """Generate the answer to the question turn after the fixed prefix. `graph_step(token)` advances
        this request's graph and returns (readout features, state change). Returns [(token, change)].
        The sampling seed comes from the question, so the same question gets the same answer."""
        rng = np.random.default_rng(zlib.crc32(seed_text.lower().strip().encode()))
        out = []
        clock = time.perf_counter
        spent = dict.fromkeys(('restore', 'prefill', 'llm', 'fly', 'graph'), 0.0)
        with self.lock:
            t = clock()
            self.llm.load_state(self.prefix_state)
            spent['restore'] = clock() - t
            t = clock()
            self.llm.eval(question_ids)
            spent['prefill'] = clock() - t
            seen = self.prefix + list(question_ids)
            for _ in range(MAX_ANSWER_TOKENS):
                t = clock()
                logits = self.logits()
                candidates = np.argpartition(logits, -CANDIDATES)[-CANDIDATES:]
                token = self.sample(logits, candidates, self.fly_change(features, candidates), seen, rng)
                spent['fly'] += clock() - t
                if token == EOS or token in self.stop_ids:
                    break
                t = clock()
                features, change = graph_step(token)
                spent['graph'] += clock() - t
                out.append((token, change))
                seen.append(token)
                t = clock()
                self.llm.eval([token])
                spent['llm'] += clock() - t
        self.last_timing = {k: round(v, 2) for k, v in spent.items()}
        return out
