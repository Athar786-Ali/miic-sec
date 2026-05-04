import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api, { getAuth, clearAuth } from '../utils/api'
import InterviewSetup from './InterviewSetup'

const WS_BASE = 'ws://localhost:8000'

// ── Voice hook (MediaRecorder + Backend Whisper) ──────────────────
function useVoiceInput({ onTranscribed, onError }) {
  const [voiceState, setVoiceState] = useState('IDLE') // IDLE, RECORDING, TRANSCRIBING, DONE, ERROR
  const [recSecs, setRecSecs]       = useState(0)
  const mediaRecorderRef = useRef(null)
  const chunksRef        = useRef([])
  const timerRef         = useRef(null)
  const streamRef        = useRef(null)

  // Pick best supported MIME type
  const getSupportedMime = () => {
    const types = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']
    return types.find(t => MediaRecorder.isTypeSupported(t)) || ''
  }

  const start = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false })
      streamRef.current = stream
      const mimeType = getSupportedMime()
      const mr = new MediaRecorder(stream, mimeType ? { mimeType } : {})
      chunksRef.current = []
      setRecSecs(0)

      // Collect data every 250ms for reliability
      mr.ondataavailable = e => { if (e.data && e.data.size > 0) chunksRef.current.push(e.data) }

      mr.onstop = async () => {
        clearInterval(timerRef.current)
        setVoiceState('TRANSCRIBING')
        stream.getTracks().forEach(t => t.stop())

        if (chunksRef.current.length === 0) {
          setVoiceState('ERROR')
          onError?.('No audio data captured. Please try again.')
          return
        }

        const blob = new Blob(chunksRef.current, { type: mimeType || 'audio/webm' })
        const ext  = mimeType?.includes('ogg') ? 'ogg' : mimeType?.includes('mp4') ? 'mp4' : 'webm'
        const formData = new FormData()
        formData.append('audio_file', blob, `answer.${ext}`)

        try {
          const { data } = await api.post('/interview/transcribe', formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
            timeout: 120000,
          })
          const text = (data.transcript || '').trim()
          onTranscribed(text)
          setVoiceState(text ? 'DONE' : 'ERROR')
          if (!text) onError?.('Nothing was transcribed. Please speak clearly and try again.')
        } catch (err) {
          console.error('Transcription error', err)
          const msg = err.response?.data?.detail || 'Transcription failed. Please type your answer below.'
          setVoiceState('ERROR')
          onError?.(msg)
        }
      }

      mr.onerror = () => {
        clearInterval(timerRef.current)
        setVoiceState('ERROR')
        onError?.('Recording error. Please try again.')
      }

      mediaRecorderRef.current = mr
      mr.start(250)  // fire ondataavailable every 250ms
      setVoiceState('RECORDING')

      // Live recording timer
      timerRef.current = setInterval(() => setRecSecs(s => s + 1), 1000)

    } catch (err) {
      console.error('Mic error', err)
      const msg = err.name === 'NotAllowedError'
        ? 'Microphone permission denied. Please allow mic access and try again.'
        : `Microphone error: ${err.message}`
      setVoiceState('ERROR')
      onError?.(msg)
    }
  }

  const stop = () => {
    clearInterval(timerRef.current)
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      mediaRecorderRef.current.stop()
    }
  }

  const reset = () => {
    clearInterval(timerRef.current)
    streamRef.current?.getTracks().forEach(t => t.stop())
    chunksRef.current = []
    setRecSecs(0)
    setVoiceState('IDLE')
  }

  return { voiceState, recSecs, start, stop, reset }
}

// ── Webcam component (continuous capture for face verify) ─────────
function WebcamPanel({ sessionId, secStatus }) {
  const videoRef  = useRef(null)
  const canvasRef = useRef(null)
  const streamRef = useRef(null)
  const timerRef  = useRef(null)
  const [camOn, setCamOn] = useState(false)

  const startCam = async () => {
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: true })
      videoRef.current.srcObject = s; streamRef.current = s
      await videoRef.current.play(); setCamOn(true)
    } catch { console.warn('Camera denied') }
  }
  const stopCam = () => { streamRef.current?.getTracks().forEach(t => t.stop()); setCamOn(false) }

  const capture = () => {
    if (!camOn) return null
    const v = videoRef.current, c = canvasRef.current
    c.width = v.videoWidth; c.height = v.videoHeight
    c.getContext('2d').drawImage(v, 0, 0)
    return new Promise(res => c.toBlob(res, 'image/jpeg', 0.8))
  }

  // Auto-capture every 30s for continuous face check
  useEffect(() => {
    if (!camOn || !sessionId) return
    timerRef.current = setInterval(async () => {
      const blob = await capture()
      if (!blob) return
      try {
        const fd = new FormData(); fd.append('frame', blob, 'frame.jpg')
        await api.post('/security/face-recheck', fd)
      } catch {}
    }, 30000)
    return () => clearInterval(timerRef.current)
  }, [camOn, sessionId]) // eslint-disable-line

  useEffect(() => { startCam(); return stopCam }, []) // eslint-disable-line

  const borderColor = secStatus === 'green' ? 'var(--clr-success)' : secStatus === 'red' ? 'var(--clr-danger)' : 'var(--clr-warning)'

  return (
    <div style={{ border: `2px solid ${borderColor}`, borderRadius: 'var(--r-md)', overflow: 'hidden', background: '#000', transition: 'border-color 0.4s', marginBottom: 16 }}>
      <div style={{ position: 'relative' }}>
        <video ref={videoRef} muted playsInline style={{ width: '100%', display: 'block', height: 200, objectFit: 'cover' }} />
        <div style={{ position: 'absolute', top: 8, right: 8, fontSize: '0.72rem', color: '#fff', background: 'rgba(0,0,0,0.65)', borderRadius: 4, padding: '2px 8px', fontWeight: 600 }}>
          {camOn ? '🔴 LIVE' : '⚫ OFF'}
        </div>
      </div>
      <canvas ref={canvasRef} style={{ display: 'none' }} />
    </div>
  )
}

// ── Step-up TOTP panel ────────────────────────────────────────────
function StepUpTotp({ sessionId, onPassed }) {
  const [code, setCode] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const submit = async () => {
    if (code.length !== 6) return
    setLoading(true); setError('')
    try {
      await api.post('/security/step-up-verify', { session_id: sessionId, totp_code: code })
      onPassed()
    } catch (e) { setError(e.response?.data?.detail || 'Verification failed.') }
    finally { setLoading(false) }
  }
  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.85)', zIndex: 999, display: 'flex', alignItems: 'center', justifyContent: 'center', backdropFilter: 'blur(8px)' }}>
      <div className="card" style={{ maxWidth: 380, width: '100%', textAlign: 'center' }}>
        <div style={{ fontSize: '3rem', marginBottom: 12 }}>🔐</div>
        <h2 style={{ color: 'var(--clr-warning)', marginBottom: 8 }}>Identity Re-Verification</h2>
        <p style={{ color: 'var(--clr-text-muted)', marginBottom: 20 }}>Enter your 6-digit TOTP code to unlock your interview session.</p>
        {error && <div className="alert alert-danger" style={{ marginBottom: 12 }}>{error}</div>}
        <input className="input" type="text" inputMode="numeric" maxLength={6}
          value={code} onChange={e => setCode(e.target.value.replace(/\D/g, ''))}
          onKeyDown={e => e.key === 'Enter' && submit()}
          style={{ fontSize: '2rem', letterSpacing: '0.4em', textAlign: 'center', maxWidth: 220, marginBottom: 20, margin: '0 auto', display: 'block' }}
          autoFocus />
        <button className="btn btn-success" disabled={code.length !== 6 || loading} onClick={submit} style={{ width: '100%', padding: '12px' }}>
          {loading ? <><span className="spinner" /> Verifying…</> : 'Unlock Session'}
        </button>
      </div>
    </div>
  )
}

// ── Code editor panel ─────────────────────────────────────────────
function CodePanel({ templateCode }) {
  const [code, setCode]       = useState(templateCode || '# Write your solution here\n')
  const [lang, setLang]       = useState('python')
  const [result, setResult]   = useState(null)
  const [running, setRunning] = useState(false)

  // When template updates, update code
  useEffect(() => {
    if (templateCode) setCode(templateCode)
  }, [templateCode])

  const run = async () => {
    setRunning(true)
    try { const { data } = await api.post('/interview/execute-code', { code, language: lang }); setResult(data) }
    catch { setResult({ passed: false, stderr: 'Execution error' }) }
    finally { setRunning(false) }
  }
  return (
    <div className="card" style={{ marginTop: 24, background: '#1e1e1e', borderColor: '#333' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <h3 style={{ margin: 0, color: '#d4d4d4', fontSize: '0.9rem' }}>💻 Code Editor</h3>
        <div style={{ display: 'flex', gap: 8 }}>
          <select value={lang} onChange={e => setLang(e.target.value)} className="input" style={{ width: 120, padding: '4px 8px', background: '#2d2d2d', borderColor: '#444', color: '#ccc' }}>
            <option value="python">Python</option><option value="javascript">JavaScript</option>
            <option value="java">Java</option><option value="cpp">C++</option>
          </select>
          <button className="btn btn-primary" disabled={running} onClick={run} style={{ padding: '6px 16px', background: '#0e639c' }}>
            {running ? <span className="spinner" /> : '▶ Run Code'}
          </button>
        </div>
      </div>
      <textarea value={code} onChange={e => setCode(e.target.value)}
        style={{ width: '100%', minHeight: 280, fontFamily: 'var(--font-mono)', fontSize: '0.9rem',
          background: '#1e1e1e', border: '1px solid #333', borderRadius: 'var(--r-sm)',
          padding: 16, color: '#d4d4d4', resize: 'vertical', boxSizing: 'border-box' }} />
      {result && (
        <div style={{ marginTop: 12, padding: 12, background: '#252526', borderRadius: 'var(--r-sm)', fontSize: '0.85rem', fontFamily: 'var(--font-mono)', border: '1px solid #333' }}>
          <div style={{ color: result.passed ? 'var(--clr-success)' : 'var(--clr-danger)', marginBottom: 6, fontWeight: 600 }}>
            {result.passed ? '✓ Tests Passed' : '✗ Tests Failed'} {result.execution_time_ms != null ? `· ${result.execution_time_ms}ms` : ''}
          </div>
          {result.stdout && <pre style={{ margin: 0, whiteSpace: 'pre-wrap', color: '#ccc' }}>{result.stdout}</pre>}
          {result.stderr && <pre style={{ margin: 0, color: '#f48771', whiteSpace: 'pre-wrap', marginTop: 8 }}>{result.stderr}</pre>}
          {result.static_issues?.length > 0 && <div style={{ marginTop: 8, color: '#cca700' }}>⚠ {result.static_issues.join(', ')}</div>}
        </div>
      )}
    </div>
  )
}

// ── Main Interview component ──────────────────────────────────────
export default function Interview() {
  const navigate = useNavigate()
  const { sessionId } = getAuth()

  // Setup / session config
  const [config,      setConfig]      = useState(null)

  // Interview state
  const [question,    setQuestion]    = useState('')
  const [answer,      setAnswer]      = useState('')
  const [score,       setScore]       = useState(null)
  const [feedback,    setFeedback]    = useState('')
  const [qNum,        setQNum]        = useState(1)
  const [difficulty,  setDifficulty]  = useState('medium')
  const [submitting,  setSubmitting]  = useState(false)
  const [timeLeft,    setTimeLeft]    = useState(1200)

  // DSA Code template tracking
  const [isDsa,       setIsDsa]       = useState(false)
  const [templateCode, setTemplateCode] = useState('')

  // Security state
  const [wsConnected, setWsConnected] = useState(false)
  const [secStatus,   setSecStatus]   = useState('green')
  const [alerts,      setAlerts]      = useState([])
  const [showTotp,    setShowTotp]    = useState(false)
  const [terminated,  setTerminated]  = useState(false)
  const [termReason,  setTermReason]  = useState('')
  const [ended,       setEnded]       = useState(false)
  const [error,       setError]       = useState('')

  const wsRef    = useRef(null)
  const timerRef = useRef(null)
  const doneRef  = useRef(false)

  const pushAlert = (msg, type = 'warning') =>
    setAlerts(a => [...a.slice(-5), { msg, type, id: Date.now() }])

  const [voiceError, setVoiceError] = useState('')
  const [inputMode, setInputMode]   = useState('voice') // 'voice' | 'text'

  const { voiceState, recSecs, start: startVoice, stop: stopVoice, reset: resetVoice } = useVoiceInput({
    onTranscribed: useCallback(text => {
      setAnswer(text)
      setVoiceError('')
    }, []),
    onError: useCallback(msg => {
      setVoiceError(msg)
    }, []),
  })

  // WebSocket
  useEffect(() => {
    if (!sessionId) { navigate('/login'); return }
    const ws = new WebSocket(`${WS_BASE}/ws/candidate/${sessionId}`)
    wsRef.current = ws
    ws.onopen  = () => setWsConnected(true)
    ws.onclose = () => setWsConnected(false)
    ws.onmessage = e => {
      try {
        const { event, data } = JSON.parse(e.data)
        switch (event) {
          case 'STEP_UP_TOTP_REQUIRED':
            setSecStatus('red'); setShowTotp(true)
            pushAlert('⚠️ Identity verification required', 'danger'); break
          case 'SESSION_TERMINATED':
            setTerminated(true); setTermReason(data?.reason || ''); ws.close(); break
          case 'MULTIPLE_PERSONS_ALERT':
            setSecStatus('red'); pushAlert(`🚨 Multiple persons detected`, 'danger'); break
          case 'MULTIPLE_SPEAKERS_ALERT':
            setSecStatus('red'); pushAlert('🚨 Multiple speakers detected', 'danger'); break
          case 'TAB_SWITCH_WARNING':
            setSecStatus('yellow'); pushAlert(`⚠️ Tab-switch detected`, 'warning'); break
          case 'RECHECK_PASSED':
            setSecStatus('green'); pushAlert('✅ Identity verified', 'success'); setShowTotp(false); break
          case 'INTERVIEW_COMPLETED':
            setEnded(true); break
          default: break
        }
      } catch {}
    }
    return () => ws.close()
  }, []) // eslint-disable-line

  // Timer
  useEffect(() => {
    if (!config || ended || terminated) return
    setTimeLeft(config.time_limit_minutes * 60)
    timerRef.current = setInterval(() => {
      setTimeLeft(t => {
        if (t <= 1) { clearInterval(timerRef.current); handleEnd(); return 0 }
        return t - 1
      })
    }, 1000)
    return () => clearInterval(timerRef.current)
  }, [config]) // eslint-disable-line

  // Tab-switch detection
  useEffect(() => {
    const onVis = () => { if (document.hidden && config) pushAlert('⚠️ Tab switch detected', 'warning') }
    document.addEventListener('visibilitychange', onVis)
    return () => document.removeEventListener('visibilitychange', onVis)
  }, [config])

  // Extract DSA Template
  const updateQuestionAndTemplate = (qText) => {
    // Strip markdown formatting if present
    const cleanText = qText.replace(/```python\n/g, '').replace(/```/g, '')
    setQuestion(cleanText)

    // Detect if it's a coding question
    const isCoding = /def |function |void |class /.test(cleanText)
    setIsDsa(isCoding)

    if (isCoding) {
      // Extract everything from the function signature onwards
      const match = cleanText.match(/(def |function |void |class )[\s\S]+/)
      if (match) {
        setTemplateCode(match[0])
      } else {
        setTemplateCode('# Write your code here\n')
      }
    } else {
      setTemplateCode('')
    }
  }

  // ── Start session from setup ──────────────────────────────────
  const handleStart = (data) => {
    setConfig(data)
    updateQuestionAndTemplate(data.first_question)
    setDifficulty(data.difficulty); setQNum(1)
  }

  // ── Submit answer ─────────────────────────────────────────────
  const submitAnswer = async () => {
    if (!answer.trim() || submitting || doneRef.current) return
    setSubmitting(true); setError(''); setVoiceError('')
    try {
      const { data } = await api.post('/interview/respond', {
        candidate_response: answer.trim(),
        input_mode: inputMode,
      })
      setScore(data.score); setFeedback(data.feedback)
      setDifficulty(data.difficulty); setQNum(data.question_number)
      setAnswer('')
      resetVoice()
      
      if (data.auto_end) { handleEnd() }
      else {
        updateQuestionAndTemplate(data.next_question)
        setTimeout(() => { setScore(null); setFeedback('') }, 4000)
      }
    } catch (e) { setError(e.response?.data?.detail || 'Submission failed.') }
    finally { setSubmitting(false) }
  }

  // ── End interview ─────────────────────────────────────────────
  const handleEnd = async () => {
    if (doneRef.current) return
    doneRef.current = true
    clearInterval(timerRef.current)
    try {
      await api.post('/interview/end')
      setEnded(true)
      setTimeout(() => navigate(`/report/${sessionId}`, { replace: true }), 1800)
    } catch { setEnded(true) }
  }

  // ── Terminated screen ─────────────────────────────────────────
  if (terminated) return (
    <div className="page-center">
      <div className="card" style={{ maxWidth: 420, textAlign: 'center' }}>
        <div style={{ fontSize: '3rem', marginBottom: 12 }}>⛔</div>
        <h2 style={{ color: 'var(--clr-danger)' }}>Session Terminated</h2>
        <p style={{ color: 'var(--clr-text-muted)', marginBottom: 20 }}>{termReason || 'Your session was ended by the security system.'}</p>
        <button className="btn btn-ghost" onClick={() => { clearAuth(); navigate('/login', { replace: true }) }}>← Back to Login</button>
      </div>
    </div>
  )

  // ── Ended screen ──────────────────────────────────────────────
  if (ended) return (
    <div className="page-center">
      <div className="card" style={{ maxWidth: 420, textAlign: 'center' }}>
        <div style={{ fontSize: '3rem', marginBottom: 12 }}>🏁</div>
        <h2>Interview Complete</h2>
        <p style={{ color: 'var(--clr-text-muted)' }}>Generating your report…</p>
        <span className="spinner" style={{ width: 36, height: 36, marginTop: 16 }} />
      </div>
    </div>
  )

  // ── Setup screen (before interview starts) ────────────────────
  if (!config) return <InterviewSetup onStart={handleStart} />

  // Format timer
  const mins = Math.floor(timeLeft / 60), secs = timeLeft % 60
  const isTimerLow = timeLeft < 120

  // ── Main interview UI ─────────────────────────────────────────
  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      
      {/* TOTP Overlay */}
      {showTotp && <StepUpTotp sessionId={sessionId} onPassed={() => { setShowTotp(false); setSecStatus('green') }} />}

      {/* TOP BAR */}
      <div style={{ padding: '16px 24px', background: 'var(--clr-surface)', borderBottom: '1px solid var(--clr-border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div className="logo-mark">🛡</div>
          <h1 style={{ fontSize: '1.2rem', margin: 0, fontWeight: 700 }}>MIIC-Sec Interview</h1>
        </div>
        <div style={{ color: 'var(--clr-text-muted)', fontFamily: 'var(--font-mono)', fontSize: '0.85rem' }}>
          Session: {sessionId.split('-')[0]}
        </div>
        <button className="btn btn-danger" style={{ padding: '6px 16px', fontSize: '0.8rem' }} onClick={() => { if(window.confirm('Are you sure you want to end the interview early?')) handleEnd() }}>
          End Interview
        </button>
      </div>

      {/* 3-COLUMN GRID */}
      <div style={{ display: 'grid', gridTemplateColumns: '280px 1fr 260px', gap: 24, padding: 24, flex: 1, maxWidth: 1600, margin: '0 auto', width: '100%' }}>
        
        {/* LEFT PANEL: Security & Bio */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="card" style={{ padding: 16 }}>
            <h3 style={{ fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 12px' }}>Live Security Feed</h3>
            <WebcamPanel sessionId={sessionId} secStatus={secStatus} />
            
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: '0.85rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 12px', background: 'var(--clr-surface-2)', borderRadius: 'var(--r-sm)' }}>
                <span style={{ color: 'var(--clr-text-muted)' }}>Emotion</span>
                <span>😊 Confident</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 12px', background: 'var(--clr-surface-2)', borderRadius: 'var(--r-sm)' }}>
                <span style={{ color: 'var(--clr-text-muted)' }}>Gaze</span>
                <span>👁️ Focused</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 12px', background: 'var(--clr-surface-2)', borderRadius: 'var(--r-sm)', alignItems: 'center' }}>
                <span style={{ color: 'var(--clr-text-muted)' }}>Status</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span className={`status-dot ${secStatus === 'green' ? 'green' : secStatus === 'yellow' ? 'yellow' : 'red'}`} />
                  <span style={{ color: secStatus === 'green' ? 'var(--clr-success)' : secStatus === 'red' ? 'var(--clr-danger)' : 'var(--clr-warning)', fontWeight: 600, fontSize: '0.8rem', textTransform: 'uppercase' }}>
                    {secStatus === 'green' ? 'All Clear' : 'Alert'}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* CENTER PANEL: Question & Input */}
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          
          {error && <div className="alert alert-danger" style={{ marginBottom: 16 }}>{error}</div>}
          
          <div className="card" style={{ flex: 1, display: 'flex', flexDirection: 'column', padding: 32 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
              <span className={`badge badge-${difficulty}`} style={{ fontSize: '0.8rem', padding: '4px 12px' }}>{difficulty}</span>
              <span style={{ color: 'var(--clr-text-muted)', fontSize: '0.9rem', fontWeight: 500 }}>Question {qNum} of {config.max_questions}</span>
            </div>

            <p style={{ fontSize: '1.25rem', lineHeight: 1.6, fontWeight: 500, color: 'var(--clr-text)', marginBottom: 24, whiteSpace: 'pre-wrap' }}>
              {question}
            </p>

            <div className="divider" style={{ margin: '12px 0 24px' }} />

            {/* Score feedback overlay */}
            {score != null && (
              <div className={`alert alert-${score >= 7 ? 'success' : score >= 5 ? 'warning' : 'danger'}`} style={{ marginBottom: 20 }}>
                <strong>Score {score}/10 ·</strong> {feedback}
              </div>
            )}

            {/* ── INPUT MODE TOGGLE ─────────────────────────── */}
            <div style={{ display: 'flex', gap: 8, marginTop: 'auto', marginBottom: 20 }}>
              <button
                onClick={() => { setInputMode('voice'); setVoiceError('') }}
                style={{
                  flex: 1, padding: '8px', borderRadius: 'var(--r-sm)', fontSize: '0.82rem', fontWeight: 600,
                  background: inputMode === 'voice' ? 'var(--clr-primary)' : 'var(--clr-surface-2)',
                  color: inputMode === 'voice' ? '#fff' : 'var(--clr-text-muted)',
                  border: `1px solid ${inputMode === 'voice' ? 'var(--clr-primary)' : 'var(--clr-border)'}`,
                  cursor: 'pointer', transition: 'all 0.2s',
                }}
              >🎙 Voice</button>
              <button
                onClick={() => { setInputMode('text'); resetVoice() }}
                style={{
                  flex: 1, padding: '8px', borderRadius: 'var(--r-sm)', fontSize: '0.82rem', fontWeight: 600,
                  background: inputMode === 'text' ? 'var(--clr-primary)' : 'var(--clr-surface-2)',
                  color: inputMode === 'text' ? '#fff' : 'var(--clr-text-muted)',
                  border: `1px solid ${inputMode === 'text' ? 'var(--clr-primary)' : 'var(--clr-border)'}`,
                  cursor: 'pointer', transition: 'all 0.2s',
                }}
              >⌨️ Type</button>
            </div>

            {/* ── VOICE MODE ─────────────────────────────────── */}
            {inputMode === 'voice' && (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>

                {/* Voice error banner */}
                {voiceError && (
                  <div className="alert alert-danger" style={{ width: '100%', marginBottom: 12, fontSize: '0.85rem' }}>
                    ⚠️ {voiceError}
                    <button onClick={() => setVoiceError('')} style={{ marginLeft: 8, background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', fontWeight: 700 }}>✕</button>
                  </div>
                )}

                {/* Big mic button */}
                <button
                  id="mic-btn"
                  onClick={voiceState === 'RECORDING' ? stopVoice : () => { setVoiceError(''); startVoice() }}
                  disabled={submitting || voiceState === 'TRANSCRIBING'}
                  style={{
                    width: 84, height: 84, borderRadius: '50%',
                    background: voiceState === 'RECORDING'
                      ? 'var(--clr-danger)'
                      : voiceState === 'ERROR' ? 'var(--clr-surface-2)'
                      : 'var(--clr-surface-2)',
                    border: `3px solid ${
                      voiceState === 'RECORDING' ? 'var(--clr-danger)'
                      : voiceState === 'DONE'      ? 'var(--clr-success)'
                      : voiceState === 'ERROR'     ? 'var(--clr-danger)'
                      : 'var(--clr-primary)'
                    }`,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: '2.2rem',
                    cursor: submitting || voiceState === 'TRANSCRIBING' ? 'not-allowed' : 'pointer',
                    transition: 'all 0.2s', margin: '0 auto 12px',
                    boxShadow: voiceState === 'RECORDING'
                      ? '0 0 24px rgba(239,68,68,0.5)'
                      : '0 4px 14px rgba(0,0,0,0.25)',
                    animation: voiceState === 'RECORDING' ? 'pulse-ring 1.4s ease-in-out infinite' : 'none',
                  }}
                >
                  {voiceState === 'TRANSCRIBING' ? <span className="spinner" style={{ width: 28, height: 28 }} />
                    : voiceState === 'RECORDING' ? '⏹'
                    : voiceState === 'DONE'      ? '✅'
                    : voiceState === 'ERROR'     ? '🔄'
                    : '🎙'}
                </button>

                {/* Status label */}
                <div style={{
                  fontSize: '0.88rem', fontWeight: 600, marginBottom: 16, minHeight: 22,
                  color: voiceState === 'RECORDING' ? 'var(--clr-danger)'
                       : voiceState === 'DONE'      ? 'var(--clr-success)'
                       : voiceState === 'ERROR'     ? 'var(--clr-danger)'
                       : 'var(--clr-text-muted)',
                  display: 'flex', alignItems: 'center', gap: 6,
                }}>
                  {voiceState === 'IDLE'        && '🎙 Tap mic to start recording'}
                  {voiceState === 'RECORDING'   && `⏺ Recording… ${recSecs}s — tap to stop`}
                  {voiceState === 'TRANSCRIBING'&& 'Converting speech to text…'}
                  {voiceState === 'DONE'        && '✅ Answer captured — review below'}
                  {voiceState === 'ERROR'       && '⟳ Tap mic to try again'}
                </div>

                {/* Transcript preview box */}
                <div style={{
                  width: '100%', minHeight: 90, padding: '12px 14px',
                  background: 'var(--clr-surface-2)', borderRadius: 'var(--r-sm)',
                  border: `1px solid ${
                    voiceState === 'DONE'  ? 'var(--clr-success)'
                    : voiceState === 'ERROR' ? 'var(--clr-danger)'
                    : 'var(--clr-border)'
                  }`,
                  fontSize: '0.97rem', lineHeight: 1.65, marginBottom: 16,
                  transition: 'border-color 0.3s',
                }}>
                  {voiceState === 'TRANSCRIBING'
                    ? <span style={{ color: 'var(--clr-text-muted)', fontStyle: 'italic' }}>Processing your speech…</span>
                    : answer
                    ? <span style={{ color: 'var(--clr-text)' }}>{answer}</span>
                    : <span style={{ color: 'var(--clr-text-muted)', fontStyle: 'italic' }}>Transcribed text will appear here…</span>
                  }
                </div>

                {/* Action buttons row */}
                <div style={{ display: 'flex', width: '100%', gap: 10 }}>
                  {(voiceState === 'DONE' || voiceState === 'ERROR') && (
                    <button className="btn btn-ghost" style={{ padding: '12px 20px', whiteSpace: 'nowrap' }}
                      onClick={() => { setAnswer(''); resetVoice(); setVoiceError('') }}
                    >🔄 Re-record</button>
                  )}
                  <button
                    className="btn btn-primary"
                    style={{ flex: 1, padding: '13px', fontSize: '1rem', justifyContent: 'center' }}
                    disabled={!answer.trim() || submitting || voiceState === 'RECORDING' || voiceState === 'TRANSCRIBING'}
                    onClick={submitAnswer}
                  >
                    {submitting ? <><span className="spinner" /> Evaluating…</> : 'Submit Answer'}
                  </button>
                </div>
              </div>
            )}

            {/* ── TEXT MODE ──────────────────────────────────── */}
            {inputMode === 'text' && (
              <div style={{ display: 'flex', flexDirection: 'column', width: '100%' }}>
                <textarea
                  id="text-answer"
                  value={answer}
                  onChange={e => setAnswer(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter' && e.ctrlKey) submitAnswer() }}
                  placeholder="Type your answer here… (Ctrl+Enter to submit)"
                  rows={7}
                  style={{
                    width: '100%', padding: '14px', fontFamily: 'var(--font-sans)', fontSize: '0.97rem',
                    background: 'var(--clr-surface-2)', border: '1px solid var(--clr-border)',
                    borderRadius: 'var(--r-sm)', color: 'var(--clr-text)', resize: 'vertical',
                    lineHeight: 1.6, outline: 'none', boxSizing: 'border-box', marginBottom: 14,
                    transition: 'border-color 0.2s',
                  }}
                  onFocus={e => e.target.style.borderColor = 'var(--clr-primary)'}
                  onBlur={e  => e.target.style.borderColor = 'var(--clr-border)'}
                />
                <div style={{ fontSize: '0.75rem', color: 'var(--clr-text-muted)', marginBottom: 10, textAlign: 'right' }}>
                  {answer.trim().split(/\s+/).filter(Boolean).length} words
                </div>
                <button
                  className="btn btn-primary"
                  style={{ width: '100%', padding: '13px', fontSize: '1rem', justifyContent: 'center' }}
                  disabled={!answer.trim() || submitting}
                  onClick={submitAnswer}
                >
                  {submitting ? <><span className="spinner" /> Evaluating…</> : 'Submit Answer'}
                </button>
              </div>
            )}
            
            {/* If DSA Question, show Editor */}
            {isDsa && (
              <div style={{ marginTop: 32 }}>
                <div className="divider" style={{ margin: '0 0 24px' }} />
                <h3 style={{ margin: '0 0 8px', color: 'var(--clr-primary)' }}>Coding Exercise</h3>
                <p style={{ color: 'var(--clr-text-muted)', fontSize: '0.9rem', marginBottom: 0 }}>Implement the requested function in the editor below. Use the voice input above to explain your approach.</p>
                <CodePanel templateCode={templateCode} />
              </div>
            )}
            
          </div>
        </div>

        {/* RIGHT PANEL: Stats & Logs */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          
          <div className="card" style={{ padding: 24, textAlign: 'center' }}>
            <h3 style={{ fontSize: '0.85rem', textTransform: 'uppercase', margin: '0 0 16px', letterSpacing: '0.05em' }}>Time Remaining</h3>
            <div style={{ fontSize: '3rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color: isTimerLow ? 'var(--clr-danger)' : 'var(--clr-text)', lineHeight: 1 }}>
              {String(mins).padStart(2,'0')}:{String(secs).padStart(2,'0')}
            </div>
          </div>

          <div className="card" style={{ padding: 20 }}>
            <h3 style={{ fontSize: '0.85rem', textTransform: 'uppercase', margin: '0 0 16px', letterSpacing: '0.05em' }}>Session Progress</h3>
            
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', marginBottom: 8, fontWeight: 500 }}>
              <span>Questions</span>
              <span>{qNum} / {config.max_questions}</span>
            </div>
            <div style={{ height: 6, background: 'var(--clr-surface-2)', borderRadius: 99, overflow: 'hidden', marginBottom: 20 }}>
              <div style={{ height: '100%', width: `${Math.min(100, ((qNum - 1) / config.max_questions) * 100)}%`, background: 'var(--clr-primary)', transition: 'width 0.5s' }} />
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 0', borderTop: '1px solid var(--clr-border)' }}>
              <span style={{ fontSize: '0.85rem', color: 'var(--clr-text-muted)' }}>Avg Score</span>
              <span style={{ fontWeight: 700, fontSize: '1.1rem', color: 'var(--clr-primary)' }}>-- / 10</span>
            </div>
          </div>

          <div className="card" style={{ padding: 20, flex: 1 }}>
            <h3 style={{ fontSize: '0.85rem', textTransform: 'uppercase', margin: '0 0 12px', letterSpacing: '0.05em', display: 'flex', justifyContent: 'space-between' }}>
              Security Log
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: wsConnected ? 'var(--clr-success)' : 'var(--clr-danger)', alignSelf: 'center' }} />
            </h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {alerts.length === 0 ? (
                <div style={{ color: 'var(--clr-text-muted)', fontSize: '0.8rem', fontStyle: 'italic' }}>Monitoring active...</div>
              ) : (
                alerts.slice(-4).reverse().map((a, i) => (
                  <div key={i} style={{ padding: '8px 10px', borderRadius: 6, background: 'var(--clr-surface-2)', borderLeft: `3px solid ${a.type === 'danger' ? 'var(--clr-danger)' : a.type === 'success' ? 'var(--clr-success)' : 'var(--clr-warning)'}`, fontSize: '0.8rem', color: 'var(--clr-text)' }}>
                    {a.msg}
                  </div>
                ))
              )}
            </div>
          </div>

        </div>
      </div>
    </div>
  )
}
