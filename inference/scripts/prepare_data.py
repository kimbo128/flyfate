"""Derive the small brain map that ships with the code, from public MaleCNS v1.0 files.

1. Download inputs (skipped when present), including the 3 GB synapse table.
2. Build the FLM graph with FLM's own prepare script (same 166,700 neurons, same weights).
3. Assign every neuron its main region and position from its synapses (syn-partners table).
4. Pick a sample of neurons to draw as beads, and the strongest region-to-region wiring.

Outputs (committed): inference/assets/brain_map.npz, web/public/brain/beads.bin and wiring.json.
Run build_brain_assets.py first: step 4 needs the scene transform in regions.json.
Only needed when meshes or the mapping change; the server itself needs just runtime.py's data.
"""
import json
import shutil
import sys
import urllib.request

import numpy as np
import pyarrow as pa
import pyarrow.feather as feather
import pyarrow.ipc as ipc

from fly_oracle_inference.paths import ASSETS, DATA, GRAPH, INPUTS, VENDOR, WEB_BRAIN
from fly_oracle_inference.runtime import ensure_flm

MALECNS = 'https://storage.googleapis.com/flyem-male-cns/v1.0/connectome-data/flat-connectome/'
DOWNLOADS = {
    INPUTS / 'annotations.feather': MALECNS + 'body-annotations-male-cns-v1.0-minconf-0.5.feather',
    INPUTS / 'edges.feather': MALECNS + 'connectome-weights-male-cns-v1.0-minconf-0.5.feather',
    INPUTS / 'syn-partners-significant.feather': MALECNS + 'syn-partners-male-cns-v1.0-minconf-0.5-significant-only.feather',
}
VOXEL_NM = 8
BEADS = 24000
BEADS_MIN_PER_REGION = 40
WIRES = 160


def download():
    for path, url in DOWNLOADS.items():
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f'Downloading {path.name}...', flush=True)
        partial = path.with_suffix('.partial')
        with urllib.request.urlopen(url) as r, open(partial, 'wb') as f:
            shutil.copyfileobj(r, f, 16 * 1024 * 1024)
        partial.replace(path)


def build_graph():
    if (GRAPH / 'manifest.json').exists():
        return
    ensure_flm()
    sys.path.insert(0, str(VENDOR))
    from scripts.prepare_graph import prepare  # FLM's own, hash-checked preparation
    prepare(INPUTS)


def assign_regions():
    """Main region = the region holding most of a neuron's synapses; position = their mean there."""
    out = DATA / 'neurons.npz'
    if out.exists():
        return dict(np.load(out, allow_pickle=False))
    ids = np.load(GRAPH / 'ids.npy')
    n = len(ids)
    lookup = {}  # region name -> column
    width = 160  # more than the ~110 MaleCNS regions
    flats, coords = [], []
    with pa.memory_map(str(INPUTS / 'syn-partners-significant.feather'), 'r') as mapped:
        reader = ipc.open_file(mapped)
        for i in range(reader.num_record_batches):
            b = reader.get_batch(i)
            roi = b.column('primary_post')
            local = np.array([lookup.setdefault(v, len(lookup)) for v in roi.dictionary.to_pylist()], np.int64)
            assert len(lookup) <= width, 'More regions than expected; raise width.'
            valid = roi.is_valid().to_numpy(zero_copy_only=False)
            r = local[roi.indices.to_numpy(zero_copy_only=False)[valid]]
            xyz = np.stack([b.column(k).to_numpy()[valid] for k in ('x_post', 'y_post', 'z_post')], 1)
            # Count each synapse for both partners: it is where both neurons do their work.
            for side in ('body_pre', 'body_post'):
                body = b.column(side).to_numpy()[valid]
                j = np.searchsorted(ids, body)
                keep = (j < n) & (ids[np.minimum(j, n - 1)] == body)
                flats.append(j[keep] * width + r[keep])
                coords.append(xyz[keep].astype(np.float32))
            if i % 200 == 0:
                print(f'  synapse batch {i}/{reader.num_record_batches}', flush=True)
    flat = np.concatenate(flats)
    xyz = np.concatenate(coords)
    del flats, coords
    names = list(lookup)
    counts = np.bincount(flat, minlength=n * width).reshape(n, width)[:, :len(names)]
    main = counts.argmax(1)
    total = counts.sum(1)
    hits = np.maximum(counts[np.arange(n), main], 1)
    # Mean position of each neuron's synapses inside its main region.
    in_main = (flat % width) == main[flat // width]
    owner = flat[in_main] // width
    xyz = np.stack([np.bincount(owner, weights=xyz[in_main, d], minlength=n) / hits for d in range(3)], 1)
    main = np.where(total > 0, main, -1).astype(np.int16)
    result = {'roi_names': np.array(names), 'main_roi': main, 'xyz': xyz.astype(np.float32),
              'synapses': total.astype(np.int32)}
    np.savez(out, **result)
    print(f'{(main >= 0).sum()} of {n} neurons placed in {len(names)} regions', flush=True)
    return result


def cell_types():
    """MaleCNS cell type per graph neuron (e.g. KCg-m, MBON05), as codes into a name list."""
    table = feather.read_table(INPUTS / 'annotations.feather', columns=['bodyId', 'type', 'superclass'])
    ids = np.load(GRAPH / 'ids.npy')
    body = table['bodyId'].to_numpy()
    order = np.searchsorted(body, ids) if np.all(np.diff(body) > 0) else None
    if order is None:
        sort = np.argsort(body)
        order = sort[np.searchsorted(body[sort], ids)]
    kinds = [t or s or 'unnamed' for t, s in zip(table['type'].to_pylist(), table['superclass'].to_pylist())]
    names, codes = np.unique(np.array(kinds, dtype=object)[order].astype(str), return_inverse=True)
    return codes.astype(np.int16 if len(names) < 32768 else np.int32), names


def export_web(neurons):
    """Bead sample (positions in scene units + region index) and the strongest wiring between regions."""
    meta = json.loads((WEB_BRAIN / 'regions.json').read_text())
    mesh_names = [r['name'] for r in meta['regions']]
    transform = np.array(meta['transform'])
    names = list(neurons['roi_names'])
    to_mesh = np.array([mesh_names.index(x) if x in mesh_names else -1 for x in names] + [-1], np.int32)
    region = to_mesh[neurons['main_roi']]  # -1 stays -1 via the trailing sentinel
    missing = sorted({names[i] for i in np.unique(neurons['main_roi']) if i >= 0 and to_mesh[i] < 0})
    if missing:
        print('Regions without mesh (not drawn):', ', '.join(missing))

    rng = np.random.default_rng(7301)
    placed = np.flatnonzero(region >= 0)
    per = np.bincount(region[placed], minlength=len(mesh_names))
    # Square-root quota: the optic lobes hold about half of all neurons and would bury the rest.
    quota = np.maximum(BEADS_MIN_PER_REGION, BEADS * np.sqrt(per) / np.sqrt(per).sum()).astype(int)
    pick = []
    for r in range(len(mesh_names)):
        members = placed[region[placed] == r]
        if len(members):
            pick.append(rng.choice(members, min(len(members), quota[r]), replace=False))
    beads = np.sort(np.concatenate(pick))
    # Synapse points are in 8 nm voxels, the meshes (and the transform) in nanometres.
    xyz = np.c_[neurons['xyz'][beads] * VOXEL_NM, np.ones(len(beads))] @ transform.T
    ASSETS.mkdir(exist_ok=True)
    type_codes, type_names = cell_types()
    np.savez_compressed(ASSETS / 'brain_map.npz', region=region.astype(np.int16), beads=beads.astype(np.int32),
                        region_names=np.array(mesh_names), cell_type=type_codes, cell_type_names=type_names)
    with open(WEB_BRAIN / 'beads.bin', 'wb') as f:
        f.write(np.uint32(len(beads)).tobytes())
        f.write(xyz[:, :3].astype(np.float32).tobytes())
        f.write(region[beads].astype(np.uint16).tobytes())

    # Region-to-region wiring from the exact graph weights (row = postsynaptic).
    indptr, indices, data = (np.load(GRAPH / f'{k}.npy') for k in ('indptr', 'indices', 'data'))
    post = np.repeat(np.arange(len(indptr) - 1), np.diff(indptr))
    rp, rq = region[indices], region[post]
    ok = (rp >= 0) & (rq >= 0) & (rp != rq)
    m = len(mesh_names)
    wiring = np.bincount(rp[ok] * m + rq[ok], weights=data[ok], minlength=m * m).reshape(m, m)
    top = np.argsort(wiring, axis=None)[::-1][:WIRES]
    wires = [[int(i // m), int(i % m), round(float(wiring.flat[i]), 2)] for i in top]
    (WEB_BRAIN / 'wiring.json').write_text(json.dumps({'from_to_weight': wires}) + '\n')
    print(f'{len(beads)} beads, {len(wires)} wires written to {WEB_BRAIN}', flush=True)


if __name__ == '__main__':
    download()
    build_graph()
    export_web(assign_regions())
