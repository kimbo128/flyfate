import { Html, Outlines, useGLTF } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { easing } from 'maath'
import { useMemo, useRef, type CSSProperties } from 'react'
import { suspend } from 'suspend-react'
import {
  AdditiveBlending, BufferAttribute, BufferGeometry, Color, DoubleSide, DynamicDrawUsage, Group, Mesh,
  MeshPhysicalMaterial, Points, QuadraticBezierCurve3, RingGeometry, ShaderMaterial, Vector3,
} from 'three'
import { mergeVertices } from 'three/examples/jsm/utils/BufferGeometryUtils.js'
import { brain, frameStep, registerRegions } from './activity'
import { GROUPS, plainName } from './regions'
import { palette } from '../palette'

// The brain as a premium vinyl toy: soft-touch, clear-coated candy regions in a glassy shell. Activity glows
// (the bloom pass picks up emissive light), regions breathe on springs, signals race as comets along the real
// strongest connections, and every verdict lands with a shockwave and a burst of sparks.

const COMETS = 120
const TRAIL = 7
const BURST = 48
const white = new Color('#ffffff')

type Meta = { shells: string[]; regions: { name: string }[] }

// Region order, real neuron sample and real region-to-region wiring, all written by inference/scripts.
function useBrainData() {
  return suspend(async () => {
    const [meta, beads, wiring] = await Promise.all([
      fetch('/brain/regions.json').then((r) => r.json() as Promise<Meta>),
      fetch('/brain/beads.bin').then((r) => r.arrayBuffer()),
      fetch('/brain/wiring.json').then((r) => r.json() as Promise<{ from_to_weight: [number, number, number][] }>),
    ])
    const count = new Uint32Array(beads, 0, 1)[0]
    return {
      meta,
      beadPositions: new Float32Array(beads, 4, count * 3),
      beadRegions: new Uint16Array(beads.slice(4 + count * 12, 4 + count * 14)),
      wires: wiring.from_to_weight,
    }
  }, ['brain-data'])
}

const glowVertex = /* glsl */ `
  attribute float aState;
  attribute vec3 aColor;
  uniform float uScale;
  varying float vState;
  varying vec3 vColor;
  void main() {
    vState = aState;
    vColor = aColor;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = uScale * aState / -mv.z;
    gl_Position = projectionMatrix * mv;
  }
`

// A neuron firing: a hot white core in a halo of its region's colour, bright enough for the bloom pass.
const glowFragment = /* glsl */ `
  varying float vState;
  varying vec3 vColor;
  void main() {
    float d = length(gl_PointCoord * 2.0 - 1.0);
    if (d > 1.0 || vState < 0.05) discard;
    float core = smoothstep(0.35, 0.0, d);
    float halo = pow(1.0 - d, 2.2);
    vec3 col = vColor * halo * 2.2 + vec3(1.0) * core * 1.6;
    gl_FragColor = vec4(col * vState, halo * vState);
    #include <colorspace_fragment>
  }
`

const cometVertex = /* glsl */ `
  attribute float aAlpha;
  uniform float uScale;
  varying float vAlpha;
  void main() {
    vAlpha = aAlpha;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = uScale * (0.35 + aAlpha) / -mv.z;
    gl_Position = projectionMatrix * mv;
  }
`

const cometFragment = /* glsl */ `
  uniform vec3 uColor;
  varying float vAlpha;
  void main() {
    float d = length(gl_PointCoord * 2.0 - 1.0);
    if (d > 1.0 || vAlpha < 0.01) discard;
    float glow = pow(1.0 - d, 2.0);
    gl_FragColor = vec4(mix(uColor, vec3(1.0), glow * glow) * glow * 2.5 * vAlpha, glow * vAlpha);
    #include <colorspace_fragment>
  }
`

// The verdict shockwave: a soft ring that races outward and fades.
const ringFragment = /* glsl */ `
  uniform float uProgress;
  uniform vec3 uColor;
  varying vec2 vUv;
  void main() {
    float a = (1.0 - uProgress) * smoothstep(0.0, 0.15, uProgress);
    gl_FragColor = vec4(uColor * 2.0, a * 0.85);
    #include <colorspace_fragment>
  }
`

type BrainProps = { pixelRatio: number; quality: number; focus?: number }

export function Brain({ pixelRatio, quality, focus = -1 }: BrainProps) {
  const { scene } = useGLTF('/brain/brain.glb')
  const data = useBrainData()
  const group = useRef<Group>(null)
  const tilt = useRef({ yaw: -0.45, sway: 0 })

  const setup = useMemo(() => {
    const byName = new Map<string, Mesh>()
    // Work on a clone: the meshes get re-parented below, which would empty the cached GLTF scene.
    scene.clone(true).traverse((o) => {
      if (!(o as Mesh).isMesh) return
      const mesh = o as Mesh
      // Weld and recompute smooth normals: the decimated ROI meshes carry broken ones.
      const welded = mergeVertices(mesh.geometry.clone().deleteAttribute('normal'), 1e-4)
      welded.computeVertexNormals()
      mesh.geometry = welded
      byName.set(mesh.name, mesh)
    })
    const shells = data.meta.shells.map((n) => byName.get(n)!)
    // Same order as the simulation service sends its region values.
    const regions = data.meta.regions.map((r) => byName.get(r.name)!)

    // The shell: clear glass with a bright rim, so the candy inside reads as a toy in a bubble.
    const shellMaterial = new MeshPhysicalMaterial({
      color: white, transparent: true, opacity: 0.16, roughness: 0.08, metalness: 0, clearcoat: 1,
      clearcoatRoughness: 0.05, depthWrite: false, side: DoubleSide, envMapIntensity: 1.6,
    })
    shells.forEach((s) => {
      s.material = shellMaterial
      s.renderOrder = 2
    })

    // Centre each region on its own origin so it can breathe in place.
    const centroids = regions.map((m) => {
      m.geometry.computeBoundingSphere()
      const c = m.geometry.boundingSphere!.center.clone()
      m.geometry.translate(-c.x, -c.y, -c.z)
      m.position.copy(c)
      return c
    })
    registerRegions(regions.map((m) => m.name), centroids)

    const looks = regions.map((m, i) => {
      const hue = new Color(GROUPS[brain.group[i]].color)
      // Soft-touch vinyl: saturated candy at rest, lighter and glowing when active.
      const rest = hue.clone().lerp(white, 0.3)
      const material = new MeshPhysicalMaterial({
        color: rest.clone(), roughness: 0.45, metalness: 0, clearcoat: 0.7, clearcoatRoughness: 0.3,
        sheen: 0.6, sheenRoughness: 0.5, sheenColor: white, emissive: hue.clone(), emissiveIntensity: 0,
      })
      m.material = material
      m.castShadow = false
      return { material, hue, rest, scale: 1, velocity: 0, last: 0, ghost: 0 }
    })

    // Firing neurons: real neurons at the centre of their synapses, glowing in their region's colour.
    const colors = new Float32Array(data.beadRegions.length * 3)
    data.beadRegions.forEach((r, k) => looks[r].hue.clone().lerp(white, 0.2).toArray(colors, k * 3))
    const beadGeometry = new BufferGeometry()
    beadGeometry.setAttribute('position', new BufferAttribute(data.beadPositions, 3))
    beadGeometry.setAttribute('aColor', new BufferAttribute(colors, 3))
    const state = new BufferAttribute(new Float32Array(data.beadRegions.length), 1).setUsage(DynamicDrawUsage)
    beadGeometry.setAttribute('aState', state)
    const beads = new Points(beadGeometry, new ShaderMaterial({
      vertexShader: glowVertex, fragmentShader: glowFragment, uniforms: { uScale: { value: 0 } },
      transparent: true, depthWrite: false, depthTest: false, blending: AdditiveBlending,
    }))
    beads.frustumCulled = false
    beads.renderOrder = 4

    // Comets race along the strongest real connections between regions, arcing up and out.
    const strongest = data.wires[0][2]
    const curves = data.wires.map(([from, to, weight], k) => {
      const a = centroids[from]
      const b = centroids[to]
      const mid = a.clone().add(b).multiplyScalar(0.5)
      mid.add(new Vector3(0, 0.12 + 0.3 * a.distanceTo(b), 0.2 + (k % 3) * 0.06))
      return { from, weight: Math.sqrt(weight / strongest), curve: new QuadraticBezierCurve3(a, mid, b) }
    })
    const cometGeometry = new BufferGeometry()
    cometGeometry.setAttribute('position', new BufferAttribute(new Float32Array(COMETS * TRAIL * 3), 3))
    cometGeometry.setAttribute('aAlpha', new BufferAttribute(new Float32Array(COMETS * TRAIL), 1))
    const cometPoints = new Points(cometGeometry, new ShaderMaterial({
      vertexShader: cometVertex, fragmentShader: cometFragment,
      uniforms: { uScale: { value: 0 }, uColor: { value: new Color(palette.sun) } },
      transparent: true, depthWrite: false, depthTest: false, blending: AdditiveBlending,
    }))
    cometPoints.frustumCulled = false
    cometPoints.renderOrder = 5
    const comets = Array.from({ length: COMETS }, () => ({ curve: -1, t: 0, speed: 0 }))

    // Verdict burst: sparks thrown out from the lit regions, and a shockwave ring.
    const burstGeometry = new BufferGeometry()
    burstGeometry.setAttribute('position', new BufferAttribute(new Float32Array(BURST * 3), 3))
    burstGeometry.setAttribute('aAlpha', new BufferAttribute(new Float32Array(BURST), 1))
    const burstPoints = new Points(burstGeometry, cometPoints.material)
    burstPoints.frustumCulled = false
    burstPoints.renderOrder = 5
    const burst = Array.from({ length: BURST }, () => ({ p: new Vector3(), v: new Vector3(), life: 0 }))
    const ringMaterial = new ShaderMaterial({
      vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
      fragmentShader: ringFragment,
      uniforms: { uProgress: { value: 1 }, uColor: { value: new Color(palette.sun) } },
      transparent: true, depthWrite: false, blending: AdditiveBlending, side: DoubleSide,
    })
    const ring = new Mesh(new RingGeometry(0.96, 1, 96), ringMaterial)
    ring.visible = false

    return { shells, regions, centroids, looks, beads, beadRegions: data.beadRegions, state, curves, comets,
      cometPoints, burst, burstPoints, ring, ringMaterial, verdictSeen: 0, focusSeen: 0, ringSize: 1,
      glass: 0 }
  }, [scene, data])

  const tmp = useMemo(() => new Vector3(), [])

  useFrame((frame, delta) => {
    const dt = Math.min(delta, 0.05)
    const time = frame.clock.elapsedTime
    frameStep(dt, time)
    const shown = brain.shown

    // Regions breathe on a spring: a jump in activity kicks them outward, then they settle and glow.
    setup.regions.forEach((m, i) => {
      const look = setup.looks[i]
      const a = shown[i]
      const kick = Math.max(0, a - look.last)
      look.last = a
      look.velocity += kick * 3.2 + ((1 + a * 0.06 - look.scale) * 170 - look.velocity * 11) * dt
      look.scale += look.velocity * dt
      m.scale.setScalar(Math.max(0.94, look.scale))
      // Brain tour: everything but the focused region turns to frosted glass, so it shows from any angle;
      // the focused one keeps its candy colour and glows harder.
      const focused = i === brain.focus
      look.material.color.copy(look.rest).lerp(white, focused ? 0 : a * 0.25 + look.ghost * 0.6)
      look.material.emissiveIntensity = a * a * (focused ? 5 : 3)
      easing.damp(look, 'ghost', brain.focus >= 0 && !focused ? 1 : 0, 0.25, dt)
      const glass = look.ghost > 0.01
      if (look.material.transparent !== glass) {
        look.material.transparent = glass
        look.material.depthWrite = !glass
        look.material.needsUpdate = true
      }
      look.material.opacity = 1 - 0.96 * look.ghost
    })
    // On the tour the shell's outline goes: with the regions turned to glass, the inside of its hull would
    // show through as a dark fog.
    easing.damp(setup, 'glass', brain.focus >= 0 ? 1 : 0, 0.3, dt)
    setup.shells.forEach((s) => s.children.forEach((outline) => (outline.visible = setup.glass < 0.3)))

    // Firing neurons: per-neuron state from the simulation, popping in fast and fading slower.
    const s = setup.state.array as Float32Array
    const real = brain.beads
    const focus = brain.focus
    for (let k = 0; k < s.length; k++) {
      // On tour, the focused region's real neurons twinkle and the rest go dark.
      const target = focus >= 0
        ? setup.beadRegions[k] === focus ? 0.25 + 0.75 * ((Math.sin(time * 2.3 + k * 2.399) + 1) / 2) ** 4 : 0
        : real ? real[k] : shown[setup.beadRegions[k]] * ((k * 0.618) % 1)
      s[k] += (target - s[k]) * Math.min(1, dt * (target > s[k] ? 22 : 5))
    }
    setup.state.needsUpdate = true
    const scale = 52 * pixelRatio * (frame.size.height / 900)
    ;(setup.beads.material as ShaderMaterial).uniforms.uScale.value = scale
    ;(setup.cometPoints.material as ShaderMaterial).uniforms.uScale.value = scale * 0.9

    // Comets with glowing tails.
    const { curves, comets } = setup
    const cometsActive = Math.round(COMETS * quality)
    const pos = setup.cometPoints.geometry.attributes.position as BufferAttribute
    const alpha = setup.cometPoints.geometry.attributes.aAlpha as BufferAttribute
    comets.forEach((p, k) => {
      if (p.curve < 0 && k < cometsActive) {
        const c = Math.floor(Math.random() * curves.length)
        if (Math.random() < shown[curves[c].from] ** 2 * curves[c].weight * dt * 16) {
          p.curve = c
          p.t = 0
          p.speed = 0.9 + Math.random() * 0.9
        }
      } else if (p.curve >= 0) {
        p.t += dt * p.speed
        if (p.t > 1 + TRAIL * 0.03) p.curve = -1
      }
      for (let j = 0; j < TRAIL; j++) {
        const idx = k * TRAIL + j
        const t = p.t - j * 0.03
        if (p.curve < 0 || t < 0 || t > 1) {
          alpha.setX(idx, 0)
          continue
        }
        curves[p.curve].curve.getPoint(t, tmp)
        pos.setXYZ(idx, tmp.x, tmp.y, tmp.z)
        alpha.setX(idx, (1 - j / TRAIL) ** 1.5 * Math.sin(Math.PI * t))
      }
    })
    pos.needsUpdate = true
    alpha.needsUpdate = true

    // The verdict moment: a shockwave and a burst of sparks from the regions named in the reading.
    if (brain.verdictAt && brain.verdictAt !== setup.verdictSeen) {
      setup.verdictSeen = brain.verdictAt
      const sources = brain.highlight.length ? brain.highlight : [0]
      setup.burst.forEach((b, k) => {
        b.p.copy(setup.centroids[sources[k % sources.length]])
        b.v.set(Math.random() - 0.5, Math.random() * 0.8 + 0.2, Math.random() - 0.2).normalize().multiplyScalar(1.2 + Math.random() * 1.4)
        b.life = 1
      })
      setup.ring.visible = true
      setup.ring.position.set(0, 0, 0)
      setup.ringSize = 1
      setup.ringMaterial.uniforms.uProgress.value = 0
    }
    // Arriving at a region on the tour: a small shockwave from it.
    if (brain.focus >= 0 && brain.focusAt !== setup.focusSeen) {
      setup.focusSeen = brain.focusAt
      setup.ring.visible = true
      setup.ring.position.copy(setup.centroids[brain.focus])
      setup.ringSize = 0.3
      setup.ringMaterial.uniforms.uProgress.value = 0
    }
    const bpos = setup.burstPoints.geometry.attributes.position as BufferAttribute
    const balpha = setup.burstPoints.geometry.attributes.aAlpha as BufferAttribute
    setup.burst.forEach((b, k) => {
      if (b.life <= 0) {
        balpha.setX(k, 0)
        return
      }
      b.life -= dt * 0.9
      b.v.multiplyScalar(1 - dt * 2.2)
      b.v.y -= dt * 0.6
      b.p.addScaledVector(b.v, dt)
      bpos.setXYZ(k, b.p.x, b.p.y, b.p.z)
      balpha.setX(k, Math.max(0, b.life) * 1.3)
    })
    bpos.needsUpdate = true
    balpha.needsUpdate = true
    if (setup.ring.visible) {
      const u = setup.ringMaterial.uniforms.uProgress
      u.value = Math.min(1, u.value + dt * 0.8)
      const r = (0.3 + u.value * 2.4) * setup.ringSize
      setup.ring.scale.setScalar(r)
      setup.ring.lookAt(frame.camera.position)
      if (u.value >= 1) setup.ring.visible = false
    }

    if (group.current) {
      // Three-quarter view at rest; while thinking, turn to face the camera like it's listening.
      const busy = brain.phase === 'reading' || brain.phase === 'speaking'
      tilt.current.sway += dt * (busy ? 0.15 : 0.3)
      let yaw = busy ? -0.15 + Math.sin(tilt.current.sway) * 0.08 : -0.45 + Math.sin(tilt.current.sway) * 0.3
      if (brain.focus >= 0) {
        // On tour, turn the focused region towards the camera (regions on the midline need no turn).
        const c = setup.centroids[brain.focus]
        yaw = Math.hypot(c.x, c.z) < 0.12 ? -0.3 : Math.max(-1.3, Math.min(1.3, Math.atan2(-c.x, c.z)))
      }
      easing.damp(tilt.current, 'yaw', yaw, brain.focus >= 0 ? 0.45 : 0.6, dt)
      group.current.rotation.y = tilt.current.yaw
      group.current.position.y = Math.sin(time * 1.1) * 0.025
      if (brain.focus >= 0) {
        group.current.updateMatrixWorld()
        brain.focusPoint.copy(setup.centroids[brain.focus]).applyMatrix4(group.current.matrixWorld)
      }
    }
  })

  return (
    <group ref={group}>
      {setup.regions.map((m) => <primitive key={m.uuid} object={m} />)}
      <primitive object={setup.beads} />
      {setup.shells.map((s) => (
        <primitive key={s.uuid} object={s}>
          <Outlines thickness={0.01} color={palette.grape} transparent opacity={0.85} />
        </primitive>
      ))}
      <primitive object={setup.cometPoints} />
      <primitive object={setup.burstPoints} />
      <primitive object={setup.ring} />
      {focus >= 0 && setup.centroids[focus] && (
        // A name tag pinned to the region on the tour, so you know which blob it is.
        <Html position={setup.centroids[focus]} zIndexRange={[2, 0]} style={{ pointerEvents: 'none' }}>
          <div className="pin" key={focus} style={{ '--tint': GROUPS[brain.group[focus]].color } as CSSProperties}>
            {plainName(brain.names[focus])}
          </div>
        </Html>
      )}
    </group>
  )
}

useGLTF.preload('/brain/brain.glb')
