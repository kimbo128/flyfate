import { Canvas } from '@react-three/fiber'
import { Suspense, useEffect } from 'react'
import { brain, highlight } from './activity'
import { Brain } from './Brain'
import { Fly } from './Fly'

// `?snapshot`: Melanie and her brain alone on a transparent background, a few regions lit, fixed camera.
// Used once to render the art for the share cards (inference/assets/card-hero.png); not part of the app.

const LIT = ['gL(R)', 'gL(L)', 'CA(R)', 'CA(L)', 'EB', 'FB', 'AL(R)', 'AL(L)', 'LH(R)', 'LH(L)']

function Pose() {
  useEffect(() => {
    brain.phase = 'verdict'
    highlight(LIT.map((n) => brain.names.indexOf(n)).filter((i) => i >= 0))
    document.body.dataset.snapshot = 'ready'
  }, [])
  return null
}

export function Snapshot() {
  return (
    <Canvas
      className="scene"
      dpr={2}
      camera={{ fov: 30, position: [-0.25, 0.55, 4.6], near: 0.05, far: 50 }}
      onCreated={({ camera }) => camera.lookAt(-0.25, 0.05, 0)}
      gl={{ antialias: true, alpha: true, preserveDrawingBuffer: true }}
    >
      <ambientLight intensity={0.75} />
      <directionalLight position={[-2.5, 4, 4]} intensity={1.7} />
      <Suspense fallback={null}>
        <Brain pixelRatio={2} quality={1} />
        <Fly talking={0} />
        <Pose />
      </Suspense>
    </Canvas>
  )
}
