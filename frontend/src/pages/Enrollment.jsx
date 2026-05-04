/**
 * Enrollment.jsx — 5-step candidate enrollment wizard (fixed).
 * step 1: Name + email
 * step 2: Face capture × 5
 * step 3: Voice recording 10s + API submit
 * step 4: TOTP QR scan + code verify
 * step 5: Success screen
 */
import React, { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../utils/api'
import styles from './Enrollment.module.css'

// ─── Step Bar ─────────────────────────────────────────────────────────────────
function StepBar({ current }) {
  const labels = ['Info', 'Face', 'Voice', 'TOTP', 'Done']
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
              <div style={{ fontSize: '0.68rem', color: 'var(--clr-text-muted)', marginTop: 3 }}>
                {label}
              </div>
            </div>
          </React.Fragment>
        )
      })}
    </div>
  )
}

// ─── Step 1: Info ─────────────────────────────────────────────────────────────
function InfoStep({ onNext }) {
  const [name,  setName]  = useState('')
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')

  const next = () => {
    if (!name.trim() || !email.trim()) { setError('Name and email are required.'); return }
    if (!/\S+@\S+\.\S+/.test(email))   { setError('Enter a valid email address.'); return }
    onNext(name.trim(), email.trim())
  }

  return (
    <div className={styles.stepContent}>
      <h2>👤 Your Information</h2>
      <p style={{ color: 'var(--clr-text-muted)', marginBottom: 16 }}>
        Enter your details to begin the enrollment process.
      </p>
      {error && <div className="alert alert-danger" style={{ marginBottom: 12 }}>{error}</div>}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 20 }}>
        <input
          className="input"
          placeholder="Full name"
          value={name}
          onChange={e => setName(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && next()}
        />
        <input
          className="input"
          type="email"
          placeholder="Email address"
          value={email}
          onChange={e => setEmail(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && next()}
        />
      </div>
      <button className="btn btn-primary" onClick={next}>Continue →</button>
    </div>
  )
}

// ─── Step 2: Face Capture ─────────────────────────────────────────────────────
function FaceStep({ onNext }) {
  const videoRef  = useRef(null)
  const canvasRef = useRef(null)
  const streamRef = useRef(null)

  const [photos,  setPhotos]  = useState([])   // data URL previews
  const [blobs,   setBlobs]   = useState([])   // File Blobs for upload
  const [camOn,   setCamOn]   = useState(false)
  const [error,   setError]   = useState('')

  useEffect(() => () => stopCam(), [])

  const startCam = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true })
      videoRef.current.srcObject = stream
      streamRef.current = stream
      await videoRef.current.play()
      setCamOn(true)
      setError('')
    } catch {
      setError('Camera access denied — please allow camera permission and try again.')
    }
  }

  const stopCam = () => {
    streamRef.current?.getTracks().forEach(t => t.stop())
    setCamOn(false)
  }

  const capture = () => {
    if (photos.length >= 5 || !camOn) return
    const v = videoRef.current
    const c = canvasRef.current
    c.width  = v.videoWidth
    c.height = v.videoHeight
    c.getContext('2d').drawImage(v, 0, 0)
    const dataUrl = c.toDataURL('image/jpeg', 0.9)
    c.toBlob(blob => setBlobs(prev => [...prev, blob]), 'image/jpeg', 0.9)
    setPhotos(prev => [...prev, dataUrl])
  }

  const proceed = () => {
    stopCam()
    onNext(blobs)
  }

  return (
    <div className={styles.stepContent}>
      <h2>📷 Face Capture</h2>
      <p style={{ color: 'var(--clr-text-muted)', marginBottom: 16 }}>
        Capture 5 clear photos of your face in good lighting.
      </p>

      {error && <div className="alert alert-danger" style={{ marginBottom: 12 }}>{error}</div>}

      <div className="webcam-frame" style={{ maxWidth: 420, margin: '0 auto 16px' }}>
        <video ref={videoRef} muted playsInline style={{ width: '100%' }} />
        <div className={`webcam-overlay ${camOn ? 'active' : ''}`} />
      </div>
      <canvas ref={canvasRef} style={{ display: 'none' }} />

      <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
        {!camOn
          ? <button className="btn btn-primary" onClick={startCam}>▶ Start Camera</button>
          : <button className="btn btn-ghost"   onClick={stopCam}>■ Stop</button>
        }
        <button
          className="btn btn-primary"
          onClick={capture}
          disabled={!camOn || photos.length >= 5}
        >
          📸 Capture ({photos.length}/5)
        </button>
      </div>

      {/* Thumbnail row */}
      <div className="thumb-row" style={{ marginBottom: 20 }}>
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="thumb">
            {photos[i]
              ? <><img src={photos[i]} alt={`cap-${i}`} /><div className="tick">✓</div></>
              : <div style={{ width: 60, height: 45, background: 'var(--clr-surface-2)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 18, color: 'var(--clr-text-muted)' }}>👤</div>
            }
          </div>
        ))}
      </div>

      <button
        className="btn btn-success"
        disabled={photos.length < 5}
        onClick={proceed}
      >
        Continue →
      </button>
    </div>
  )
}

// ─── Step 3: Voice + Submit ───────────────────────────────────────────────────
function VoiceStep({ name, email, faceBlobs, onNext }) {
  const recorderRef = useRef(null)
  const chunksRef   = useRef([])
  const timerRef    = useRef(null)
  const barsRef     = useRef(null)

  const [recording,  setRecording]  = useState(false)
  const [audioBlob,  setAudioBlob]  = useState(null)
  const [seconds,    setSeconds]    = useState(0)
  const [loading,    setLoading]    = useState(false)
  const [error,      setError]      = useState('')

  const drawBars = (analyser) => {
    const canvas = barsRef.current
    if (!canvas) return
    const ctx  = canvas.getContext('2d')
    const data = new Uint8Array(analyser.frequencyBinCount)
    const tick = () => {
      if (!recorderRef.current || recorderRef.current.state === 'inactive') return
      analyser.getByteFrequencyData(data)
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      const bw = canvas.width / data.length * 2.5
      data.forEach((v, i) => {
        const h = (v / 255) * canvas.height
        ctx.fillStyle = `hsl(${215 + i * 0.5}, 75%, 60%)`
        ctx.fillRect(i * bw * 1.1, canvas.height - h, bw, h)
      })
      requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  }

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      chunksRef.current = []
      const actx = new (window.AudioContext || window.webkitAudioContext)()
      const src  = actx.createMediaStreamSource(stream)
      const an   = actx.createAnalyser(); an.fftSize = 256
      src.connect(an)
      drawBars(an)

      const rec = new MediaRecorder(stream)
      rec.ondataavailable = e => chunksRef.current.push(e.data)
      rec.onstop = () => {
        stream.getTracks().forEach(t => t.stop())
        setAudioBlob(new Blob(chunksRef.current, { type: 'audio/webm' }))
        setRecording(false)
      }
      rec.start(100)
      recorderRef.current = rec
      setRecording(true)
      setSeconds(0)

      let s = 0
      timerRef.current = setInterval(() => {
        s += 1
        setSeconds(s)
        if (s >= 10) {
          clearInterval(timerRef.current)
          rec.stop()
        }
      }, 1000)
    } catch {
      setError('Microphone access denied — please allow microphone permission.')
    }
  }

  const stopEarly = () => {
    clearInterval(timerRef.current)
    recorderRef.current?.stop()
  }

  // Convert any browser audio format (WebM/MP4/OGG) → 16-bit PCM WAV
  const toWav = async (blob) => {
    const arrayBuf = await blob.arrayBuffer()
    const actx     = new (window.AudioContext || window.webkitAudioContext)()
    const decoded  = await actx.decodeAudioData(arrayBuf)
    const sr       = 16000
    const offline  = new OfflineAudioContext(1, decoded.duration * sr, sr)
    const src2     = offline.createBufferSource()
    src2.buffer    = decoded
    src2.connect(offline.destination)
    src2.start(0)
    const rendered = await offline.startRendering()
    const pcm      = rendered.getChannelData(0)
    const wavBuf   = new ArrayBuffer(44 + pcm.length * 2)
    const dv       = new DataView(wavBuf)
    const ws       = (off, s) => { for (let i = 0; i < s.length; i++) dv.setUint8(off + i, s.charCodeAt(i)) }
    ws(0, 'RIFF'); dv.setUint32(4, 36 + pcm.length * 2, true)
    ws(8, 'WAVE'); ws(12, 'fmt '); dv.setUint32(16, 16, true)
    dv.setUint16(20, 1, true); dv.setUint16(22, 1, true)
    dv.setUint32(24, sr, true); dv.setUint32(28, sr * 2, true)
    dv.setUint16(32, 2, true); dv.setUint16(34, 16, true)
    ws(36, 'data'); dv.setUint32(40, pcm.length * 2, true)
    for (let i = 0; i < pcm.length; i++)
      dv.setInt16(44 + i * 2, Math.max(-1, Math.min(1, pcm[i])) * 0x7fff, true)
    return new Blob([wavBuf], { type: 'audio/wav' })
  }

  const submit = async () => {
    if (!audioBlob) { setError('Please record your voice first.'); return }
    setLoading(true)
    setError('')
    try {
      const wavBlob = await toWav(audioBlob)
      const fd = new FormData()
      fd.append('candidate_name',  name)
      fd.append('candidate_email', email)
      faceBlobs.forEach((b, i) => fd.append('face_images', b, `face_${i}.jpg`))
      fd.append('voice_audio', wavBlob, 'voice.wav')
      const { data } = await api.post('/auth/enroll', fd)
      onNext(data)
    } catch (e) {
      const detail = e.response?.data?.detail
      setError(typeof detail === 'string' ? detail : JSON.stringify(detail) || 'Enrollment failed.')
    } finally {
      setLoading(false)
    }
  }


  return (
    <div className={styles.stepContent}>
      <h2>🎙 Voice Recording</h2>
      <p style={{ color: 'var(--clr-text-muted)', marginBottom: 16 }}>
        Record 10 seconds of your natural speaking voice.
      </p>

      {error && <div className="alert alert-danger" style={{ marginBottom: 12 }}>{error}</div>}

      <canvas
        ref={barsRef}
        width={420} height={72}
        style={{ width: '100%', maxWidth: 420, background: 'var(--clr-surface-2)', borderRadius: 'var(--r-sm)', marginBottom: 16 }}
      />

      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 20 }}>
        {!recording && !audioBlob && (
          <button className="btn btn-primary" onClick={startRecording}>⏺ Record 10 seconds</button>
        )}
        {recording && (
          <button className="btn btn-danger" onClick={stopEarly}>⏹ Stop ({10 - seconds}s left)</button>
        )}
        {audioBlob && !recording && (
          <span className="alert alert-success" style={{ margin: 0 }}>
            ✓ Recording ready ({seconds}s)
          </span>
        )}
        {audioBlob && !recording && (
          <button className="btn btn-ghost" onClick={() => { setAudioBlob(null); setSeconds(0) }}>
            Re-record
          </button>
        )}
      </div>

      <button
        className="btn btn-success"
        disabled={!audioBlob || loading || recording}
        onClick={submit}
      >
        {loading
          ? <><span className="spinner" style={{ marginRight: 8 }} /> Enrolling — this may take 30s…</>
          : 'Submit Enrollment →'}
      </button>

      {loading && (
        <p style={{ marginTop: 12, fontSize: '0.8rem', color: 'var(--clr-text-muted)' }}>
          ⏳ Processing face + voice biometrics…
        </p>
      )}
    </div>
  )
}

// ─── Step 4: TOTP Setup ───────────────────────────────────────────────────────
function TotpStep({ enrollData, onNext }) {
  const [code,  setCode]  = useState('')
  const [error, setError] = useState('')

  const verify = () => {
    if (code.length !== 6) { setError('Enter the 6-digit code from your authenticator app.'); return }
    onNext()
  }

  return (
    <div className={styles.stepContent}>
      <h2>🔐 TOTP Setup</h2>
      <p style={{ color: 'var(--clr-text-muted)', marginBottom: 20 }}>
        Scan the QR code with <strong>Google Authenticator</strong> or <strong>Authy</strong>,
        then enter the 6-digit code below.
      </p>

      {enrollData?.totp_qr_code_base64 ? (
        <div style={{ textAlign: 'center', marginBottom: 20 }}>
          <img
            src={`data:image/png;base64,${enrollData.totp_qr_code_base64}`}
            alt="TOTP QR Code"
            style={{ width: 200, height: 200, border: '4px solid white', borderRadius: 8 }}
          />
        </div>
      ) : (
        <div className="alert alert-warning" style={{ marginBottom: 16 }}>
          QR code unavailable — use the candidate ID to set up TOTP manually.
        </div>
      )}

      {error && <div className="alert alert-danger" style={{ marginBottom: 12 }}>{error}</div>}

      <input
        className="input"
        type="text"
        inputMode="numeric"
        maxLength={6}
        placeholder="000000"
        value={code}
        onChange={e => setCode(e.target.value.replace(/\D/g, ''))}
        onKeyDown={e => e.key === 'Enter' && verify()}
        style={{ fontSize: '1.8rem', letterSpacing: '0.35em', textAlign: 'center', maxWidth: 200, marginBottom: 16 }}
        autoFocus
      />

      <button className="btn btn-success" onClick={verify} disabled={code.length !== 6}>
        ✓ Verify &amp; Complete →
      </button>
    </div>
  )
}

// ─── Step 5: Success ──────────────────────────────────────────────────────────
function SuccessStep({ enrollData }) {
  const navigate = useNavigate()

  // Save candidate_id to localStorage so the Login page can pre-fill it
  useEffect(() => {
    if (enrollData?.candidate_id) {
      localStorage.setItem('lastCandidateId', enrollData.candidate_id)
    }
    // Auto-redirect to login after 4 seconds
    const timer = setTimeout(() => navigate('/login', { replace: true }), 4000)
    return () => clearTimeout(timer)
  }, [])   // eslint-disable-line

  return (
    <div className={styles.stepContent} style={{ textAlign: 'center' }}>
      <div style={{ fontSize: '4rem', marginBottom: 16 }}>🎉</div>
      <h2 style={{ color: 'var(--clr-success)', marginBottom: 8 }}>Enrollment Complete!</h2>
      <p style={{ color: 'var(--clr-text-muted)', marginBottom: 24 }}>
        Your biometric profile has been securely registered.
        Redirecting to login in 4 seconds…
      </p>
      <div className="card" style={{ textAlign: 'left', marginBottom: 24 }}>
        <p style={{ fontSize: '0.75rem', color: 'var(--clr-text-muted)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Your Candidate ID (saved automatically)
        </p>
        <p style={{ fontFamily: 'var(--font-mono)', color: 'var(--clr-primary)', wordBreak: 'break-all', fontSize: '0.9rem' }}>
          {enrollData?.candidate_id}
        </p>
        <p style={{ fontSize: '0.8rem', color: 'var(--clr-warning)', marginTop: 10 }}>
          ⚠️ This ID has been saved in your browser. Keep a separate copy too.
        </p>
      </div>
      <button className="btn btn-primary" style={{ width: '100%' }} onClick={() => navigate('/login', { replace: true })}>
        Proceed to Login →
      </button>
    </div>
  )
}

// ─── Main Component ───────────────────────────────────────────────────────────
export default function Enrollment() {
  const [step,       setStep]       = useState(1)
  const [name,       setName]       = useState('')
  const [email,      setEmail]      = useState('')
  const [faceBlobs,  setFaceBlobs]  = useState([])
  const [enrollData, setEnrollData] = useState(null)

  return (
    <div className="page-center">
      <div className="card" style={{ width: '100%', maxWidth: 560 }}>
        <div className="page-header">
          <div className="logo-mark">🛡</div>
          <h1>MIIC-Sec Enrollment</h1>
        </div>

        <StepBar current={step} />

        {step === 1 && (
          <InfoStep onNext={(n, e) => { setName(n); setEmail(e); setStep(2) }} />
        )}

        {step === 2 && (
          <FaceStep onNext={(blobs) => { setFaceBlobs(blobs); setStep(3) }} />
        )}

        {step === 3 && (
          <VoiceStep
            name={name}
            email={email}
            faceBlobs={faceBlobs}
            onNext={(data) => { setEnrollData(data); setStep(4) }}
          />
        )}

        {step === 4 && (
          <TotpStep enrollData={enrollData} onNext={() => setStep(5)} />
        )}

        {step === 5 && (
          <SuccessStep enrollData={enrollData} />
        )}
      </div>
    </div>
  )
}
