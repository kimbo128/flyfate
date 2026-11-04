import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import App from './App.tsx'
import { Snapshot } from './brain/Snapshot.tsx'

const snapshot = new URLSearchParams(location.search).has('snapshot')
if (snapshot) document.documentElement.dataset.snapshot = ''

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {snapshot ? <Snapshot /> : <App />}
  </StrictMode>,
)
