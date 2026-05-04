import React, { useEffect, useRef, useState } from 'react'
import api from '../utils/api'

const MODES = [
  { id: 'topic',    icon: '📚', label: 'Topic Based',  desc: 'Select CS topics for your interview' },
  { id: 'resume',   icon: '📄', label: 'Resume Based', desc: 'Questions from your PDF resume' },
  { id: 'combined', icon: '🔗', label: 'Combined',     desc: 'Resume + selected topics together' },
]

export default function InterviewSetup({ onStart }) {
  const [mode,       setMode]       = useState('topic')
  const [topics,     setTopics]     = useState([])
  const [selected,   setSelected]   = useState([])
  const [jobRole,    setJobRole]    = useState('Software Engineering')
  const [maxQ,       setMaxQ]       = useState(10)
  const [timeLimit,  setTimeLimit]  = useState(20)
  const [resumeCtx,  setResumeCtx]  = useState('')
  const [resumeInfo, setResumeInfo] = useState(null)
  const [uploading,  setUploading]  = useState(false)
  const [loading,    setLoading]    = useState(false)
  const [error,      setError]      = useState('')
  const fileRef = useRef()

  useEffect(() => {
    api.get('/interview/topics')
      .then(r => setTopics(r.data.topics))
      .catch(() => {})
  }, [])

  const toggleTopic = id =>
    setSelected(s => s.includes(id) ? s.filter(x => x !== id) : [...s, id])

  const handleResume = async e => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true); setError('')
    try {
      const fd = new FormData()
      fd.append('resume_pdf', file)
      const { data } = await api.post('/interview/upload-resume', fd)
      setResumeCtx(data.resume_context)
      setResumeInfo(data)
    } catch (err) {
      setError(err.response?.data?.detail || 'Resume upload failed.')
    } finally { setUploading(false) }
    // reset so same file can be re-selected
    e.target.value = ''
  }

  const canStart = () => {
    if (mode === 'topic')    return selected.length > 0
    if (mode === 'resume')   return !!resumeCtx
    if (mode === 'combined') return selected.length > 0 && !!resumeCtx
    return false
  }

  const handleStart = async () => {
    if (!canStart() || loading) return
    setLoading(true); setError('')
    try {
      const fd = new FormData()
      fd.append('job_role',           jobRole.trim() || 'Software Engineering')
      fd.append('max_questions',      String(maxQ))
      fd.append('time_limit_minutes', String(timeLimit))
      fd.append('interview_mode',     mode)
      fd.append('selected_topics',    JSON.stringify(selected))
      fd.append('resume_context',     resumeCtx)
      const { data } = await api.post('/interview/start', fd)
      onStart(data)
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not start interview.')
    } finally { setLoading(false) }
  }

  const needsTopics = mode === 'topic' || mode === 'combined'
  const needsResume = mode === 'resume' || mode === 'combined'

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'flex-start', justifyContent: 'center', padding: '32px 16px 64px' }}>
      <div style={{ width: '100%', maxWidth: 620 }}>

        {/* Header */}
        <div className="page-header" style={{ justifyContent: 'center', marginBottom: 24 }}>
          <div className="logo-mark">🛡</div>
          <h1>Interview Setup</h1>
        </div>

        {error && (
          <div className="alert alert-danger" style={{ marginBottom: 20 }}>{error}</div>
        )}

        {/* ── Mode selector ── */}
        <div className="card" style={{ marginBottom: 16 }}>
          <h3 style={{ margin: '0 0 14px', fontSize: '0.88rem', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--clr-text-muted)' }}>
            Interview Mode
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {MODES.map(m => (
              <div
                key={m.id}
                onClick={() => setMode(m.id)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 14, padding: '12px 16px',
                  borderRadius: 'var(--r-sm)', cursor: 'pointer',
                  border: `2px solid ${mode === m.id ? 'var(--clr-primary)' : 'var(--clr-border)'}`,
                  background: mode === m.id ? 'rgba(99,102,241,0.1)' : 'var(--clr-surface-2)',
                  transition: 'all 0.18s',
                }}
              >
                <span style={{ fontSize: '1.5rem', flexShrink: 0 }}>{m.icon}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 700, fontSize: '0.95rem', marginBottom: 2 }}>{m.label}</div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--clr-text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{m.desc}</div>
                </div>
                <div style={{
                  width: 18, height: 18, borderRadius: '50%', flexShrink: 0,
                  border: `2px solid ${mode === m.id ? 'var(--clr-primary)' : 'var(--clr-border)'}`,
                  background: mode === m.id ? 'var(--clr-primary)' : 'transparent',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.7rem', color: '#fff',
                }}>
                  {mode === m.id && '✓'}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* ── Topic selector ── */}
        {needsTopics && (
          <div className="card" style={{ marginBottom: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
              <h3 style={{ margin: 0, fontSize: '0.88rem', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--clr-text-muted)' }}>
                Select Topics
              </h3>
              {selected.length > 0 && (
                <span className="badge badge-easy">{selected.length} selected</span>
              )}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 8 }}>
              {topics.map(t => {
                const isSelected = selected.includes(t.id)
                return (
                  <div
                    key={t.id}
                    onClick={() => toggleTopic(t.id)}
                    style={{
                      padding: '10px 12px', borderRadius: 'var(--r-sm)', cursor: 'pointer',
                      border: `2px solid ${isSelected ? 'var(--clr-primary)' : 'var(--clr-border)'}`,
                      background: isSelected ? 'rgba(99,102,241,0.12)' : 'var(--clr-surface-2)',
                      transition: 'all 0.15s',
                    }}
                  >
                    <div style={{ fontWeight: 600, fontSize: '0.82rem', marginBottom: 3, lineHeight: 1.3 }}>{t.name}</div>
                    <div style={{ fontSize: '0.7rem', color: 'var(--clr-text-muted)' }}>{t.subtopic_count} subtopics</div>
                    {isSelected && <div style={{ fontSize: '0.72rem', color: 'var(--clr-primary)', marginTop: 4, fontWeight: 700 }}>✓ Selected</div>}
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* ── Resume upload ── */}
        {needsResume && (
          <div className="card" style={{ marginBottom: 16 }}>
            <h3 style={{ margin: '0 0 14px', fontSize: '0.88rem', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--clr-text-muted)' }}>
              Upload Resume (PDF)
            </h3>
            <div
              onClick={() => !uploading && fileRef.current?.click()}
              style={{
                border: `2px dashed ${resumeCtx ? 'var(--clr-success)' : 'var(--clr-border)'}`,
                borderRadius: 'var(--r-sm)', padding: 28, textAlign: 'center',
                cursor: uploading ? 'wait' : 'pointer',
                background: 'var(--clr-surface-2)', transition: 'border-color 0.2s',
              }}
            >
              {uploading ? (
                <><span className="spinner" style={{ marginRight: 8 }} />Parsing resume…</>
              ) : resumeInfo ? (
                <>
                  <div style={{ fontSize: '1.6rem', marginBottom: 6 }}>✅</div>
                  <div style={{ fontWeight: 700, color: 'var(--clr-success)', marginBottom: 6 }}>Resume Parsed</div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--clr-text-muted)', marginBottom: 4 }}>
                    {['skills', 'experience', 'projects', 'education']
                      .filter(k => resumeInfo.section_counts?.[k] > 0)
                      .map(k => `${k} (${resumeInfo.section_counts[k]})`)
                      .join('  ·  ')}
                  </div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--clr-text-muted)' }}>{resumeInfo.word_count} words · click to replace</div>
                </>
              ) : (
                <>
                  <div style={{ fontSize: '2rem', marginBottom: 8 }}>📄</div>
                  <div style={{ fontWeight: 600, marginBottom: 4 }}>Click to upload PDF</div>
                  <div style={{ fontSize: '0.78rem', color: 'var(--clr-text-muted)' }}>Max 5 MB · text-based PDFs only</div>
                </>
              )}
            </div>
            <input ref={fileRef} type="file" accept=".pdf" style={{ display: 'none' }} onChange={handleResume} />
          </div>
        )}

        {/* ── Config: Job role + sliders ── */}
        <div className="card" style={{ marginBottom: 16 }}>
          <h3 style={{ margin: '0 0 14px', fontSize: '0.88rem', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--clr-text-muted)' }}>
            Interview Settings
          </h3>

          <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--clr-text-muted)', marginBottom: 6 }}>Job Role</label>
          <input
            className="input"
            value={jobRole}
            onChange={e => setJobRole(e.target.value)}
            placeholder="e.g. Software Engineer, ML Engineer"
            style={{ marginBottom: 18 }}
          />

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <label style={{ fontSize: '0.8rem', color: 'var(--clr-text-muted)' }}>Questions</label>
                <span style={{ fontWeight: 700, color: 'var(--clr-primary)', fontSize: '0.9rem' }}>{maxQ}</span>
              </div>
              <input type="range" min={5} max={20} value={maxQ}
                onChange={e => setMaxQ(+e.target.value)} style={{ width: '100%' }} />
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'var(--clr-text-muted)', marginTop: 4 }}>
                <span>5</span><span>20</span>
              </div>
            </div>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <label style={{ fontSize: '0.8rem', color: 'var(--clr-text-muted)' }}>Time Limit</label>
                <span style={{ fontWeight: 700, color: 'var(--clr-primary)', fontSize: '0.9rem' }}>{timeLimit} min</span>
              </div>
              <input type="range" min={10} max={60} step={5} value={timeLimit}
                onChange={e => setTimeLimit(+e.target.value)} style={{ width: '100%' }} />
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'var(--clr-text-muted)', marginTop: 4 }}>
                <span>10m</span><span>60m</span>
              </div>
            </div>
          </div>
        </div>

        {/* ── Start button ── */}
        {!canStart() && (
          <div style={{ fontSize: '0.82rem', color: 'var(--clr-text-muted)', textAlign: 'center', marginBottom: 10 }}>
            {mode === 'topic' && selected.length === 0 && '⬆ Select at least one topic to continue'}
            {mode === 'resume' && !resumeCtx && '⬆ Upload your resume to continue'}
            {mode === 'combined' && !resumeCtx && '⬆ Upload your resume'}
            {mode === 'combined' && resumeCtx && selected.length === 0 && '⬆ Select at least one topic'}
          </div>
        )}
        <button
          className="btn btn-primary"
          style={{ width: '100%', padding: '14px', fontSize: '1rem', fontWeight: 700 }}
          disabled={!canStart() || loading}
          onClick={handleStart}
        >
          {loading
            ? <><span className="spinner" style={{ marginRight: 8 }} />Starting interview…</>
            : '▶ Start Interview'}
        </button>
      </div>
    </div>
  )
}
