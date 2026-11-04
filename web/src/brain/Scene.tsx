import { Environment, Lightformer, PerformanceMonitor } from '@react-three/drei'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { Bloom, EffectComposer, SMAA, Vignette } from '@react-three/postprocessing'
import { easing } from 'maath'
import { Suspense, useEffect, useMemo, useState } from 'react'
import { AgXToneMapping, CanvasTexture, PerspectiveCamera, SRGBColorSpace, Vector3 } from 'three'
import { brain, type Phase } from './activity'
import { Brain } from './Brain'
import { Fly } from './Fly'
import { palette } from '../palette'

// Camera distance per phase. Reading pushes in and slowly orbits while Melanie loops, the verdict pulls back.
const DISTANCE: Record<Phase, number> = { idle: 5.2, reading: 4.3, speaking: 4.7, verdict: 5.0 }
// On the brain tour the camera flies in close to the focused region.
const TOUR_DISTANCE = 3.5
const FOV = 30

function Rig({ reducedMotion }: { reducedMotion: boolean }) {
  const { camera, size, pointer } = useThree()
  const goal = useMemo(() => new Vector3(), [])
  const look = useMemo(() => new Vector3(), [])
  const origin = useMemo(() => new Vector3(), [])
  const lens = useMemo(() => ({ fov: FOV, seen: 0 }), [])
  const aim = useMemo(() => new Vector3(), [])

  useFrame((frame, delta) => {
    const t = frame.clock.elapsedTime
    const aspect = size.width / size.height
    // Wide screens: the dialog sits in a left column (styles.css), the brain to the right of it.
    const wide = aspect > 1.2 && size.width >= 1024
    // Narrow screens back off until the brain (2 units wide) nearly fills the width; Melanie moves above it.
    const touring = brain.focus >= 0
    const d = (touring ? TOUR_DISTANCE : DISTANCE[brain.phase]) * Math.max(1, 0.78 / aspect)
    const halfHeight = Math.tan((FOV / 2) * (Math.PI / 180)) * d
    // What to frame: the whole brain, or on the tour the focused region.
    const centre = touring ? brain.focusPoint : origin
    // Wide: brain centred in the right part. Otherwise keep the lower part of the screen free for the dialog
    // (taller on the tour, with the region's explanation in it).
    if (wide) look.set(centre.x - halfHeight * aspect * 0.32, centre.y - 0.05, centre.z)
    else look.set(centre.x - 0.05, centre.y - (touring ? 0.42 : 0.3) * halfHeight + 0.15, centre.z)
    // While thinking, drift around the brain like a slow dolly; otherwise follow the pointer a little.
    const orbit = brain.phase === 'reading' ? Math.sin(t * 0.35) * 0.45 : pointer.x * 0.08
    goal.set(look.x + Math.sin(orbit) * d * 0.35, look.y + 0.55 * (d / 5) + pointer.y * 0.12, look.z + Math.cos(orbit) * d)
    // A small lens punch when the verdict lands.
    if (brain.verdictAt !== lens.seen) {
      lens.seen = brain.verdictAt
      lens.fov = FOV - 3
    }
    if (reducedMotion) {
      camera.position.copy(goal)
    } else {
      easing.damp3(camera.position, goal, brain.phase === 'reading' ? 0.9 : touring ? 0.45 : 0.6, delta)
      easing.damp(lens, 'fov', FOV, 0.5, delta)
    }
    const cam = camera as PerspectiveCamera
    if (Math.abs(cam.fov - lens.fov) > 0.001) {
      cam.fov = lens.fov
      cam.updateProjectionMatrix()
    }
    // Look-at eases too, so flying between regions is a glide rather than a snap.
    if (reducedMotion) aim.copy(look)
    else easing.damp3(aim, look, touring ? 0.4 : 0.25, delta)
    camera.lookAt(aim)
  })
  return null
}

// The sky from the page, painted into the scene so post-processing sees an opaque background.
function useSky() {
  return useMemo(() => {
    const c = document.createElement('canvas')
    c.width = 4
    c.height = 512
    const g = c.getContext('2d')!
    const grad = g.createLinearGradient(0, 0, 0, 512)
    grad.addColorStop(0, palette.skyTop)
    grad.addColorStop(1, palette.skyBottom)
    g.fillStyle = grad
    g.fillRect(0, 0, 4, 512)
    const tex = new CanvasTexture(c)
    tex.colorSpace = SRGBColorSpace
    return tex
  }, [])
}

// A soft blob shadow under the brain. (drei's ContactShadows renders the painted sky background into its
// shadow map and greys out the whole floor.)
function GroundShadow() {
  const texture = useMemo(() => {
    const c = document.createElement('canvas')
    c.width = c.height = 128
    const g = c.getContext('2d')!
    const grad = g.createRadialGradient(64, 64, 0, 64, 64, 64)
    grad.addColorStop(0, 'rgba(46,36,87,0.42)')
    grad.addColorStop(0.55, 'rgba(46,36,87,0.16)')
    grad.addColorStop(1, 'rgba(46,36,87,0)')
    g.fillStyle = grad
    g.fillRect(0, 0, 128, 128)
    return new CanvasTexture(c)
  }, [])
  return (
    <mesh position={[0, -0.92, 0]} rotation-x={-Math.PI / 2} scale={[3.4, 1.9, 1]} renderOrder={-1}>
      <planeGeometry />
      <meshBasicMaterial map={texture} transparent depthWrite={false} toneMapped={false} />
    </mesh>
  )
}

// Mounts only once everything inside the Suspense boundary has loaded.
function Ready({ onReady }: { onReady: () => void }) {
  useEffect(onReady, [onReady])
  return null
}

// A studio for vinyl toys, built from light panels (no HDR download): warm key, cool fill, pink rim.
function Studio() {
  return (
    <Environment resolution={256} frames={1}>
      <Lightformer form="rect" intensity={3.2} color="#fff4e6" position={[-3, 4, 4]} scale={[6, 4, 1]} />
      <Lightformer form="rect" intensity={1.6} color="#d6ecff" position={[4, 1, 3]} scale={[4, 5, 1]} />
      <Lightformer form="ring" intensity={2.2} color="#ffd3ec" position={[0, 2, -5]} scale={4} />
      <Lightformer form="rect" intensity={1.2} color={palette.skyBottom} position={[0, -4, 0]} rotation-x={Math.PI / 2} scale={[10, 10, 1]} />
    </Environment>
  )
}

type SceneProps = { reducedMotion: boolean; talking: number; focus: number; onReady: () => void }

export function Scene({ reducedMotion, talking, focus, onReady }: SceneProps) {
  // Full effects by default; PerformanceMonitor steps down on devices that can't keep up.
  const [quality, setQuality] = useState(1)
  const sky = useSky()
  const pixelRatio = Math.min(window.devicePixelRatio, quality < 1 ? 1.25 : 2)
  return (
    <Canvas
      className="scene"
      dpr={pixelRatio}
      camera={{ fov: FOV, position: [0, 0.6, 6], near: 0.05, far: 50 }}
      gl={{ antialias: false, powerPreference: 'high-performance', toneMapping: AgXToneMapping, toneMappingExposure: 1.15 }}
      scene={{ background: sky }}
      aria-hidden
    >
      <PerformanceMonitor onDecline={() => setQuality(0.5)} onIncline={() => setQuality(1)} flipflops={3} />
      <ambientLight intensity={0.35} />
      <directionalLight position={[-2.5, 4, 4]} intensity={1.4} />
      <Studio />
      <Suspense fallback={null}>
        <Brain pixelRatio={pixelRatio} quality={quality} focus={focus} />
        <Fly talking={talking} />
        <Ready onReady={onReady} />
      </Suspense>
      <GroundShadow />
      <Rig reducedMotion={reducedMotion} />
      {/* No ambient-occlusion pass: the N8AO bundled with @react-three/postprocessing breaks on three r187
          (render targets without mipmaps). Depth comes from the studio light and the contact shadow. */}
      <EffectComposer multisampling={0} enableNormalPass={false}>
        <Bloom mipmapBlur luminanceThreshold={0.92} luminanceSmoothing={0.15} intensity={1.15} levels={6} />
        <SMAA />
        <Vignette offset={0.4} darkness={0.32} />
      </EffectComposer>
    </Canvas>
  )
}
