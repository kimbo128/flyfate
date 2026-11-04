"""The real fly graph, driven token by token exactly as in FLM.

Every token's LFM2.5 input embedding goes through FLM's Reservoir.step over all 166,700 neurons
and 25.6 million connections. What we show is how much each neuron's state changes per token
("rattling"), summed per brain region, plus the change of a fixed sample of neurons.
The readout features of each step feed the trained adapter that nudges the answer (oracle.py).
"""
import re
import sys
import threading
import time
from typing import NamedTuple

import numpy as np
from tokenizers import Tokenizer

from .paths import ASSETS, MODEL, VENDOR
from .runtime import EMBEDDINGS

# The oracle's own instruction replaces FLM's chat persona.
SYSTEM = ('You are Melanie, a cheerful fruit fly oracle. Always commit to one clear decision: for yes/no '
          'questions start with Yes or No, for "A or B" name the one you pick, for open questions give one '
          'concrete suggestion. Add one short, playful reason from a fruit fly\'s point of view. One or two short '
          'sentences, one line. Never hedge, never say it depends. Answer in the language of the question.')

# A small model follows examples better than rules. They are part of the fixed, public prefix:
# the graph runs them once at startup and llama.cpp keeps them cached.
EXAMPLES = [
    ('Should I go to the party tonight?', 'Yes! Parties have snacks, and snacks are where the buzz is.'),
    ('Tea or coffee?', 'Tea. Coffee makes my wings jittery.'),
    ('Should I lend my friend money?', 'No. Keep your sugar where you can see it.'),
    ('What should I cook tonight?', 'Pasta with ripe tomatoes. Ripe tomatoes are the best smell in the world.'),
    ('Soll ich ein neues Velo kaufen?', 'Ja! Mit einem neuen Velo bist du fast so schnell wie ich.'),
]


class Step(NamedTuple):
    change: np.ndarray    # |state change| per neuron
    state: np.ndarray     # new state
    features: np.ndarray  # FLM's 128 readout features, what the adapter reads
    seconds: float


def bf16_row(raw, token):
    # The embedding table is stored as raw bfloat16 bits; widen to float32.
    return (raw[token].astype(np.uint32) << 16).view(np.float32)


# LFM2.5 chat format (chat_template.jinja), without tools or thinking, split at the user turn.
def system_turn(system, examples=()):
    turns = ''.join(f'{user_turn(q)}{a}<|im_end|>\n' for q, a in examples)
    return f'<|startoftext|><|im_start|>system\n{system}<|im_end|>\n{turns}'


def user_turn(question):
    return f'<|im_start|>user\n{question}<|im_end|>\n<|im_start|>assistant\n'


class Simulator:
    def __init__(self):
        t = time.perf_counter()
        sys.path.insert(0, str(VENDOR))
        from flm.graph import Connectome, Reservoir  # fetched by runtime.ensure()

        self.graph = Connectome(verify=False)
        self.tokenizer = Tokenizer.from_file(str(MODEL / 'tokenizer.json'))
        # In RAM (268 MB), not memory-mapped: the adapter gathers 1,024 scattered rows per answer token.
        self.embeddings = np.load(EMBEDDINGS)
        self.reservoir = Reservoir(self.graph, self.embeddings.shape[1])
        self.lock = threading.Lock()

        # Region index per graph neuron (same order as the web meshes), and the bead sample.
        brain_map = np.load(ASSETS / 'brain_map.npz')
        self.region = brain_map['region'].astype(np.int64)
        self.regions = len(brain_map['region_names'])
        self.beads = brain_map['beads']
        self.cell_type = brain_map['cell_type']
        self.cell_type_names = brain_map['cell_type_names']
        self.region_names = [str(n) for n in brain_map['region_names']]
        self.placed = self.region >= 0
        self.region_size = np.maximum(1, np.bincount(self.region[self.placed], minlength=self.regions))

        # The system prompt is public and fixed: run it once and start every question from there.
        self.system_ids = self.encode(system_turn(SYSTEM, EXAMPLES))
        self.base_state = self._run(self.system_ids)
        self._calibrate()
        # What "usual" means for the brain reading, measured over many real questions and answers
        # (scripts/calibrate_reading.py). Without it, the few samples above stand in.
        path = ASSETS / 'reading_baseline.npz'
        self.baseline = dict(np.load(path)) if path.exists() else None
        print(f'Simulator ready in {time.perf_counter() - t:.1f}s', flush=True)

    def encode(self, text):
        return self.tokenizer.encode(text, add_special_tokens=False).ids

    def _run(self, ids):
        self.reservoir.reset()
        for i in ids:
            self.reservoir.step(bf16_row(self.embeddings, i))
        return self.reservoir.state.copy()

    def _calibrate(self):
        """Typical per-region change per token, so the display shows unusual rattling, not size."""
        samples = []
        for q in ['Should I quit my job?', 'Pizza or sushi?', 'What should I do this weekend?']:
            for step in self.steps(self.encode(user_turn(q) + 'Yes. Do it now.')):
                samples.append(step.change)
        regional = np.array([self._regional(c) for c in samples])
        self.region_typical = regional.mean(axis=0) + 1e-9
        self.region_low = np.percentile(regional, 20, axis=0)
        self.region_high = np.percentile(regional, 98, axis=0) + 1e-9

    def _regional(self, change):
        return np.bincount(self.region[self.placed], weights=change[self.placed], minlength=self.regions) / self.region_size

    def step(self, x, token):
        """One graph update from state x. Each caller carries its own state; FLM's Reservoir is shared,
        so it is only borrowed for the step itself and no lock is ever held across a yield."""
        t = time.perf_counter()
        with self.lock:
            self.reservoir.state = x
            features = self.reservoir.step(bf16_row(self.embeddings, token))
            new = self.reservoir.state  # step() assigns a fresh array, x stays untouched
        return Step(np.abs(new - x), new, features, time.perf_counter() - t)

    def steps(self, ids, start=None):
        x = self.base_state if start is None else start
        for i in ids:
            step = self.step(x, i)
            yield step
            x = step.state

    def frame(self, change):
        """One display frame: region rattling 0..1, bead rattling as bytes, neurons clearly active.

        FLM's input interface spreads every token over random neurons across the whole graph, so
        the whole brain always moves. The display therefore shows what rattles more than the rest
        in this step: regions relative to the frame's median, beads only for the top few percent.
        """
        r = (self._regional(change) - self.region_low) / (self.region_high - self.region_low)
        r = 0.3 + 1.4 * (r - np.median(r))
        bead = change[self.beads]
        low, high = np.percentile(bead, [90, 99.5])
        b = np.clip((bead - low) / (high - low + 1e-9), 0, 1)
        return {
            'regions': np.round(np.clip(r, 0, 1), 3).tolist(),
            'beads': (b * 255).astype(np.uint8).tobytes(),
            'active': int((change > 0.25).sum()),
        }

    def reading(self, total, steps, count=3):
        """The brain reading, measured: the regions that rattled most unusually over the whole question and
        answer, how much above their usual level, how many of their neurons fired hard, and the real cell
        types leading. Ranked by how far each region is outside its usual spread across many questions, so
        a region that always swings a lot doesn't win every time."""
        regional = self._regional(total) / steps
        if self.baseline is not None:
            typical = self.baseline['mean']
            score = (regional - typical) / self.baseline['std']
        else:
            typical = self.region_typical
            score = regional / typical
        typical = np.maximum(typical, 1e-12)  # regions without placed neurons
        factor = regional / typical
        score[self.region_size < 20] = -np.inf  # tiny regions are too noisy to rank
        per_token = total / steps
        picked, sides = [], set()
        for r in np.argsort(score)[::-1]:
            base = re.sub(r'\((L|R)\)$', '', self.region_names[r])
            if base in sides:  # left and right of the same region would say the same thing twice
                continue
            sides.add(base)
            members = np.flatnonzero(self.region == r)
            # Firing hard = changing at least twice as much per token as the region typically does.
            hot = members[per_token[members] > 2 * typical[r]]
            leaders = hot if len(hot) else members[np.argsort(total[members])[-20:]]
            codes, counts = np.unique(self.cell_type[leaders], return_counts=True)
            top = np.argsort(counts)[::-1][:2]
            picked.append({
                'region': int(r), 'factor': round(float(factor[r]), 2), 'active': int(len(hot)),
                'neurons': int(len(members)),
                'types': [[str(self.cell_type_names[codes[i]]), int(counts[i])] for i in top],
            })
            if len(picked) == count:
                break
        return picked

    def question_ids(self, question):
        return self.encode(user_turn(question))
