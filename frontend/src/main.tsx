import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import './tailwind.css'
import App from './App.tsx'
import { AuthProvider } from './context/AuthContext.tsx'
import { applyTheme, preferredTheme } from './lib/theme'

import { EmployerProvider } from './context/EmployerContext.tsx'

// Initialize the existing theme before the first paint so public pages (including
// the landing navbar) receive the correct theme-aware branding as well.
applyTheme(preferredTheme())

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <EmployerProvider>
          <App />
        </EmployerProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
)
