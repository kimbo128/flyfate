// The sky behind Melanie, chosen by the visitor and remembered on this device. One shared value for the page
// (CSS custom properties), the 3D scene's background (Scene.tsx) and the video card (video.ts).
import { useSyncExternalStore } from 'react'

export type Sky = { id: string; name: string; top: string; bottom: string; dark?: boolean }

export const SKIES: Sky[] = [
  { id: 'day', name: 'Daydream', top: '#a8dbff', bottom: '#ffe3c7' },
  { id: 'golden', name: 'Golden hour', top: '#ff9e8a', bottom: '#ffdc8f' },
  { id: 'bubblegum', name: 'Bubblegum', top: '#ffc2e2', bottom: '#cdbcff' },
  { id: 'meadow', name: 'Meadow', top: '#b5efe0', bottom: '#fff1a8' },
  { id: 'night', name: 'Night flight', top: '#1f1a4d', bottom: '#5b3f8f', dark: true },
]
const KEY = 'flyfate-sky'

let current = (() => {
  try {
    return SKIES.find((s) => s.id === localStorage.getItem(KEY)) ?? SKIES[0]
  } catch {
    return SKIES[0]
  }
})()
const listeners = new Set<() => void>()

function apply(sky: Sky) {
  const root = document.documentElement.style
  root.setProperty('--sky-top', sky.top)
  root.setProperty('--sky-bottom', sky.bottom)
  document.documentElement.dataset.sky = sky.id
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', sky.top)
}
apply(current)

export const getSky = () => current

export function setSky(id: string) {
  const next = SKIES.find((s) => s.id === id)
  if (!next || next === current) return
  current = next
  try {
    localStorage.setItem(KEY, id)
  } catch {
    /* storage blocked: the choice lasts for this visit */
  }
  apply(next)
  listeners.forEach((l) => l())
}

export function useSky() {
  return useSyncExternalStore((l) => {
    listeners.add(l)
    return () => listeners.delete(l)
  }, getSky)
}
