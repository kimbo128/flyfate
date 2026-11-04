import { Vector3 } from 'three'
import { GROUPS, baseRoi, groupOf } from './regions'

// Shared, mutable brain state. React never re-renders from it; the 3D scene reads it every frame.
// Frames come from the simulation service (real graph) or, offline, from the mock below.

export type Phase = 'idle' | 'reading' | 'speaking' | 'verdict'

const NEIGHBOURS = 5

export const brain = {
  names: [] as string[],
  centroids: [] as Vector3[],
  group: new Int8Array(0),
  neighbours: [] as number[][],
  target: new Float32Array(0),
  shown: new Float32Array(0),
  // Per-neuron rattling for the bead sample, 0..1, or null when the mock is running.
  beads: null as Float32Array | null,
  phase: 'idle' as Phase,
  lastFrame: 0,
  // Regions named in the brain reading; they keep glowing after the verdict.
  highlight: [] as number[],
  // When the last verdict landed (performance.now()): the scene plays its shockwave, Melanie her flip.
  verdictAt: 0,
  // Brain tour: the region the camera flies to (-1 = none). The rest of the brain turns to glass around it.
  focus: -1,
  focusAt: 0,
  // Where the focused region is in world space right now (the brain turns and bobs), for the camera.
  focusPoint: new Vector3(),
}

export function registerRegions(names: string[], centroids: Vector3[]) {
  brain.names = names
  brain.centroids = centroids
  brain.group = Int8Array.from(names, (n) => GROUPS.indexOf(groupOf(n)))
  brain.neighbours = centroids.map((c, i) =>
    centroids
      .map((o, j) => ({ j, d: i === j ? Infinity : c.distanceToSquared(o) }))
      .sort((a, b) => a.d - b.d)
      .slice(0, NEIGHBOURS)
      .map((x) => x.j),
  )
  brain.target = new Float32Array(names.length)
  brain.shown = new Float32Array(names.length)
}

export function resetFrames() {
  brain.beads = null
  brain.highlight = []
  brain.focus = -1
}

// Fly to one region of the brain reading, or back out (-1).
export function focusRegion(region: number) {
  if (region === brain.focus) return
  brain.focus = region
  brain.focusAt = performance.now()
}

// One real graph step: region rattling and the bead sample, straight from the simulation.
export function applyFrame(regions: number[], beads: Uint8Array) {
  for (let i = 0; i < regions.length && i < brain.target.length; i++) brain.target[i] = regions[i]
  if (!brain.beads || brain.beads.length !== beads.length) brain.beads = new Float32Array(beads.length)
  for (let k = 0; k < beads.length; k++) brain.beads[k] = beads[k] / 255
  brain.lastFrame = performance.now()
}

// Offline stand-in for one graph step: decay, drive the focus groups, a few sparks, spread to neighbours.
export function mockStep(focus: number[], drive: number) {
  const a = brain.target
  for (let i = 0; i < a.length; i++) {
    a[i] *= 0.6
    if (focus.includes(brain.group[i])) a[i] += drive * (0.35 + 0.65 * Math.random())
    if (Math.random() < 0.025) a[i] += 0.5 * Math.random()
  }
  const spread = Float32Array.from(a, (v, i) => {
    const nb = brain.neighbours[i]
    let m = 0
    for (const j of nb) m += a[j]
    return 0.82 * v + 0.18 * (m / nb.length)
  })
  for (let i = 0; i < a.length; i++) a[i] = Math.min(1, spread[i])
  brain.lastFrame = performance.now()
}

// Called every frame: a resting brain still flickers a little, and the display eases towards the target.
export function frameStep(dt: number, time: number) {
  const { target, shown } = brain
  const resting = brain.phase === 'idle' || brain.phase === 'verdict'
  const touring = brain.focus >= 0
  // The focused region beats like a heart: a quick double pulse, then a pause.
  const beat = Math.max(0, Math.sin(time * 5.5)) ** 6 * (Math.sin(time * 2.75) > 0 ? 1 : 0.55)
  for (let i = 0; i < target.length; i++) {
    if (resting) {
      const lit = brain.phase === 'verdict' && brain.highlight.includes(i)
      const breath = touring
        ? i === brain.focus ? 0.5 + 0.5 * beat : 0.02
        : lit ? 0.42 + 0.14 * Math.sin(time * 1.3 + i) : 0.04 + 0.04 * Math.sin(time * 0.7 + i * 1.7)
      const rate = touring ? (i === brain.focus ? 12 : 3) : brain.phase === 'verdict' ? 0.8 : 1.2
      target[i] += (breath - target[i]) * Math.min(1, dt * rate)
    }
    shown[i] += (target[i] - shown[i]) * Math.min(1, dt * 9)
  }
  if (resting && brain.beads) for (let k = 0; k < brain.beads.length; k++) brain.beads[k] *= Math.max(0, 1 - dt * 1.5)
}

// A region and its mirror twin glow together, since the reading names one side only.
export function highlight(regions: number[]) {
  const bases = regions.map((r) => baseRoi(brain.names[r]))
  brain.highlight = brain.names.flatMap((n, i) => (bases.includes(baseRoi(n)) ? [i] : []))
  brain.verdictAt = performance.now()
}
