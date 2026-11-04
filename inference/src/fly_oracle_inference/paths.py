import os
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2]  # .../inference
# Small derived data that ships with the code (neuron -> region map, bead sample).
ASSETS = PACKAGE / 'assets'
# Large data stays outside git and is shared between worktrees via FLY_ORACLE_HOME (a volume on Railway).
HOME = Path(os.environ.get('FLY_ORACLE_HOME', PACKAGE))
DATA = HOME / 'data'
INPUTS = DATA / 'source'
MODEL = DATA / 'lfm25'
VENDOR = HOME / 'vendor' / 'flm'
GRAPH = VENDOR / 'cache' / 'malecns_v1'
WEB = PACKAGE.parent / 'web'
WEB_BRAIN = WEB / 'public' / 'brain'
WEB_DIST = Path(os.environ.get('WEB_DIST', WEB / 'dist'))
