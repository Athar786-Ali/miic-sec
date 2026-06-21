/**
 * Login.jsx — 4-step multi-factor login.
 *
 * Step 0: Enter Candidate ID
 * Step 1: Face capture (webcam snapshot)
 * Step 2: Voice recording (8 s) ← NEW
 * Step 3: TOTP code → POST /auth/login → store token → navigate('/interview')
 */
import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import api, { setAuth } from '../utils/api'
import styles from './Login.module.css'

// ─── Step bar ─────────────────────────────────────────────────────────────────
function StepBar({ current }) {
  const labels = ['Face', 'Voice', 'TOTP']
  return (
    <div className="steps" style={{ marginBottom: 28 }}>
      {labels.map((label, i) => {
        const n   = i + 1
        const cls = n < current ? 'done' : n === current ? 'active' : ''
        return (
          <React.Fragment key={n}>
            {i > 0 && <div className={`step-connector ${n <= current ? 'done' : ''}`} />}
            <div style={{ textAlign: 'center' }}>
              <div className={`step-dot ${cls}`}>{n < current ? '✓' : n}</div>
              <div style={{ fontSize: '0.68rem', color: 'var(--clr-text-muted)', marginTop: 3 }}>{label}</div>
            </div>
          </React.Fragment>
        )
      })}
    </div>
  )
}

// ─── Voice recorder (reused from Enrollment) ─────────────────────────────────
function VoiceRecorder({ onDone }) {
  const mediaRef    = useRef(null)
  const chunksRef   = useRef([])
  const timerRef    = useRef(null)
  const animRef     = useRef(null)
  const analyserRef = useRef(null)
  const ctxRef      = useRef(null)

  const [phase, setPhase] = useState('idle')   // idle | recording | done | error
  const [secs,  setSecs]  = useState(8)
  const [bars,  setBars]  = useState(Array(20).fill(3))
  const [blob,  setBlob]  = useState(null)
  const [error, setError] = useState('')

  const animateWave = useCallback(() => {
    if (!analyserRef.current) return
    const data = new Uint8Array(analyserRef.current.frequencyBinCount)
    analyserRef.current.getByteFrequencyData(data)
    const step = Math.floor(data.length / 20)
    setBars(Array.from({ length: 20 }, (_, i) => Math.max(3, Math.round(((data[i * step] || 0) / 255) * 48))))
    animRef.current = requestAnimationFrame(animateWave)
  }, [])

  const start = async () => {
    setError(''); setBlob(null); chunksRef.current = []
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false })

      const audioCtx  = new (window.AudioContext || window.webkitAudioContext)()
      ctxRef.current  = audioCtx
      const analyser  = audioCtx.createAnalyser(); analyser.fftSize = 256
      audioCtx.createMediaStreamSource(stream).connect(analyser)
      analyserRef.current = analyser
      animRef.current = requestAnimationFrame(animateWave)

      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : ''

      const rec = new MediaRecorder(stream, mimeType ? { mimeType } : {})
      mediaRef.current = rec
      rec.ondataavailable = e => { if (e.data.size > 0) chunksRef.current.push(e.data) }
      rec.onstop = () => {
        stream.getTracks().forEach(t => t.stop())
        cancelAnimationFrame(animRef.current)
        audioCtx.close()
        setBars(Array(20).fill(3))
        const b = new Blob(chunksRef.current, { type: mimeType || 'audio/webm' })
        setBlob(b); setPhase('done')
      }

      rec.start(100); setPhase('recording')
      let rem = 8; setSecs(rem)
      timerRef.current = setInterval(() => {
        rem -= 1; setSecs(rem)
        if (rem <= 0) { clearInterval(timerRef.current); rec.stop() }
      }, 1000)
    } catch {
      setError('Microphone access denied. Please allow microphone and try again.')
      setPhase('error')
    }
  }

  const retry = () => {
    cancelAnimationFrame(animRef.current); clearInterval(timerRef.current)
    ctxRef.current?.close()
    setBlob(null); setPhase('idle'); setSecs(8); setBars(Array(20).fill(3)); setError('')
  }

  useEffect(() => () => {
    cancelAnimationFrame(animRef.current); clearInterval(timerRef.current)
    ctxRef.current?.close()
    mediaRef.current?.stream?.getTracks().forEach(t => t.stop())
  }, [])

  return (
    <div>
      <h2 style={{ marginBottom: 12 }}>🎙️ Voice Verification</h2>
      <p style={{ color: 'var(--clr-text-muted)', marginBottom: 16 }}>
        Read the sentence below aloud for <strong>8 seconds</strong>:
      </p>

      <div style={{
        background: 'var(--clr-surface-2)', border: '1px solid var(--clr-border)',
        borderRadius: 'var(--r-md)', padding: '12px 16px', marginBottom: 20,
        fontStyle: 'italic', color: 'var(--clr-text)', lineHeight: 1.6,
      }}>
        "My name is [your name] and I confirm my identity for the MIIC secure interview platform."
      </div>

      {error && <div className="alert alert-danger" style={{ marginBottom: 12 }}>{error}</div>}

      {/* Waveform */}
      <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'center', gap: 3, height: 56, marginBottom: 16 }}>
        {bars.map((h, i) => (
          <div key={i} style={{
            width: 6, height: h, borderRadius: 3,
            background: phase === 'recording'
              ? `hsl(${160 + i * 3}, 80%, 55%)`
              : phase === 'done' ? 'var(--clr-success)' : 'var(--clr-surface-3, var(--clr-border))',
            transition: 'height 0.08s ease',
          }} />
        ))}
      </div>

      <div style={{ textAlign: 'center', marginBottom: 20, minHeight: 24 }}>
        {phase === 'idle'      && <span style={{ color: 'var(--clr-text-muted)' }}>Press Start Recording below</span>}
        {phase === 'recording' && <span style={{ color: 'var(--clr-success)', fontWeight: 600 }}>🔴 Recording… {secs}s remaining</span>}
        {phase === 'done'      && <span style={{ color: 'var(--clr-success)', fontWeight: 600 }}>✅ Voice recorded!</span>}
      </div>

      <div style={{ display: 'flex', gap: 10 }}>
        {phase === 'idle' && (
          <button className="btn btn-primary" onClick={start} style={{ flex: 1 }}>🎙️ Start Recording</button>
        )}
        {phase === 'recording' && (
          <button className="btn btn-ghost" disabled style={{ flex: 1 }}>
            <span className="spinner" style={{ marginRight: 8 }} />Recording… {secs}s
          </button>
        )}
        {(phase === 'done' || phase === 'error') && (
          <button className="btn btn-ghost" onClick={retry} style={{ flex: 1 }}>🔄 Re-record</button>
        )}
        {phase === 'done' && (
          <button className="btn btn-success" onClick={() => onDone(blob)} style={{ flex: 1 }}>Continue →</button>
        )}
      </div>

      <p style={{ marginTop: 16, fontSize: '0.78rem', color: 'var(--clr-text-muted)', textAlign: 'center' }}>
        If your account has no voice enrolled, this step will be skipped automatically.{' '}
        <button
          onClick={() => onDone(null)}
          style={{ background: 'none', border: 'none', color: 'var(--clr-primary)', cursor: 'pointer', textDecoration: 'underline', fontSize: 'inherit', padding: 0 }}
        >
          Skip
        </button>
      </p>
    </div>
  )
}

// ─── Main Login component ─────────────────────────────────────────────────────
export default function Login() {
  const navigate = useNavigate()

  const [candidateId, setCandidateId] = useState(() => localStorage.getItem('lastCandidateId') || '')
  const [step,        setStep]        = useState(0)
  const [faceBlob,    setFaceBlob]    = useState(null)
  const [voiceBlob,   setVoiceBlob]   = useState(null)  // ← NEW
  const [totpCode,    setTotpCode]    = useState('')
  const [error,       setError]       = useState('')
  const [loading,     setLoading]     = useState(false)

  const videoRef  = useRef(null)
  const canvasRef = useRef(null)
  const streamRef = useRef(null)
  const [camOn,   setCamOn]   = useState(false)
  const doneRef   = useRef(false)

  // ── Camera helpers ──────────────────────────────────────────────────────────
  const startCam = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true })
      videoRef.current.srcObject = stream
      streamRef.current = stream
      await videoRef.current.play()
      setCamOn(true); setError('')
    } catch { setError('Camera access denied.') }
  }

  const stopCam = () => {
    streamRef.current?.getTracks().forEach(t => t.stop())
    streamRef.current = null
    setCamOn(false)
  }

  const capturePhoto = () => {
    const v = videoRef.current, c = canvasRef.current
    c.width = v.videoWidth; c.height = v.videoHeight
    c.getContext('2d').drawImage(v, 0, 0)
    c.toBlob(blob => {
      setFaceBlob(blob)
      stopCam()
      setStep(2)          // → Voice step
    }, 'image/jpeg', 0.9)
  }

  useEffect(() => { if (step === 1) startCam() }, [step]) // eslint-disable-line
  useEffect(() => () => stopCam(), [])                     // eslint-disable-line

  // ── Submit ──────────────────────────────────────────────────────────────────
  const submit = async () => {
    if (doneRef.current) return
    if (totpCode.length !== 6) { setError('Enter the 6-digit TOTP code.'); return }
    doneRef.current = true
    setError(''); setLoading(true)

    try {
      const fd = new FormData()
      fd.append('candidate_id', candidateId.trim())
      fd.append('face_image',   faceBlob, 'face.jpg')
      fd.append('totp_code',    totpCode)
      if (voiceBlob && voiceBlob.size > 1000) {
        fd.append('voice_audio', voiceBlob, 'voice_login.webm')
      }

      const { data } = await api.post('/auth/login', fd)

      setAuth({
        token:       data.access_token,
        sessionId:   data.session_id,
        candidateId: candidateId.trim(),
      })

      window.location.href = '/dashboard'

    } catch (e) {
      doneRef.current = false
      const detail = e.response?.data?.detail
      setError(typeof detail === 'string' ? detail : JSON.stringify(detail) || 'Login failed.')
    } finally {
      setLoading(false)
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div className="page-center">
      <div className="card" style={{ width: '100%', maxWidth: 480 }}>
        <div className="page-header">
          <div className="logo-mark">🛡</div>
          <h1>MIIC-Sec Login</h1>
        </div>

        {step > 0 && <StepBar current={step} />}
        {error && <div className="alert alert-danger" style={{ marginBottom: 16 }}>{error}</div>}

        {/* ── Step 0: Candidate ID ── */}
        {step === 0 && (
          <div className={styles.stepSlide}>
            <h2 style={{ marginBottom: 12 }}>Enter your Candidate ID</h2>
            <input
              className="input"
              placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
              value={candidateId}
              onChange={e => setCandidateId(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && candidateId.trim() && setStep(1)}
              style={{ marginBottom: 16, fontFamily: 'var(--font-mono)', fontSize: '0.85rem' }}
              autoFocus
            />
            <button
              className="btn btn-primary"
              disabled={!candidateId.trim()}
              onClick={() => setStep(1)}
            >
              Continue →
            </button>
            <p style={{ marginTop: 16, fontSize: '0.82rem', color: 'var(--clr-text-muted)' }}>
              Not enrolled? <Link to="/enroll">Register here</Link>
            </p>
          </div>
        )}

        {/* ── Step 1: Face ── */}
        {step === 1 && (
          <div className={styles.stepSlide}>
            <h2 style={{ marginBottom: 12 }}>📷 Face Verification</h2>
            <p style={{ color: 'var(--clr-text-muted)', marginBottom: 12 }}>
              Look directly at the camera and click Capture.
            </p>
            <div className="webcam-frame" style={{ maxWidth: 380, margin: '0 auto 16px' }}>
              <video ref={videoRef} muted playsInline style={{ width: '100%' }} />
              <div className={`webcam-overlay ${camOn ? 'active' : ''}`} />
            </div>
            <canvas ref={canvasRef} style={{ display: 'none' }} />
            {faceBlob
              ? <p className="alert alert-success" style={{ margin: '0 0 12px' }}>✓ Photo captured</p>
              : (
                <button className="btn btn-primary" disabled={!camOn} onClick={capturePhoto}>
                  📸 Capture Face
                </button>
              )
            }
          </div>
        )}

        {/* ── Step 2: Voice ── */}
        {step === 2 && (
          <div className={styles.stepSlide}>
            <VoiceRecorder
              onDone={(blob) => {
                setVoiceBlob(blob)
                setStep(3)
              }}
            />
          </div>
        )}

        {/* ── Step 3: TOTP ── */}
        {step === 3 && (
          <div className={styles.stepSlide}>
            <h2 style={{ marginBottom: 12 }}>🔐 Enter TOTP Code</h2>
            <p style={{ color: 'var(--clr-text-muted)', marginBottom: 16 }}>
              Open your authenticator app and enter the current 6-digit code.
            </p>
            <input
              className="input"
              type="text"
              inputMode="numeric"
              maxLength={6}
              placeholder="000000"
              value={totpCode}
              onChange={e => setTotpCode(e.target.value.replace(/\D/g, ''))}
              onKeyDown={e => e.key === 'Enter' && totpCode.length === 6 && submit()}
              style={{
                fontSize: '1.8rem', letterSpacing: '0.35em',
                textAlign: 'center', maxWidth: 200, marginBottom: 20,
              }}
              autoFocus
            />
            <button
              className="btn btn-success"
              disabled={loading || totpCode.length !== 6}
              onClick={submit}
            >
              {loading ? <><span className="spinner" /> Verifying…</> : '✓ Login'}
            </button>
            {loading && (
              <p style={{ marginTop: 12, fontSize: '0.8rem', color: 'var(--clr-text-muted)' }}>
                ⏳ Processing biometrics — may take up to 60 seconds on first run…
              </p>
            )}
          </div>
        )}
      </div>

      {/* Phase 1: Link to email/password signup */}
      <div style={{
        marginTop: 24, textAlign: 'center',
        fontSize: '0.83rem', color: 'var(--clr-text-muted)',
      }}>
        New here?{' '}
        <Link to="/signup" style={{ color: 'var(--clr-accent)', fontWeight: 600 }}>
          Create an account with email →
        </Link>
      </div>
    </div>
  )
}

