"""Fetch the share-card fonts from Google Fonts (OFL) and cut M PLUS Rounded down to Latin.

Output: inference/assets/fonts/. Both families carry Korean or Japanese and would be 1.5-3.5 MB each, so only
Latin, punctuation and a few symbols are kept.
"""
import io
import urllib.request
from pathlib import Path

from fontTools import subset

OUT = Path(__file__).resolve().parents[1] / 'assets' / 'fonts'
RAW = 'https://raw.githubusercontent.com/google/fonts/main/ofl/'
# Latin, Greek (the mushroom body's α/β/γ lobes), punctuation, a few symbols.
LATIN = 'U+0000-024F,U+0370-03FF,U+2010-2027,U+2030-205E,U+20AC,U+2122,U+2190-21FF'


def fetch(path):
    with urllib.request.urlopen(RAW + path, timeout=120) as r:
        return r.read()


def latin(path, name):
    options = subset.Options()
    options.layout_features = ['*']
    font = subset.load_font(io.BytesIO(fetch(path)), options)
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=subset.parse_unicodes(LATIN))
    subsetter.subset(font)
    subset.save_font(font, str(OUT / name), options)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ofl = fetch('bagelfatone/OFL.txt').decode()
    (OUT / 'OFL-BagelFatOne.txt').write_text(ofl)
    body = ofl[ofl.index('This Font Software is licensed'):]
    (OUT / 'OFL-MPLUSRounded1c.txt').write_text('Copyright 2016 The Rounded M+ Project Authors.\n\n' + body)
    latin('bagelfatone/BagelFatOne-Regular.ttf', 'BagelFatOne-Regular.ttf')
    for weight in ('ExtraBold', 'Medium'):
        latin(f'mplusrounded1c/MPLUSRounded1c-{weight}.ttf', f'MPLUSRounded1c-{weight}.ttf')
    for f in sorted(OUT.iterdir()):
        print(f'{f.name:32s} {f.stat().st_size // 1024:6d} KB')


if __name__ == '__main__':
    main()
