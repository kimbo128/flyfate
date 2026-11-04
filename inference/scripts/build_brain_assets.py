"""Download the public MaleCNS v1.0 ROI meshes (brain and nerve cord) and pack them into one GLB.

Source: gs://flyem-male-cns/rois (FlyEM/Janelia, CC BY 4.0). Meshes are neuroglancer
legacy fragments in nanometres. Output: web/public/brain/brain.glb + regions.json.
"""
import json
import struct
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import fast_simplification
import numpy as np
import trimesh

BASE = 'https://storage.googleapis.com/flyem-male-cns/rois/'
# Shells first; the brain shell defines the scene scale.
LAYERS = [('shell', 'brain-shell-v2.2'), ('shell', 'vnc-shell-v2'),
          ('neuropil', 'fullbrain-roi-v5'), ('neuropil', 'malecns-vnc-neuropil-roi-v0')]
OUT = Path(__file__).resolve().parents[2] / 'web' / 'public' / 'brain'
FACES_PER_NEUROPIL = (700, 3200)  # scaled by surface area
FACES_SHELL = 16000


def fetch(url):
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def segments(layer):
    info = json.loads(fetch(f'{BASE}{layer}/segment_properties/info'))['inline']
    return dict(zip(info['ids'], info['properties'][0]['values']))


def load_mesh(layer, segment):
    manifest = json.loads(fetch(f'{BASE}{layer}/mesh/{segment}:0'))
    parts = []
    for fragment in manifest['fragments']:
        raw = fetch(f'{BASE}{layer}/mesh/{fragment}')
        n = struct.unpack_from('<I', raw)[0]
        vertices = np.frombuffer(raw, '<f4', n * 3, 4).reshape(-1, 3)
        faces = np.frombuffer(raw, '<u4', offset=4 + n * 12).reshape(-1, 3)
        parts.append(trimesh.Trimesh(vertices, faces, process=False))
    mesh = trimesh.util.concatenate(parts)
    mesh.update_faces(mesh.unique_faces())
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.merge_vertices(digits_vertex=0)
    return mesh


def simplify(mesh, target, voxels):
    """Remesh, then decimate. The ROI meshes are not manifold; decimating them directly leaves
    long sliver triangles. Voxelizing, filling and marching cubes gives a clean, closed blob."""
    pitch = (mesh.bounds[1] - mesh.bounds[0]).max() / voxels
    grid = mesh.voxelized(pitch).fill()
    out = grid.marching_cubes
    out.apply_transform(grid.transform)
    trimesh.smoothing.filter_taubin(out, iterations=10)
    if len(out.faces) > target:
        v, f = fast_simplification.simplify(out.vertices.astype(np.float32), out.faces.astype(np.int32),
                                            target_reduction=1 - target / len(out.faces), agg=9)
        out = trimesh.Trimesh(v, f)
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [(kind, layer, sid, name) for kind, layer in LAYERS for sid, name in segments(layer).items()]
    with ThreadPoolExecutor(12) as pool:
        meshes = list(pool.map(lambda j: load_mesh(j[1], j[2]), jobs))

    shell = meshes[0]
    center = shell.bounds.mean(axis=0)
    scale = 2.0 / (shell.bounds[1] - shell.bounds[0]).max()
    # MaleCNS: x = left-right, y = dorsal-ventral (down), z = anterior-posterior.
    # Three.js: y up, z towards the viewer (fly faces the camera).
    transform = np.diag([scale, -scale, -scale, 1.0])
    transform[:3, 3] = -center * np.array([scale, -scale, -scale])

    areas = np.array([m.area for m in meshes])
    lo, hi = FACES_PER_NEUROPIL
    targets = np.clip(lo + (hi - lo) * np.sqrt(areas / areas.max()), lo, hi).astype(int)
    targets = [FACES_SHELL if j[0] == 'shell' else t for j, t in zip(jobs, targets)]

    with ThreadPoolExecutor(12) as pool:
        meshes = list(pool.map(lambda a: simplify(a[0], a[1], 140 if a[2][0] == 'shell' else 48),
                               zip(meshes, targets, jobs)))

    scene = trimesh.Scene()
    regions = []
    for (kind, _, _, name), mesh in zip(jobs, meshes):
        mesh.apply_transform(transform)
        mesh.fix_normals()
        scene.add_geometry(mesh, node_name=name, geom_name=name)
        if kind == 'neuropil':
            regions.append({'name': name, 'centroid': np.round(mesh.centroid, 4).tolist(),
                            'volume': round(float(abs(mesh.volume)), 6), 'faces': len(mesh.faces)})
        print(f'{name:14s} {len(mesh.faces):6d} faces', flush=True)

    scene.export(OUT / 'brain.glb')
    (OUT / 'regions.json').write_text(json.dumps({
        'source': 'MaleCNS v1.0 ROI meshes, FlyEM / HHMI Janelia, CC BY 4.0',
        'shells': [j[3] for j in jobs if j[0] == 'shell'],
        'transform': np.round(transform, 9).tolist(),  # MaleCNS nm -> scene units
        'regions': regions}, indent=1) + '\n')
    print(f'{OUT / "brain.glb"}: {(OUT / "brain.glb").stat().st_size / 1e6:.1f} MB')


if __name__ == '__main__':
    main()
