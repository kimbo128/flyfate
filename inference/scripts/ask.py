"""Ask a running server questions from the command line: uv run python scripts/ask.py [--url URL] "Question?" ..."""
import argparse
import json
import time
import urllib.parse
import urllib.request


def ask(url, question):
    started = time.time()
    with urllib.request.urlopen(f'{url}/api/ask?q={urllib.parse.quote(question)}', timeout=120) as r:
        name = None
        for raw in r:
            line = raw.decode()
            if line.startswith('event: '):
                name = line[7:].strip()
            elif line.startswith('data: ') and name in ('done', 'limit'):
                return json.loads(line[6:]), time.time() - started
    return None, time.time() - started


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--url', default='http://127.0.0.1:8000')
    p.add_argument('questions', nargs='+')
    a = p.parse_args()
    for q in a.questions:
        done, seconds = ask(a.url, q)
        print(f'{q}\n  -> {done.get("answer") or done.get("message")}  ({seconds:.1f}s)')
