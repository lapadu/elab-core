import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { DispatcherProvider } from './contexts/DispatcherContext.jsx'
import { applySystemColorsToRoot } from './utils/Shared.jsx'

applySystemColorsToRoot()

createRoot(document.getElementById('root')).render(
 <StrictMode>
    <DispatcherProvider>
      <App />
    </DispatcherProvider>
 </StrictMode>,
)
