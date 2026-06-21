/**
 * SignupLogin.jsx — Friction-free email/password auth (Phase 1)
 *
 * Tabs: "Create Account" | "Login"
 * After signup → OTP verification screen → auto-login → /dashboard
 * Biometric login link: "Have a Candidate ID? Use biometric login →"
 */
import React, { useState, useRef, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import api, { setAuth } from '../utils/api'

// ─── Tiny toast helper ──────────────────────────────────────────────────────
function Toast({ msg, type = 'danger', onClose }) {
  if (!msg) return null
  const colors = {
    danger:  'var(--clr-danger)',
    success: 'var(--clr-success)',
    info:    'var(--clr-primary)',
  }
  return (
    <div style={{
      position: 'fixed', top: 20, right: 20, zIndex: 9999,
      background: 'var(--clr-surface-2)', border: `1px solid ${colors[type]}`,
      borderRadius: 'var(--r-md)', padding: '12px 18px', maxWidth: 360,
      boxShadow: '0 4px 24px rgba(0,0,0,0.5)',
      animation: 'slideDown 0.25s ease',
      display: 'flex', alignItems: 'flex-start', gap: 10,
    }}>
      <span style={{ fontSize: '1.1rem' }}>
        {type === 'danger' ? '⚠️' : type === 'success' ? '✅' : 'ℹ️'}
      </span>
      <span style={{ flex: 1, fontSize: '0.9rem', color: 'var(--clr-text)', lineHeight: 1.5 }}>{msg}</span>
      <button onClick={onClose} style={{
        background: 'none', border: 'none', color: 'var(--clr-text-muted)',
        cursor: 'pointer', fontSize: '1rem', padding: 0, lineHeight: 1,
      }}>✕</button>
    </div>
  )
}

// ─── Input field ───────────────────────────────────────────────────────────
function Field({ label, id, type = 'text', value, onChange, placeholder, autoFocus }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <label htmlFor={id} style={{ display: 'block', fontSize: '0.82rem', fontWeight: 600, marginBottom: 6, color: 'var(--clr-text-muted)' }}>
        {label}
      </label>
      <input
        id={id}
        className="input"
        type={type}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        autoFocus={autoFocus}
        style={{ width: '100%' }}
      />
    </div>
  )
}

// ─── OTP digit input ───────────────────────────────────────────────────────
function OtpInput({ value, onChange }) {
  return (
    <input
      className="input"
      type="text"
      inputMode="numeric"
      maxLength={6}
      value={value}
      onChange={e => onChange(e.target.value.replace(/\D/g, ''))}
      placeholder="000000"
      style={{
        fontSize: '2rem', letterSpacing: '0.4em', textAlign: 'center',
        maxWidth: 220, margin: '0 auto 20px', display: 'block',
        fontFamily: 'var(--font-mono)',
      }}
      autoFocus
    />
  )
}

export default function SignupLogin() {
  const navigate = useNavigate()
  const [tab,         setTab]         = useState('login')   // 'login' | 'signup'
  const [screen,      setScreen]      = useState('form')    // 'form' | 'otp'
  const [toast,       setToast]       = useState(null)
  const [loading,     setLoading]     = useState(false)

  // Login fields
  const [loginEmail,    setLoginEmail]    = useState('')
  const [loginPassword, setLoginPassword] = useState('')

  // Signup fields
  const [signupName,     setSignupName]     = useState('')
  const [signupEmail,    setSignupEmail]    = useState('')
  const [signupPassword, setSignupPassword] = useState('')

  // OTP fields
  const [otpCode,   setOtpCode]   = useState('')
  const [otpEmail,  setOtpEmail]  = useState('')  // email to verify
  const [resendCd,  setResendCd]  = useState(0)   // cooldown seconds
  const resendTimer = useRef(null)

  const showToast = (msg, type = 'danger') => setToast({ msg, type })
  const clearToast = () => setToast(null)

  // ── Resend cooldown countdown ─────────────────────────────────────────────
  const startCooldown = () => {
    setResendCd(60)
    clearInterval(resendTimer.current)
    resendTimer.current = setInterval(() => {
      setResendCd(c => {
        if (c <= 1) { clearInterval(resendTimer.current); return 0 }
        return c - 1
      })
    }, 1000)
  }
  useEffect(() => () => clearInterval(resendTimer.current), [])

  // ── Login submit ─────────────────────────────────────────────────────────
  const handleLogin = async (e) => {
    e.preventDefault()
    clearToast()
    if (!loginEmail || !loginPassword) { showToast('Please fill in all fields.'); return }
    setLoading(true)
    try {
      const { data } = await api.post('/auth/password-login', {
        email: loginEmail.trim().toLowerCase(),
        password: loginPassword,
      })
      setAuth({
        token:       data.access_token,
        sessionId:   data.session_id,
        candidateId: data.candidate_id,
      })
      navigate('/dashboard', { replace: true })
    } catch (err) {
      const detail = err.response?.data?.detail
      if (err.response?.status === 403) {
        // Email not verified — bounce to OTP screen
        setOtpEmail(loginEmail.trim().toLowerCase())
        setScreen('otp')
        startCooldown()
        showToast('Your email is not verified yet. Enter the code we sent you.', 'info')
      } else {
        showToast(typeof detail === 'string' ? detail : 'Login failed. Check your credentials.')
      }
    } finally {
      setLoading(false)
    }
  }

  // ── Signup submit ────────────────────────────────────────────────────────
  const handleSignup = async (e) => {
    e.preventDefault()
    clearToast()
    if (!signupName || !signupEmail || !signupPassword) { showToast('Please fill in all fields.'); return }
    if (signupPassword.length < 6) { showToast('Password must be at least 6 characters.'); return }
    setLoading(true)
    try {
      await api.post('/auth/signup', {
        name:     signupName.trim(),
        email:    signupEmail.trim().toLowerCase(),
        password: signupPassword,
      })
      setOtpEmail(signupEmail.trim().toLowerCase())
      setScreen('otp')
      startCooldown()
      showToast('Account created! Check your email for a 6-digit code.', 'success')
    } catch (err) {
      const detail = err.response?.data?.detail
      showToast(typeof detail === 'string' ? detail : 'Signup failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  // ── OTP verify ───────────────────────────────────────────────────────────
  const handleVerifyOtp = async (e) => {
    e?.preventDefault()
    clearToast()
    if (otpCode.length !== 6) { showToast('Enter the 6-digit code.'); return }
    setLoading(true)
    try {
      await api.post('/auth/verify-email', { email: otpEmail, otp_code: otpCode })
      showToast('Email verified! Signing you in…', 'success')
      // Auto-login with the password the user just set
      const pw = signupPassword || loginPassword
      if (pw) {
        const { data } = await api.post('/auth/password-login', {
          email:    otpEmail,
          password: pw,
        })
        setAuth({
          token:       data.access_token,
          sessionId:   data.session_id,
          candidateId: data.candidate_id,
        })
        navigate('/dashboard', { replace: true })
      } else {
        // Can't auto-login without password — send back to login
        setScreen('form')
        setTab('login')
        setLoginEmail(otpEmail)
        showToast('Email verified! Please log in.', 'success')
      }
    } catch (err) {
      const detail = err.response?.data?.detail
      showToast(typeof detail === 'string' ? detail : 'Verification failed. Try again.')
    } finally {
      setLoading(false)
    }
  }

  // ── Resend OTP ───────────────────────────────────────────────────────────
  const handleResend = async () => {
    if (resendCd > 0) return
    setLoading(true)
    try {
      await api.post('/auth/resend-otp', { email: otpEmail })
      startCooldown()
      showToast('New code sent! Check your inbox.', 'success')
    } catch (err) {
      showToast('Could not resend code. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  // ─── Render ───────────────────────────────────────────────────────────────
  return (
    <div className="page-center" style={{ padding: '20px 16px' }}>
      {toast && <Toast msg={toast.msg} type={toast.type} onClose={clearToast} />}

      <div className="card" style={{ width: '100%', maxWidth: 460 }}>
        {/* Header */}
        <div className="page-header" style={{ marginBottom: 24 }}>
          <div className="logo-mark">🛡</div>
          <h1>MIIC-Sec</h1>
          <p style={{ color: 'var(--clr-text-muted)', fontSize: '0.88rem', marginTop: 4 }}>
            AI-Powered Mock Interview Practice
          </p>
        </div>

        {screen === 'form' && (
          <>
            {/* Tab switcher */}
            <div style={{
              display: 'grid', gridTemplateColumns: '1fr 1fr',
              background: 'var(--clr-surface-2)', borderRadius: 'var(--r-sm)',
              padding: 4, marginBottom: 28, gap: 4,
            }}>
              {['login', 'signup'].map(t => (
                <button
                  key={t}
                  onClick={() => { setTab(t); clearToast() }}
                  style={{
                    padding: '9px 0', borderRadius: 'var(--r-sm)',
                    border: 'none', cursor: 'pointer', fontWeight: 600,
                    fontSize: '0.88rem', transition: 'all 0.18s',
                    background: tab === t ? 'var(--clr-primary)' : 'transparent',
                    color:      tab === t ? '#fff' : 'var(--clr-text-muted)',
                  }}
                >
                  {t === 'login' ? '🔑 Login' : '✨ Create Account'}
                </button>
              ))}
            </div>

            {/* Login form */}
            {tab === 'login' && (
              <form onSubmit={handleLogin}>
                <Field id="le" label="Email Address" type="email"
                  value={loginEmail} onChange={e => setLoginEmail(e.target.value)}
                  placeholder="you@example.com" autoFocus />
                <Field id="lp" label="Password" type="password"
                  value={loginPassword} onChange={e => setLoginPassword(e.target.value)}
                  placeholder="••••••••" />
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={loading}
                  style={{ width: '100%', justifyContent: 'center', marginTop: 4 }}
                >
                  {loading ? <><span className="spinner" />Signing in…</> : '→ Sign In'}
                </button>
              </form>
            )}

            {/* Signup form */}
            {tab === 'signup' && (
              <form onSubmit={handleSignup}>
                <Field id="sn" label="Full Name" value={signupName}
                  onChange={e => setSignupName(e.target.value)}
                  placeholder="Arjun Sharma" autoFocus />
                <Field id="se" label="Email Address" type="email" value={signupEmail}
                  onChange={e => setSignupEmail(e.target.value)}
                  placeholder="you@example.com" />
                <Field id="sp" label="Password (min. 6 chars)" type="password"
                  value={signupPassword} onChange={e => setSignupPassword(e.target.value)}
                  placeholder="••••••••" />
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={loading}
                  style={{ width: '100%', justifyContent: 'center', marginTop: 4 }}
                >
                  {loading ? <><span className="spinner" />Creating account…</> : '✨ Create Account'}
                </button>
                <p style={{ fontSize: '0.78rem', color: 'var(--clr-text-muted)', textAlign: 'center', marginTop: 14 }}>
                  By signing up you agree to use this platform for practice only.
                </p>
              </form>
            )}

            {/* Biometric login link */}
            <div style={{
              marginTop: 24, paddingTop: 20,
              borderTop: '1px solid var(--clr-border)',
              textAlign: 'center', fontSize: '0.82rem', color: 'var(--clr-text-muted)',
            }}>
              Have a Candidate ID?{' '}
              <Link to="/login" style={{ color: 'var(--clr-accent)' }}>
                Use Biometric Login →
              </Link>
            </div>
          </>
        )}

        {/* OTP verification screen */}
        {screen === 'otp' && (
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '3rem', marginBottom: 12 }}>📬</div>
            <h2 style={{ marginBottom: 8 }}>Check Your Email</h2>
            <p style={{ color: 'var(--clr-text-muted)', marginBottom: 24, fontSize: '0.9rem', lineHeight: 1.6 }}>
              We sent a <strong>6-digit verification code</strong> to<br />
              <strong style={{ color: 'var(--clr-primary)' }}>{otpEmail}</strong>
            </p>

            <form onSubmit={handleVerifyOtp}>
              <OtpInput value={otpCode} onChange={setOtpCode} />
              <button
                type="submit"
                className="btn btn-success"
                disabled={loading || otpCode.length !== 6}
                style={{ width: '100%', justifyContent: 'center' }}
              >
                {loading ? <><span className="spinner" />Verifying…</> : '✓ Verify Code'}
              </button>
            </form>

            <div style={{ marginTop: 20 }}>
              <button
                onClick={handleResend}
                disabled={resendCd > 0 || loading}
                style={{
                  background: 'none', border: 'none',
                  color: resendCd > 0 ? 'var(--clr-text-muted)' : 'var(--clr-primary)',
                  cursor: resendCd > 0 ? 'default' : 'pointer',
                  fontSize: '0.85rem', textDecoration: 'underline',
                }}
              >
                {resendCd > 0 ? `Resend in ${resendCd}s` : 'Resend code'}
              </button>
            </div>

            <button
              onClick={() => { setScreen('form'); setOtpCode(''); clearToast() }}
              style={{
                marginTop: 16, background: 'none', border: 'none',
                color: 'var(--clr-text-muted)', cursor: 'pointer',
                fontSize: '0.82rem',
              }}
            >
              ← Back
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
