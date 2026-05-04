/**
 * api.js — Axios instance with sessionStorage-backed auth store.
 *
 * Why sessionStorage instead of pure in-memory?
 * Vite's Hot Module Replacement resets module-level variables on every
 * file save during development, which clears the in-memory token and
 * makes ProtectedRoute bounce the user back to /login immediately after
 * a successful login navigation.
 *
 * sessionStorage:
 *  - Survives React re-renders and Vite HMR module resets
 *  - Cleared automatically when the browser tab closes (unlike localStorage)
 *  - Not accessible across tabs (more secure than localStorage for tokens)
 */
import axios from 'axios'

const KEYS = {
  token:       'miic_token',
  sessionId:   'miic_session_id',
  candidateId: 'miic_candidate_id',
}

// ── Auth store (backed by sessionStorage) ────────────────────────────────────

export function setAuth({ token, sessionId, candidateId }) {
  if (token)       sessionStorage.setItem(KEYS.token,       token)
  if (sessionId)   sessionStorage.setItem(KEYS.sessionId,   sessionId)
  if (candidateId) sessionStorage.setItem(KEYS.candidateId, candidateId)
}

export function getAuth() {
  return {
    token:       sessionStorage.getItem(KEYS.token),
    sessionId:   sessionStorage.getItem(KEYS.sessionId),
    candidateId: sessionStorage.getItem(KEYS.candidateId),
  }
}

export function clearAuth() {
  Object.values(KEYS).forEach(k => sessionStorage.removeItem(k))
}

export function isAuthenticated() {
  return Boolean(sessionStorage.getItem(KEYS.token))
}

// ── Axios instance ────────────────────────────────────────────────────────────
const api = axios.create({
  baseURL: 'http://localhost:8000',
  timeout: 120000,   // 2 min — ML models can be slow on first run
})

// Attach Bearer token on every request
api.interceptors.request.use((config) => {
  const token = sessionStorage.getItem(KEYS.token)
  if (token) config.headers['Authorization'] = `Bearer ${token}`
  return config
})

// On 401: clear auth and redirect to login
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      clearAuth()
      window.location.replace('/login')
    }
    return Promise.reject(err)
  }
)

export default api
