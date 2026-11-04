import { Outlines } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { easing } from 'maath'
import { useMemo, useRef } from 'react'
import {
  BufferGeometry, CatmullRomCurve3, DoubleSide, Group, MathUtils, Shape, ShapeGeometry, Vector3,
} from 'three'
import { brain } from './activity'
import { palette } from '../palette'

// Melanie, a Drosophila melanogaster as a vinyl toy: tan body, striped abdomen, big glossy red eyes, and
// iridescent wings you can actually see. She hovers in a lazy figure-eight, banks through loops around her
// brain while thinking, bobs on every word, and does a happy flip when the verdict lands.

const BODY = '#e0a95f'
const STRIPE = '#5b3a1f'
const EYE = palette.flyRed

// Where Melanie hangs out per phase, relative to the brain.
const PERCH = new Vector3(-1.2, 0.62, 0.7)
const SPEAKING = new Vector3(-1.1, 0.78, 0.8)
// Portrait screens have no room beside the brain: she hovers above it.
const PERCH_NARROW = new Vector3(-0.5, 0.8, 0.6)
const SPEAKING_NARROW = new Vector3(-0.35, 0.74, 0.7)
// On the brain tour: beside the focused region, a little towards the camera.
const TOUR = new Vector3(0.5, 0.3, 0.3)
const TOUR_NARROW = new Vector3(0.38, 0.42, 0.3)

// A loop around the brain for thinking: wide, tilted, passing in front of it.
const LOOP = new CatmullRomCurve3([
  new Vector3(-1.35, 0.4, 0.55), new Vector3(-0.2, 0.85, 0.85), new Vector3(1.25, 0.5, 0.45),
  new Vector3(1.1, 0.25, -0.8), new Vector3(-0.3, 0.6, -1.05), new Vector3(-1.4, 0.3, -0.25),
], true, 'catmullrom', 0.5)

// Teardrop wing outline with a few veins, as real Drosophila wings have.
function wingShape() {
  const s = new Shape()
  s.moveTo(0, 0)
  s.bezierCurveTo(0.08, 0.07, 0.3, 0.1, 0.42, 0.05)
  s.bezierCurveTo(0.48, 0.02, 0.48, -0.05, 0.4, -0.07)
  s.bezierCurveTo(0.26, -0.09, 0.08, -0.06, 0, 0)
  return s
}

const VEINS = [
  [[0.02, 0.0], [0.42, 0.03]],
  [[0.03, -0.01], [0.38, -0.05]],
  [[0.12, 0.02], [0.3, -0.06]],
].map((line) => new BufferGeometry().setFromPoints(line.map(([x, y]) => new Vector3(x, y, 0.001))))

function Wing({ side, ghost = 0 }: { side: 1 | -1; ghost?: number }) {
  const geometry = useMemo(() => new ShapeGeometry(wingShape(), 24), [])
  const opacity = ghost ? 0.16 / ghost : 0.62
  return (
    <group scale={[side, 1, 1]}>
      <mesh geometry={geometry} renderOrder={6}>
        <meshPhysicalMaterial
          color="#bfe1ff" transparent opacity={opacity} roughness={0.3} metalness={0} side={DoubleSide}
          iridescence={1} iridescenceIOR={1.35} iridescenceThicknessRange={[180, 560]} depthWrite={false}
          envMapIntensity={0.55}
        />
        {!ghost && <Outlines thickness={0.006} color={palette.grape} transparent opacity={0.9} />}
      </mesh>
      {!ghost && VEINS.map((v, i) => (
        <lineSegments key={i} geometry={v}>
          <lineBasicMaterial color={palette.grape} transparent opacity={0.45} />
        </lineSegments>
      ))}
    </group>
  )
}

function Vinyl({ color, clearcoat = 0.8 }: { color: string; clearcoat?: number }) {
  return <meshPhysicalMaterial color={color} roughness={0.38} clearcoat={clearcoat} clearcoatRoughness={0.18} sheen={0.4} />
}

function Eye({ side }: { side: 1 | -1 }) {
  return (
    <group position={[side * 0.1, 0.03, 0.06]}>
      <mesh scale={[0.95, 1.1, 0.95]}>
        <sphereGeometry args={[0.108, 32, 24]} />
        <meshPhysicalMaterial color={EYE} roughness={0.22} clearcoat={1} clearcoatRoughness={0.05} />
        <Outlines thickness={0.008} color={palette.grape} />
      </mesh>
      {/* Not anatomically correct, but she is a mascot. */}
      <mesh position={[side * 0.012, 0.0, 0.088]}>
        <sphereGeometry args={[0.046, 20, 16]} />
        <meshPhysicalMaterial color={palette.grape} roughness={0.1} clearcoat={1} />
      </mesh>
      <mesh position={[-0.014, 0.024, 0.124]}>
        <sphereGeometry args={[0.017, 12, 10]} />
        <meshBasicMaterial color="#ffffff" toneMapped={false} />
      </mesh>
    </group>
  )
}

// Short, splayed toy legs that dangle: an upper segment out to the side, a foot bent back in.
function Leg({ side, z }: { side: 1 | -1; z: number }) {
  return (
    <group position={[side * 0.11, -0.07, z]} rotation={[z * 2.5, 0, side * 1.05]}>
      <mesh position={[0, -0.045, 0]}>
        <capsuleGeometry args={[0.012, 0.07, 4, 8]} />
        <Vinyl color={STRIPE} clearcoat={0.3} />
      </mesh>
      <mesh position={[side * 0.025, -0.1, 0]} rotation={[0, 0, side * -1.2]}>
        <capsuleGeometry args={[0.01, 0.05, 4, 8]} />
        <Vinyl color={STRIPE} clearcoat={0.3} />
      </mesh>
    </group>
  )
}

export function Fly({ talking }: { talking: number }) {
  const root = useRef<Group>(null)
  const body = useRef<Group>(null)
  const wings = useRef<(Group | null)[]>([])
  const state = useMemo(() => ({
    loop: 0, pos: PERCH.clone(), goal: new Vector3(), heading: new Vector3(1, 0, 0), roll: 0, yaw: 0.45,
    lastTalk: 0, hop: 0, flip: 0, verdictSeen: 0, size: 1,
  }), [])
  const ahead = useMemo(() => new Vector3(), [])

  useFrame((frame, delta) => {
    const dt = Math.min(delta, 0.05)
    const t = frame.clock.elapsedTime
    const thinking = brain.phase === 'reading'
    const narrow = frame.size.width < frame.size.height

    if (thinking) {
      // Loop around her brain, banking into the turns.
      state.loop = (state.loop + dt * 0.16) % 1
      LOOP.getPointAt(state.loop, state.goal)
      LOOP.getPointAt((state.loop + 0.02) % 1, ahead)
    } else if (brain.focus >= 0) {
      // Brain tour: she guides, hovering just beside the region the camera flew to.
      state.goal.copy(brain.focusPoint).add(narrow ? TOUR_NARROW : TOUR)
      state.goal.y += Math.sin(t * 1.8) * 0.03
    } else {
      const base = brain.phase === 'idle' ? (narrow ? PERCH_NARROW : PERCH) : (narrow ? SPEAKING_NARROW : SPEAKING)
      // A lazy figure-eight hover.
      state.goal.set(base.x + Math.sin(t * 0.9) * 0.07, base.y + Math.sin(t * 1.8) * 0.045, base.z + Math.cos(t * 0.9) * 0.03)
    }
    easing.damp3(state.pos, state.goal, thinking ? 0.12 : 0.45, dt)
    if (!root.current || !body.current) return
    root.current.position.copy(state.pos)
    // The tour camera is close: she shrinks a little so she doesn't hide the brain.
    easing.damp(state, 'size', brain.focus >= 0 ? 0.6 : 1, 0.4, dt)
    root.current.scale.setScalar(state.size)

    // Heading and bank: face where she flies while looping, the camera otherwise.
    let targetYaw = brain.focus >= 0 ? -0.5 : 0.45  // on tour she turns towards the region on her left
    let targetRoll = 0
    if (thinking) {
      ahead.sub(state.goal)
      targetYaw = Math.atan2(ahead.x, ahead.z)
      const turn = MathUtils.euclideanModulo(targetYaw - state.yaw + Math.PI, Math.PI * 2) - Math.PI
      targetRoll = MathUtils.clamp(-turn * 8, -0.7, 0.7)
    }
    const dyaw = MathUtils.euclideanModulo(targetYaw - state.yaw + Math.PI, Math.PI * 2) - Math.PI
    state.yaw += dyaw * (1 - Math.exp(-dt * 6))
    state.roll += (targetRoll - state.roll) * (1 - Math.exp(-dt * 5))

    // Verdict: one happy backflip.
    if (brain.verdictAt && brain.verdictAt !== state.verdictSeen) {
      state.verdictSeen = brain.verdictAt
      state.flip = 1
    }
    state.flip = Math.max(0, state.flip - dt * 1.6)
    const flipAngle = (1 - easeOutBack(1 - state.flip)) * Math.PI * 2
    root.current.rotation.set(-flipAngle, state.yaw, state.roll, 'YXZ')

    // A little hop on every spoken word.
    if (talking !== state.lastTalk) {
      state.lastTalk = talking
      state.hop = 1
    }
    state.hop = Math.max(0, state.hop - dt * 5)
    const squash = Math.sin(state.hop * Math.PI) * 0.13
    body.current.scale.set(1 + squash, 1 - squash, 1 + squash)
    body.current.position.y = Math.sin(state.hop * Math.PI) * 0.05

    // Wings: fast beats while flying, a slower hover beat at rest; ghost copies trail the beat as motion blur.
    const rate = thinking ? 62 : 34
    const amp = thinking ? 0.75 : 0.5
    wings.current.forEach((w, i) => {
      if (!w) return
      const side = i % 2 ? -1 : 1
      const lag = Math.floor(i / 2) * 0.35
      w.rotation.set(-0.35, side * 0.55, side * (0.35 + Math.sin(t * rate - lag) * amp))
    })
  })

  return (
    <group ref={root} scale={0.78}>
      <group ref={body}>
        {/* head */}
        <group position={[0, 0.14, 0.2]}>
          <mesh>
            <sphereGeometry args={[0.13, 32, 24]} />
            <Vinyl color={BODY} />
            <Outlines thickness={0.01} color={palette.grape} />
          </mesh>
          <Eye side={1} />
          <Eye side={-1} />
          {[1, -1].map((s) => (
            <group key={s} position={[s * 0.035, 0.12, 0.1]} rotation={[0.5, 0, -s * 0.4]}>
              <mesh>
                <capsuleGeometry args={[0.012, 0.06, 4, 8]} />
                <Vinyl color={STRIPE} clearcoat={0.3} />
              </mesh>
              <mesh position={[0, 0.05, 0]}>
                <sphereGeometry args={[0.02, 12, 10]} />
                <Vinyl color={STRIPE} clearcoat={0.3} />
              </mesh>
            </group>
          ))}
        </group>
        {/* thorax */}
        <mesh position={[0, 0.05, 0]} scale={[1, 0.9, 1.1]}>
          <sphereGeometry args={[0.17, 32, 24]} />
          <Vinyl color={BODY} />
          <Outlines thickness={0.01} color={palette.grape} />
        </mesh>
        {/* abdomen with stripes */}
        <group position={[0, -0.02, -0.26]} rotation={[0.35, 0, 0]}>
          <mesh scale={[0.85, 0.8, 1.2]}>
            <sphereGeometry args={[0.17, 32, 24]} />
            <Vinyl color={BODY} />
            <Outlines thickness={0.01} color={palette.grape} />
          </mesh>
          {[-0.05, 0.04, 0.12].map((z) => (
            <mesh key={z} position={[0, 0, -z]} rotation={[Math.PI / 2, 0, 0]} scale={[0.85, 1, 0.8]}>
              <torusGeometry args={[0.152 - Math.abs(z) * 0.25, 0.022, 10, 36]} />
              <Vinyl color={STRIPE} clearcoat={0.4} />
            </mesh>
          ))}
        </group>
        {[-1, 1].flatMap((s) => [0.08, 0, -0.08].map((z) => <Leg key={`${s}${z}`} side={s as 1 | -1} z={z} />))}
        {/* wings at the top of the thorax: a sharp pair and two fading ghost pairs */}
        <group position={[0, 0.17, -0.05]}>
          {[0, 1, 2].flatMap((g) => [1, -1].map((s) => (
            <group key={`${g}${s}`} ref={(el) => { wings.current[g * 2 + (s === 1 ? 0 : 1)] = el }}>
              <Wing side={s as 1 | -1} ghost={g} />
            </group>
          )))}
        </group>
      </group>
    </group>
  )
}

function easeOutBack(x: number) {
  const c1 = 1.70158
  const c3 = c1 + 1
  return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2
}
