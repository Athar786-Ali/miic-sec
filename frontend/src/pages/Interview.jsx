import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Editor from '@monaco-editor/react'
import api, { getAuth, clearAuth } from '../utils/api'
import InterviewSetup from './InterviewSetup'

// Derive WebSocket base from the configured API URL.
// In dev: VITE_API_URL is empty → use current window location (Vite proxy handles /ws)
// In Docker: VITE_API_URL = http://localhost:8000 → ws://localhost:8000
const _apiBase = import.meta.env.VITE_API_URL || ''
const WS_BASE = _apiBase
  ? _apiBase.replace(/^https/, 'wss').replace(/^http/, 'ws')
  : `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`

// ── Voice hook (Deepgram Live WebSocket streaming) ─────────────────
const DEEPGRAM_WS_URL =
  'wss://api.deepgram.com/v1/listen?model=nova-2&language=en-IN&smart_format=true&punctuate=true'

function useVoiceInput({ onLiveText, onError }) {
  const [voiceState, setVoiceState] = useState('IDLE') // IDLE, RECORDING, TRANSCRIBING, DONE, ERROR
  const [recSecs, setRecSecs]       = useState(0)

  const mediaRecorderRef = useRef(null)
  const wsRef            = useRef(null)
  const timerRef         = useRef(null)
  const streamRef        = useRef(null)
  const startedAtRef     = useRef(0)
  const stopDelayRef     = useRef(null)
  const dgKeyIdRef       = useRef(null)   // Deepgram temp key_id for revocation
  const dgProjectIdRef   = useRef(null)   // Deepgram project_id for revocation
  const MIN_RECORD_MS    = 800 // avoid opening/closing too fast (needs at least a few chunks)

  const finalTextRef     = useRef('')
  const interimTextRef   = useRef('')

  // Pick best supported MIME type for MediaRecorder
  const getSupportedMime = () => {
    const types = [
      'audio/webm;codecs=opus',
      'audio/webm',
      'audio/ogg;codecs=opus',
      'audio/ogg',
      'audio/mp4',
    ]
    return types.find(t => {
      try { return MediaRecorder.isTypeSupported(t) } catch { return false }
    }) || ''
  }

  const cleanup = () => {
    clearInterval(timerRef.current)
    clearTimeout(stopDelayRef.current)

    try {
      const mr = mediaRecorderRef.current
      if (mr) {
        mr.ondataavailable = null
        mr.onstop = null
        mr.onerror = null
        if (mr.state === 'recording') mr.stop()
      }
    } catch {}
    mediaRecorderRef.current = null

    try {
      const ws = wsRef.current
      if (ws) {
        ws.onopen = null
        ws.onmessage = null
        ws.onerror = null
        ws.onclose = null
        if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) ws.close()
      }
    } catch {}
    wsRef.current = null

    try { streamRef.current?.getTracks().forEach(t => t.stop()) } catch {}
    streamRef.current = null

    finalTextRef.current = ''
    interimTextRef.current = ''
    dgKeyIdRef.current = null
    dgProjectIdRef.current = null
    setRecSecs(0)
  }

  const start = async () => {
    try {
      cleanup()
      setVoiceState('TRANSCRIBING') // connecting

      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error('Your browser does not support microphone access.')
      }

      // Clear UI text for a fresh recording
      finalTextRef.current = ''
      interimTextRef.current = ''
      onLiveText?.('')

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false })
      streamRef.current = stream

      // Fetch a temporary Deepgram key from backend
      const tokenRes = await api.get('/interview/deepgram-token', { timeout: 20000 })
      const token      = tokenRes?.data?.key
      const keyId      = tokenRes?.data?.key_id
      const projectId  = tokenRes?.data?.project_id
      if (!token) throw new Error('Failed to obtain Deepgram token from backend.')

      // Store for later revocation
      dgKeyIdRef.current     = keyId
      dgProjectIdRef.current = projectId

      const ws = new WebSocket(DEEPGRAM_WS_URL, ['token', token])
      wsRef.current = ws

      ws.onmessage = (evt) => {
        let msg = null
        try { msg = JSON.parse(evt.data) } catch { return }
        if (!msg || msg.type !== 'Results') return

        const transcript = msg.channel?.alternatives?.[0]?.transcript || ''
        if (!transcript.trim()) return

        if (msg.is_final) {
          finalTextRef.current = `${finalTextRef.current} ${transcript}`.trim()
          interimTextRef.current = ''
          onLiveText?.(finalTextRef.current)
        } else {
          interimTextRef.current = transcript
          const combined = `${finalTextRef.current} ${interimTextRef.current}`.trim()
          onLiveText?.(combined)
        }
      }

      ws.onerror = () => {
        setVoiceState('ERROR')
        onError?.('Deepgram connection error. Please try again.')
        cleanup()
      }

      ws.onclose = () => {
        clearInterval(timerRef.current)
        const combined = `${finalTextRef.current} ${interimTextRef.current}`.trim()
        setVoiceState(combined ? 'DONE' : 'ERROR')
        if (!combined) onError?.('No speech detected. Please speak clearly and try again.')
        try { stream.getTracks().forEach(t => t.stop()) } catch {}
        streamRef.current = null
        mediaRecorderRef.current = null
        wsRef.current = null
        // Revoke the temp Deepgram key immediately — don't wait for TTL
        const kid = dgKeyIdRef.current
        const pid = dgProjectIdRef.current
        if (kid && pid) {
          api.delete(`/interview/deepgram-token?key_id=${kid}&project_id=${pid}`).catch(() => {})
          dgKeyIdRef.current = null
          dgProjectIdRef.current = null
        }
      }

      ws.onopen = () => {
        const mimeType = getSupportedMime()
        const mr = new MediaRecorder(stream, mimeType ? { mimeType } : {})
        mediaRecorderRef.current = mr

        mr.ondataavailable = (e) => {
          if (!e.data || e.data.size === 0) return
          if (ws.readyState === WebSocket.OPEN) ws.send(e.data)
        }

        mr.onerror = () => {
          setVoiceState('ERROR')
          onError?.('Recording error. Please try again.')
          cleanup()
        }

        // When recording stops, flush results and ask Deepgram to close the stream.
        mr.onstop = () => {
          try {
            if (ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ type: 'CloseStream' }))
            }
          } catch {}

          // If Deepgram doesn't close quickly, force-close after a short grace period.
          setTimeout(() => {
            try { if (ws.readyState === WebSocket.OPEN) ws.close() } catch {}
          }, 3000)
        }

        startedAtRef.current = Date.now()
        mr.start(250) // send chunks every 250ms to Deepgram
        setVoiceState('RECORDING')
        timerRef.current = setInterval(() => setRecSecs(s => s + 1), 1000)
      }
    } catch (err) {
      const msg = err?.name === 'NotAllowedError'
        ? 'Microphone permission denied. Please allow mic access and try again.'
        : (err?.message || 'Could not start voice transcription.')
      setVoiceState('ERROR')
      onError?.(msg)
      cleanup()
    }
  }

  const stop = () => {
    const mr = mediaRecorderRef.current
    if (!mr || mr.state !== 'recording') return

    const elapsed = Date.now() - startedAtRef.current
    if (elapsed < MIN_RECORD_MS) {
      clearTimeout(stopDelayRef.current)
      stopDelayRef.current = setTimeout(() => stop(), MIN_RECORD_MS - elapsed)
      return
    }

    setVoiceState('TRANSCRIBING') // finalizing / waiting for last results
    clearInterval(timerRef.current)
    try { mr.requestData?.() } catch {}
    try { mr.stop() } catch {}
  }

  const reset = () => {
    cleanup()
    setVoiceState('IDLE')
  }

  // Release mic/WS on unmount
  useEffect(() => () => cleanup(), []) // eslint-disable-line

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

// ── Language configs ──────────────────────────────────────────────
const LANG_CONFIG = {
  python: {
    label: 'Python 3',
    monacoId: 'python',
    icon: '🐍',
    defaultCode: `# Write your solution here
# Press Ctrl+Enter or ▶ Run to execute

def solution():
    pass

print(solution())
`,
  },
  javascript: {
    label: 'JavaScript',
    monacoId: 'javascript',
    icon: '🟨',
    defaultCode: `// Write your solution here
// Press Ctrl+Enter or ▶ Run to execute

function solution() {
    
}

console.log(solution());
`,
  },
  java: {
    label: 'Java',
    monacoId: 'java',
    icon: '☕',
    defaultCode: `// Write your solution here
public class Solution {
    public static void main(String[] args) {
        // your code here
    }
}
`,
  },
  cpp: {
    label: 'C++',
    monacoId: 'cpp',
    icon: '⚙️',
    defaultCode: `#include <iostream>
using namespace std;

int main() {
    // your code here
    return 0;
}
`,
  },
}

// ── LeetCode-style Monaco Code Panel ──────────────────────────────
function CodePanel({ templateCode }) {
  const [lang,      setLang]      = useState('python')
  const [fontSize,  setFontSize]  = useState(14)
  const [result,    setResult]    = useState(null)
  const [running,   setRunning]   = useState(false)
  const [activeTab, setActiveTab] = useState('editor') // 'editor' | 'output'
  const [execTime,  setExecTime]  = useState(null)
  const editorRef = useRef(null)

  // code per language, seeded with defaults
  const [codeMap, setCodeMap] = useState(() =>
    Object.fromEntries(Object.entries(LANG_CONFIG).map(([k, v]) => [k, v.defaultCode]))
  )

  // When a DSA template arrives, inject it into current language slot
  useEffect(() => {
    if (templateCode) {
      setCodeMap(prev => ({ ...prev, [lang]: templateCode }))
    }
  }, [templateCode]) // eslint-disable-line

  const currentCode = codeMap[lang] || ''

  const handleEditorChange = (val) => {
    setCodeMap(prev => ({ ...prev, [lang]: val || '' }))
  }

  const handleLangChange = (newLang) => {
    setLang(newLang)
    setResult(null)
  }

  const run = async () => {
    const code = editorRef.current?.getValue() || currentCode
    if (!code.trim()) return
    setRunning(true)
    setResult(null)
    setActiveTab('output')
    const t0 = Date.now()
    try {
      const { data } = await api.post('/interview/execute-code', { code, language: lang })
      setExecTime(Date.now() - t0)
      setResult(data)
    } catch (e) {
      setExecTime(Date.now() - t0)
      setResult({ passed: false, stderr: e.response?.data?.detail || 'Execution error — check backend.' })
    } finally {
      setRunning(false)
    }
  }

  const resetCode = () => {
    const fresh = LANG_CONFIG[lang].defaultCode
    setCodeMap(prev => ({ ...prev, [lang]: fresh }))
    editorRef.current?.setValue(fresh)
    setResult(null)
  }

  // Ctrl+Enter shortcut inside Monaco
  const handleEditorMount = (editor, monaco) => {
    editorRef.current = editor
    editor.addAction({
      id: 'run-code',
      label: 'Run Code',
      keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter],
      run: () => run(),
    })
    // Configure editor settings
    editor.updateOptions({
      fontLigatures: true,
      smoothScrolling: true,
      cursorSmoothCaretAnimation: 'on',
    })
  }

  const cfg = LANG_CONFIG[lang]

  return (
    <div style={{
      marginTop: 24,
      borderRadius: 'var(--r-md)',
      overflow: 'hidden',
      border: '1px solid #3c3c3c',
      background: '#1e1e1e',
      display: 'flex',
      flexDirection: 'column',
      boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
    }}>

      {/* ── Editor toolbar ── */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '8px 12px',
        background: '#252526',
        borderBottom: '1px solid #3c3c3c',
        flexWrap: 'wrap',
      }}>
        {/* Language pills */}
        <div style={{ display: 'flex', gap: 4, marginRight: 8 }}>
          {Object.entries(LANG_CONFIG).map(([k, v]) => (
            <button
              key={k}
              id={`lang-btn-${k}`}
              onClick={() => handleLangChange(k)}
              style={{
                padding: '3px 10px', borderRadius: 4, fontSize: '0.75rem', fontWeight: 600,
                cursor: 'pointer', transition: 'all 0.15s',
                background: lang === k ? '#0e639c' : '#2d2d2d',
                color: lang === k ? '#fff' : '#9d9d9d',
                border: `1px solid ${lang === k ? '#0e639c' : '#3c3c3c'}`,
              }}
            >
              {v.icon} {v.label}
            </button>
          ))}
        </div>

        {/* Spacer */}
        <div style={{ flex: 1 }} />

        {/* Font size */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <button onClick={() => setFontSize(s => Math.max(10, s - 1))} style={{ background: '#2d2d2d', border: '1px solid #3c3c3c', color: '#ccc', borderRadius: 3, padding: '1px 6px', cursor: 'pointer', fontSize: '0.8rem' }}>A-</button>
          <span style={{ fontSize: '0.72rem', color: '#666', minWidth: 20, textAlign: 'center' }}>{fontSize}</span>
          <button onClick={() => setFontSize(s => Math.min(24, s + 1))} style={{ background: '#2d2d2d', border: '1px solid #3c3c3c', color: '#ccc', borderRadius: 3, padding: '1px 6px', cursor: 'pointer', fontSize: '0.8rem' }}>A+</button>
        </div>

        {/* Reset */}
        <button onClick={resetCode} style={{ background: '#2d2d2d', border: '1px solid #3c3c3c', color: '#9d9d9d', borderRadius: 4, padding: '4px 10px', cursor: 'pointer', fontSize: '0.75rem' }}>
          ↺ Reset
        </button>

        {/* Run button */}
        <button
          id="run-code-btn"
          onClick={run}
          disabled={running}
          style={{
            padding: '5px 16px', borderRadius: 4, fontSize: '0.82rem', fontWeight: 700,
            background: running ? '#555' : '#16825d',
            color: '#fff', border: 'none', cursor: running ? 'not-allowed' : 'pointer',
            display: 'flex', alignItems: 'center', gap: 6,
            transition: 'background 0.2s',
          }}
        >
          {running
            ? <><span className="spinner" style={{ width: 12, height: 12, borderWidth: 2 }} /> Running…</>
            : <>▶ Run <span style={{ fontSize: '0.68rem', opacity: 0.7, fontWeight: 400 }}>Ctrl+↵</span></>
          }
        </button>
      </div>

      {/* ── Tab bar: Editor / Output ── */}
      <div style={{ display: 'flex', background: '#252526', borderBottom: '1px solid #3c3c3c' }}>
        {['editor', 'output'].map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            style={{
              padding: '6px 18px', fontSize: '0.78rem', fontWeight: 600,
              background: 'none', border: 'none', cursor: 'pointer',
              color: activeTab === tab ? '#fff' : '#888',
              borderBottom: `2px solid ${activeTab === tab ? '#0e639c' : 'transparent'}`,
              transition: 'all 0.15s', textTransform: 'capitalize',
            }}
          >
            {tab === 'editor' ? '📝 Code' : `🖥 Output${result ? (result.passed ? ' ✓' : ' ✗') : ''}`}
          </button>
        ))}
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: '0.7rem', color: '#555', alignSelf: 'center', paddingRight: 12 }}>
          {cfg.label} · {currentCode.split('\n').length} lines
        </span>
      </div>

      {/* ── Monaco Editor ── */}
      <div style={{ display: activeTab === 'editor' ? 'block' : 'none' }}>
        <Editor
          height="380px"
          language={cfg.monacoId}
          value={currentCode}
          theme="vs-dark"
          onChange={handleEditorChange}
          onMount={handleEditorMount}
          options={{
            fontSize,
            fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', Menlo, monospace",
            fontLigatures: true,
            minimap: { enabled: true, scale: 1 },
            lineNumbers: 'on',
            scrollBeyondLastLine: false,
            automaticLayout: true,
            tabSize: 4,
            wordWrap: 'on',
            renderLineHighlight: 'all',
            bracketPairColorization: { enabled: true },
            guides: { bracketPairs: true, indentation: true },
            smoothScrolling: true,
            cursorBlinking: 'smooth',
            padding: { top: 12, bottom: 12 },
            suggestOnTriggerCharacters: true,
            quickSuggestions: true,
            scrollbar: {
              verticalScrollbarSize: 8,
              horizontalScrollbarSize: 8,
            },
          }}
        />
      </div>

      {/* ── Output Panel ── */}
      <div style={{ display: activeTab === 'output' ? 'flex' : 'none', flexDirection: 'column', minHeight: 380 }}>
        {running ? (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 12, color: '#888' }}>
            <span className="spinner" style={{ width: 28, height: 28, borderWidth: 3, borderColor: '#0e639c', borderTopColor: 'transparent' }} />
            <span style={{ fontSize: '0.85rem' }}>Executing in sandbox…</span>
          </div>
        ) : !result ? (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 8, color: '#555' }}>
            <div style={{ fontSize: '2.5rem' }}>▶</div>
            <div style={{ fontSize: '0.85rem' }}>Press Run or Ctrl+Enter to execute your code</div>
          </div>
        ) : (
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
            {/* Status bar */}
            <div style={{
              display: 'flex', alignItems: 'center', gap: 12, padding: '10px 16px',
              background: result.passed ? 'rgba(22,130,93,0.15)' : 'rgba(205,49,49,0.15)',
              borderBottom: `1px solid ${result.passed ? '#16825d' : '#cd3131'}`,
            }}>
              <span style={{ fontSize: '1.2rem' }}>{result.passed ? '✅' : '❌'}</span>
              <div>
                <div style={{ fontSize: '0.88rem', fontWeight: 700, color: result.passed ? '#4ec9b0' : '#f48771' }}>
                  {result.passed ? 'All Tests Passed' : result.timed_out ? 'Time Limit Exceeded' : 'Runtime Error / Failed'}
                </div>
                <div style={{ fontSize: '0.72rem', color: '#888', marginTop: 2 }}>
                  {execTime != null && `${execTime}ms total`}
                  {result.execution_time_ms != null && ` · ${result.execution_time_ms}ms exec`}
                </div>
              </div>
              {result.static_issues?.length > 0 && (
                <div style={{ marginLeft: 'auto', fontSize: '0.72rem', color: '#cca700', padding: '2px 8px', background: 'rgba(204,167,0,0.1)', borderRadius: 4, border: '1px solid #cca700' }}>
                  ⚠ {result.static_issues.length} security warning{result.static_issues.length > 1 ? 's' : ''}
                </div>
              )}
            </div>

            {/* stdout */}
            {result.stdout && (
              <div style={{ padding: '12px 16px', borderBottom: '1px solid #3c3c3c' }}>
                <div style={{ fontSize: '0.7rem', color: '#888', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>stdout</div>
                <pre style={{ margin: 0, fontFamily: "'JetBrains Mono', monospace", fontSize: '0.85rem', color: '#d4d4d4', whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>{result.stdout}</pre>
              </div>
            )}

            {/* stderr */}
            {result.stderr && (
              <div style={{ padding: '12px 16px', borderBottom: '1px solid #3c3c3c' }}>
                <div style={{ fontSize: '0.7rem', color: '#f48771', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>stderr / error</div>
                <pre style={{ margin: 0, fontFamily: "'JetBrains Mono', monospace", fontSize: '0.85rem', color: '#f48771', whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>{result.stderr}</pre>
              </div>
            )}

            {/* Static issues */}
            {result.static_issues?.length > 0 && (
              <div style={{ padding: '12px 16px' }}>
                <div style={{ fontSize: '0.7rem', color: '#cca700', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>security analysis</div>
                {result.static_issues.map((iss, i) => (
                  <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', marginBottom: 6 }}>
                    <span style={{ color: iss.severity === 'HIGH' ? '#f48771' : '#cca700', fontSize: '0.75rem', fontWeight: 700, flexShrink: 0 }}>[{iss.severity}]</span>
                    <span style={{ fontSize: '0.82rem', color: '#ccc' }}>{iss.message || iss}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Status bar (VS Code style) ── */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '3px 12px',
        background: '#007acc',
        fontSize: '0.7rem', color: 'rgba(255,255,255,0.85)',
      }}>
        <span>{cfg.icon} {cfg.label}</span>
        <span style={{ display: 'flex', gap: 16 }}>
          <span>UTF-8</span>
          <span>Tab Size: 4</span>
          <span>MIIC-Sec Sandbox</span>
        </span>
      </div>
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
  const [whatGood,    setWhatGood]    = useState('')   // Phase 4
  const [improveTip,  setImproveTip]  = useState('')   // Phase 4
  const [hint,        setHint]        = useState('')   // Phase 3
  const [hintLoading, setHintLoading] = useState(false)
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
    onLiveText: useCallback(text => {
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
    const onVis = async () => {
      if (document.hidden && config) {
        pushAlert('⚠️ Tab switch detected', 'warning')
        // Notify backend — counter triggers warning/terminate logic
        try {
          const res = await api.post('/security/tab-switch', {
            timestamp: new Date().toISOString(),
          })
          if (res.data?.terminated) {
            // Backend terminated — WS will push SESSION_TERMINATED event
            pushAlert('🚨 Session terminated due to excessive tab switches', 'danger')
          }
        } catch { /* silently ignore network errors */ }
      }
    }
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
      setWhatGood(data.what_was_good || '')   // Phase 4
      setImproveTip(data.improve_tip || '')   // Phase 4
      setHint('')                             // Phase 3: clear hint after submit
      setDifficulty(data.difficulty); setQNum(data.question_number)
      setAnswer('')
      resetVoice()
      
      if (data.auto_end) { handleEnd() }
      else {
        updateQuestionAndTemplate(data.next_question)
        setTimeout(() => { setScore(null); setFeedback(''); setWhatGood(''); setImproveTip('') }, 6000)
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

            {/* Score feedback overlay — Phase 4 coaching tone */}
            {score != null && (
              <div style={{ marginBottom: 20 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                  <span style={{
                    padding: '4px 12px', borderRadius: 20, fontWeight: 700, fontSize: '0.85rem',
                    background: score >= 7 ? 'rgba(34,197,94,0.15)' : score >= 5 ? 'rgba(245,158,11,0.15)' : 'rgba(239,68,68,0.15)',
                    color: score >= 7 ? 'var(--clr-success)' : score >= 5 ? 'var(--clr-warning)' : 'var(--clr-danger)',
                    border: `1px solid ${score >= 7 ? 'var(--clr-success)' : score >= 5 ? 'var(--clr-warning)' : 'var(--clr-danger)'}`,
                  }}>
                    {score}/10
                  </span>
                  <span style={{ fontSize: '0.8rem', color: 'var(--clr-text-muted)' }}>Answer score</span>
                </div>
                {whatGood && (
                  <div className="feedback-card good">
                    <div style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--clr-success)', marginBottom: 4 }}>✅ What was good</div>
                    <div style={{ fontSize: '0.87rem', lineHeight: 1.5 }}>{whatGood}</div>
                  </div>
                )}
                {improveTip && (
                  <div className="feedback-card improve">
                    <div style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--clr-warning)', marginBottom: 4 }}>💡 Next time try</div>
                    <div style={{ fontSize: '0.87rem', lineHeight: 1.5 }}>{improveTip}</div>
                  </div>
                )}
                {!whatGood && feedback && (
                  <div className="feedback-card">
                    <div style={{ fontSize: '0.87rem', lineHeight: 1.5 }}>{feedback}</div>
                  </div>
                )}
              </div>
            )}

            {/* Phase 3: Hint button — practice mode only */}
            {config?.pressure_mode !== 'simulated' && !score && question && (
              <div style={{ marginBottom: 12 }}>
                {hint ? (
                  <div className="feedback-card" style={{ borderColor: 'rgba(99,102,241,0.4)', background: 'rgba(99,102,241,0.07)' }}>
                    <div style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--clr-primary)', marginBottom: 4 }}>💭 Hint</div>
                    <div style={{ fontSize: '0.87rem', lineHeight: 1.5 }}>{hint}</div>
                    <button onClick={() => setHint('')} style={{ marginTop: 6, background: 'none', border: 'none', color: 'var(--clr-text-muted)', cursor: 'pointer', fontSize: '0.78rem' }}>Dismiss</button>
                  </div>
                ) : (
                  <button
                    className="btn btn-ghost"
                    style={{ fontSize: '0.78rem', padding: '5px 12px' }}
                    disabled={hintLoading}
                    onClick={async () => {
                      setHintLoading(true)
                      try {
                        const { data } = await api.post('/interview/hint', { question_text: question, candidate_response: answer })
                        setHint(data.hint)
                      } catch { setHint('Hint: Break the problem into smaller steps and think about which data structure fits best.') }
                      finally { setHintLoading(false) }
                    }}
                  >
                    {hintLoading ? <><span className="spinner" style={{ width: 12, height: 12 }} /> Getting hint…</> : '💭 Need a hint?'}
                  </button>
                )}
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
                  {voiceState === 'TRANSCRIBING'&& '⏳ Connecting / finalizing live transcription…'}
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
                  {answer
                    ? <span style={{ color: 'var(--clr-text)' }}>{answer}</span>
                    : voiceState === 'TRANSCRIBING'
                      ? <span style={{ color: 'var(--clr-text-muted)', fontStyle: 'italic' }}>Connecting to live transcription…</span>
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
            
            {/* If DSA Question, show Monaco Editor */}
            {isDsa && (
              <div style={{ marginTop: 32 }}>
                <div className="divider" style={{ margin: '0 0 16px' }} />
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
                  <span style={{ fontSize: '1.1rem' }}>💻</span>
                  <h3 style={{ margin: 0, color: 'var(--clr-primary)', fontSize: '1rem' }}>Coding Exercise</h3>
                  <span style={{ fontSize: '0.72rem', padding: '2px 8px', background: 'rgba(99,102,241,0.15)', borderRadius: 20, color: 'var(--clr-primary)', border: '1px solid rgba(99,102,241,0.3)' }}>Monaco Editor</span>
                </div>
                <p style={{ color: 'var(--clr-text-muted)', fontSize: '0.85rem', marginBottom: 0 }}>
                  Implement the function below. Use the voice/text input above to explain your approach before submitting.
                </p>
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
