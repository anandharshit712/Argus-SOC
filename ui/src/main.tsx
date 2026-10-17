import '@fontsource/rajdhani/500.css'
import '@fontsource/rajdhani/700.css'
import '@fontsource/share-tech-mono'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
