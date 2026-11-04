"""Keep a public single-instance service usable: per-IP and global limits, a fair queue, serious topics.

Everything is in memory; that is enough for one replica. Restarting the service resets the counters.
"""
import re
import threading
import time
from collections import defaultdict, deque

# (questions, seconds). Generous: people try a handful of questions in a row, and a household or office
# shares one IP. The global daily cap is what keeps the bill bounded: a question costs about a second of CPU,
# so 20,000 a day stay a few dollars, and a launch day doesn't hit the cap by noon.
PER_IP = [(20, 600), (150, 86400)]
GLOBAL_PER_DAY = 20000
# A turn holds the queue for about a second (the answer plays back outside it), so 50 waiting is under a minute.
MAX_WAITING = 50

# Questions where a joke oracle would be the wrong answer. Deliberately broad.
SERIOUS = re.compile(
    r'\b(suicid\w*|kill (my|him|her|them)sel\w*|end (my|it all)|self[- ]?harm\w*|hurt (my|him|her|them)sel\w*|'
    r'overdos\w*|want to die|don\'?t want to live|abus(e|ed|ing)|rape\w*|emergency|heart attack|stroke|'
    r'chest pain|can\'?t breathe|poison\w*)\b', re.I)
SERIOUS_ANSWER = ("This one is too important for a fruit fly. If you or someone else might be in danger, "
                  "please contact local emergency services or a crisis line, or talk to someone you trust right now.")


class Limits:
    def __init__(self):
        self.lock = threading.Lock()
        self.by_ip = defaultdict(deque)
        self.day = deque()

    def allow(self, ip):
        """None if allowed (and counted), else (friendly reason, seconds until the next question is allowed)."""
        now = time.time()
        with self.lock:
            while self.day and now - self.day[0] > 86400:
                self.day.popleft()
            if len(self.day) >= GLOBAL_PER_DAY:
                return ("I've answered so many questions today that my wings need a rest. Come back tomorrow!",
                        int(self.day[0] + 86400 - now) + 1)
            seen = self.by_ip[ip]
            while seen and now - seen[0] > PER_IP[-1][1]:
                seen.popleft()
            for count, window in PER_IP:
                recent = [t for t in seen if now - t <= window]
                if len(recent) >= count:
                    wait = int(recent[0] + window - now) + 1
                    return ("Slow down, I'm only a fly! I need a short break." if window < 3600
                            else "That's enough wisdom for one day. Come back tomorrow!", wait)
            seen.append(now)
            self.day.append(now)
            return None


STALE = 6  # seconds without a sign of life before a place in line is given up


class Queue:
    """First come, first served; one question runs through the graph at a time.

    A visitor who closes the tab may never let go of their ticket (the stream just stops being read),
    so every waiting or running stream touches its ticket, and silent tickets are dropped.
    """

    def __init__(self):
        self.cond = threading.Condition()
        self.line = deque()
        self.seen = {}
        self.next_ticket = 0

    def join(self):
        with self.cond:
            self._prune()
            if len(self.line) > MAX_WAITING:
                return None
            ticket = self.next_ticket
            self.next_ticket += 1
            self.line.append(ticket)
            self.seen[ticket] = time.time()
            return ticket

    def touch(self, ticket):
        with self.cond:
            self.seen[ticket] = time.time()

    def position(self, ticket):
        with self.cond:
            self._prune()
            return self.line.index(ticket) if ticket in self.line else 0

    def wait_turn(self, ticket, timeout):
        """Wait up to `timeout` seconds; True when it's this ticket's turn."""
        with self.cond:
            self.seen[ticket] = time.time()
            self._prune()
            return self.cond.wait_for(lambda: not self.line or self.line[0] == ticket, timeout)

    def leave(self, ticket):
        with self.cond:
            if ticket in self.line:
                self.line.remove(ticket)
            self.seen.pop(ticket, None)
            self.cond.notify_all()

    def _prune(self):
        now = time.time()
        for t in [t for t in self.line if now - self.seen.get(t, 0) > STALE]:
            self.line.remove(t)
            self.seen.pop(t, None)
        self.cond.notify_all()
