/**
 * main.jsx — App entry point and router.
 *
 * ProtectedRoute reads isAuthenticated() which now checks sessionStorage.
 * This is resilient to Vite HMR module resets.
 *
 * NOTE: React.StrictMode is intentionally removed — it double-invokes
 * every useEffect in development which breaks the login wizard step-machine.
 */
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import './index.css'

import Enrollment from './pages/Enrollment'
import Login      from './pages/Login'
import Interview  from './pages/Interview'
import Report     from './pages/Report'
import { isAuthenticated } from './utils/api'

/** Guard: redirect to /login if no token in sessionStorage. */
function ProtectedRoute({ children }) {
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace />
  }
  return children
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <BrowserRouter>
    <Routes>
      {/* Public */}
      <Route path="/"       element={<Navigate to="/login" replace />} />
      <Route path="/enroll" element={<Enrollment />} />
      <Route path="/login"  element={<Login />} />

      {/* Protected — requires sessionStorage token */}
      <Route path="/interview" element={
        <ProtectedRoute><Interview /></ProtectedRoute>
      } />
      <Route path="/report/:sessionId" element={
        <ProtectedRoute><Report /></ProtectedRoute>
      } />

      {/* Fallback */}
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  </BrowserRouter>
)
