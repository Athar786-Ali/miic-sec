/**
 * Dashboard.jsx — Student Career Accelerator Dashboard
 * Route: /dashboard (ProtectedRoute)
 *
 * Sections:
 *   - Welcome header with candidate name + ID + stats pills
 *   - Score-over-time line graph (recharts)
 *   - Interview history table (click row → /report/:sessionId)
 *   - "Start New Mock Interview" CTA
 */
import React, { useEffect, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Area, AreaChart,
  RadarChart, Radar, PolarGrid, PolarAngleAxis,
} from 'recharts'
import api, { getAuth, clearAuth } from '../utils/api'

// ─── Helpers ──────────────────────────────────────────────────────────────────
const REC_COLORS = {
  EXCELLENT:       { bg: 'rgba(16,185,129,0.15)', border: 'var(--clr-success)', text: 'var(--clr-success)' },
  'NEEDS PRACTICE':{ bg: 'rgba(245,158,11,0.15)', border: 'var(--clr-warning)', text: 'var(--clr-warning)' },
  POOR:            { bg: 'rgba(239,68,68,0.15)',  border: 'var(--clr-danger)',  text: 'var(--clr-danger)'  },
}

function RecPill({ rec }) {
  const c = REC_COLORS[rec] || REC_COLORS['NEEDS PRACTICE']
  return (
    <span style={{
      display: 'inline-block', padding: '3px 10px', borderRadius: 20,
      fontSize: '0.72rem', fontWeight: 700, letterSpacing: '0.05em',
      background: c.bg, border: `1px solid ${c.border}`, color: c.text,
    }}>
      {rec}
    </span>
  )
}

function StatCard({ icon, label, value, sub, color }) {
  return (
    <div style={{
      background: 'var(--clr-surface)', border: '1px solid var(--clr-border)',
      borderRadius: 'var(--r-md)', padding: '20px 24px',
      backdropFilter: 'blur(12px)',
      transition: 'transform 0.18s, border-color 0.18s',
    }}
      onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.borderColor = color || 'var(--clr-primary)' }}
      onMouseLeave={e => { e.currentTarget.style.transform = ''; e.currentTarget.style.borderColor = 'var(--clr-border)' }}
    >
      <div style={{ fontSize: '1.6rem', marginBottom: 8 }}>{icon}</div>
      <div style={{ fontSize: '2rem', fontWeight: 800, fontFamily: 'var(--font-mono)', color: color || 'var(--clr-primary)', lineHeight: 1 }}>
        {value}
      </div>
      <div style={{ fontSize: '0.8rem', fontWeight: 600, marginTop: 6, color: 'var(--clr-text)' }}>{label}</div>
      {sub && <div style={{ fontSize: '0.72rem', color: 'var(--clr-text-muted)', marginTop: 3 }}>{sub}</div>}
    </div>
  )
}

const COMPANY_LABELS = {
  service:  '🏢 Service Based',
  product:  '🚀 Product / FAANG',
  startup:  '⚡ Startup',
  '':       '—',
}

// ─── Main Dashboard ───────────────────────────────────────────────────────────
export default function Dashboard() {
  const navigate  = useNavigate()
  const [data,      setData]      = useState(null)
  const [progress,  setProgress]  = useState(null)   // Phase 2
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState('')
  const [walkDone,  setWalkDone]  = useState(() =>    // Phase 6
    localStorage.getItem('miic_walkthrough_dismissed') === '1'
  )
  const [pdfLoading, setPdfLoading] = useState(false)  // Phase 5

  useEffect(() => {
    Promise.all([
      api.get('/user/dashboard'),
      api.get('/user/progress'),
    ])
      .then(([dash, prog]) => { setData(dash.data); setProgress(prog.data) })
      .catch(e => setError(e.response?.data?.detail || 'Could not load dashboard.'))
      .finally(() => setLoading(false))
  }, [])

  const handleLogout = () => { clearAuth(); navigate('/signup', { replace: true }) }

  // Phase 5: Download growth PDF
  const handleGrowthPdf = async () => {
    setPdfLoading(true)
    try {
      const resp = await api.get('/user/progress/pdf', { responseType: 'blob' })
      const url  = URL.createObjectURL(resp.data)
      const a    = document.createElement('a'); a.href = url; a.download = 'miic_growth_report.pdf'; a.click()
      URL.revokeObjectURL(url)
    } catch { /* silently fail */ }
    finally { setPdfLoading(false) }
  }

  if (loading) return (
    <div className="page-center">
      <span className="spinner" style={{ width: 40, height: 40 }} />
    </div>
  )

  if (error) return (
    <div className="page-center">
      <div className="card" style={{ maxWidth: 420, textAlign: 'center' }}>
        <div style={{ fontSize: '3rem', marginBottom: 12 }}>😕</div>
        <h2 style={{ color: 'var(--clr-danger)' }}>Dashboard Error</h2>
        <p style={{ color: 'var(--clr-text-muted)', marginBottom: 20 }}>{error}</p>
        <Link to="/signup" className="btn btn-ghost">← Back to Login</Link>
      </div>
    </div>
  )

  const { candidate, stats, sessions, streak_days = 0 } = data

  // Build chart data — chronological (oldest first)
  const chartData = [...sessions]
    .reverse()
    .map((s, i) => ({
      n:     i + 1,
      score: parseFloat((s.final_score || 0).toFixed(1)),
      date:  s.date ? new Date(s.date).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) : `#${i + 1}`,
    }))

  return (
    <div style={{ minHeight: '100vh', padding: '0 0 64px' }}>

      {/* ── Top nav bar ── */}
      <nav style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '14px 32px',
        background: 'var(--clr-surface)', borderBottom: '1px solid var(--clr-border)',
        backdropFilter: 'blur(16px)', position: 'sticky', top: 0, zIndex: 100,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div className="logo-mark" style={{ fontSize: '1.4rem' }}>🛡</div>
          <span style={{ fontWeight: 800, fontSize: '1.05rem', letterSpacing: '-0.01em' }}>MIIC-Sec</span>
          <span style={{
            marginLeft: 8, fontSize: '0.7rem', padding: '2px 8px',
            borderRadius: 20, background: 'rgba(99,102,241,0.15)',
            color: 'var(--clr-primary)', fontWeight: 700, letterSpacing: '0.06em',
          }}>CAREER ACCELERATOR</span>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <button
            className="btn btn-primary"
            onClick={() => navigate('/interview')}
            style={{ padding: '8px 18px', fontSize: '0.85rem' }}
          >
            ▶ New Mock Interview
          </button>
          <button className="btn btn-ghost" onClick={handleLogout} style={{ padding: '8px 14px', fontSize: '0.85rem' }}>
            Logout
          </button>
        </div>
      </nav>

      <div style={{ maxWidth: 1100, margin: '0 auto', padding: '32px 24px' }}>

        {/* ── Welcome header ── */}
        <div style={{ marginBottom: 32 }}>
          <h1 style={{ fontSize: '1.9rem', fontWeight: 800, marginBottom: 4 }}>
            Hey, {candidate.name.split(' ')[0]} 👋
          </h1>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
            <span style={{ fontSize: '0.78rem', color: 'var(--clr-text-muted)', fontFamily: 'var(--font-mono)' }}>
              ID: {candidate.id}
            </span>
            <span style={{ fontSize: '0.78rem', color: 'var(--clr-text-muted)' }}>·</span>
            <span style={{ fontSize: '0.78rem', color: 'var(--clr-text-muted)' }}>
              {candidate.email}
            </span>
            <span style={{ fontSize: '0.78rem', color: 'var(--clr-text-muted)' }}>·</span>
            <span style={{ fontSize: '0.78rem', color: 'var(--clr-text-muted)' }}>
              Member since {candidate.member_since ? new Date(candidate.member_since).toLocaleDateString('en-IN', { month: 'long', year: 'numeric' }) : '—'}
            </span>
          </div>
        </div>

        {/* ── Stats row ── */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 16, marginBottom: 32 }}>
          <StatCard icon="🎯" label="Total Interviews"     value={stats.total_interviews}           sub="completed sessions"         color="var(--clr-primary)" />
          <StatCard icon="📊" label="Average Score"        value={`${stats.average_score}/10`}      sub="across all sessions"        color="var(--clr-accent)"  />
          <StatCard icon="🏆" label="Personal Best"        value={`${stats.best_score}/10`}         sub="highest single score"       color="var(--clr-success)" />
          <StatCard icon="📅" label="This Month"           value={stats.interviews_this_month}       sub="mock interviews taken"      color="var(--clr-warning)" />
          <StatCard icon="🔥" label="Practice Streak"      value={`${streak_days}d`}                  sub={streak_days > 0 ? 'days in a row!' : 'start today!'} color="var(--clr-danger)" />
        </div>

        {/* ── Phase 6: First-time walkthrough card ── */}
        {!walkDone && (
          <div className="card" style={{ marginBottom: 24, background: 'rgba(99,102,241,0.08)', borderColor: 'var(--clr-primary)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
              <div>
                <h3 style={{ margin: '0 0 8px', color: 'var(--clr-primary)' }}>👋 Welcome to MIIC-Sec!</h3>
                <p style={{ margin: '0 0 12px', fontSize: '0.88rem', color: 'var(--clr-text-muted)', lineHeight: 1.6 }}>
                  This is your personal interview practice hub. Here's how to get started:
                </p>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                  {[
                    { n: '1', t: 'Pick Just Practice or Simulate Real Pressure mode' },
                    { n: '2', t: 'Choose your topics and company target' },
                    { n: '3', t: 'Answer questions and get instant coaching feedback' },
                    { n: '4', t: 'Track your progress here over time' },
                  ].map(step => (
                    <div key={step.n} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.82rem', color: 'var(--clr-text)' }}>
                      <span style={{ background: 'var(--clr-primary)', color: '#fff', borderRadius: '50%', width: 20, height: 20, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.7rem', fontWeight: 700, flexShrink: 0 }}>{step.n}</span>
                      {step.t}
                    </div>
                  ))}
                </div>
              </div>
              <button
                onClick={() => { localStorage.setItem('miic_walkthrough_dismissed', '1'); setWalkDone(true) }}
                style={{ background: 'none', border: 'none', color: 'var(--clr-text-muted)', cursor: 'pointer', fontSize: '1.2rem', flexShrink: 0 }}
                title="Dismiss"
              >✕</button>
            </div>
          </div>
        )}

        {/* ── Score growth chart ── */}
        {chartData.length > 0 ? (
          <div className="card" style={{ marginBottom: 24 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h2 style={{ margin: 0, fontSize: '1.05rem' }}>📈 Score Progress</h2>
              <span style={{ fontSize: '0.75rem', color: 'var(--clr-text-muted)' }}>
                {chartData.length} interview{chartData.length !== 1 ? 's' : ''}
              </span>
            </div>
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={chartData} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="scoreGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="var(--clr-primary)" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="var(--clr-primary)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(99,119,179,0.1)" />
                <XAxis dataKey="date" tick={{ fontSize: 11, fill: 'var(--clr-text-muted)' }} />
                <YAxis domain={[0, 10]} tick={{ fontSize: 11, fill: 'var(--clr-text-muted)' }} />
                <Tooltip
                  contentStyle={{ background: 'var(--clr-surface-2)', border: '1px solid var(--clr-border)', borderRadius: 8, fontSize: 12 }}
                  formatter={v => [`${v}/10`, 'Score']}
                />
                <Area
                  type="monotone" dataKey="score"
                  stroke="var(--clr-primary)" strokeWidth={2.5}
                  fill="url(#scoreGrad)" dot={{ r: 4, fill: 'var(--clr-primary)', strokeWidth: 0 }}
                  activeDot={{ r: 6 }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="card" style={{ marginBottom: 24, textAlign: 'center', padding: '40px 24px' }}>
            <div style={{ fontSize: '3rem', marginBottom: 12 }}>🎯</div>
            <h3 style={{ marginBottom: 8 }}>No interviews yet</h3>
            <p style={{ color: 'var(--clr-text-muted)', marginBottom: 20 }}>
              Start your first mock interview to see your score progress chart here.
            </p>
            <button className="btn btn-primary" onClick={() => navigate('/interview')}>
              ▶ Start Your First Interview
            </button>
          </div>
        )}

        {/* ── Phase 2: Topic progress radar + focus areas ── */}
        {progress && progress.topics && progress.topics.length > 0 && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 20, marginBottom: 24 }}>

            {/* Radar chart */}
            <div className="card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                <h2 style={{ margin: 0, fontSize: '1.05rem' }}>🕸️ Your Growth</h2>
                <button
                  onClick={handleGrowthPdf}
                  disabled={pdfLoading}
                  className="btn btn-ghost"
                  style={{ fontSize: '0.75rem', padding: '5px 10px' }}
                >
                  {pdfLoading ? <><span className="spinner" style={{ width: 12, height: 12 }} /> Generating…</> : '📊 Download PDF'}
                </button>
              </div>
              <ResponsiveContainer width="100%" height={220}>
                <RadarChart data={progress.topics.map(t => ({ topic: t.topic, score: t.avg_score }))}>
                  <PolarGrid stroke="rgba(99,119,179,0.2)" />
                  <PolarAngleAxis dataKey="topic" tick={{ fontSize: 11, fill: 'var(--clr-text-muted)' }} />
                  <Radar name="Score" dataKey="score" stroke="var(--clr-primary)" fill="var(--clr-primary)" fillOpacity={0.2} dot={{ r: 3 }} />
                  <Tooltip
                    contentStyle={{ background: 'var(--clr-surface-2)', border: '1px solid var(--clr-border)', borderRadius: 8, fontSize: 12 }}
                    formatter={v => [`${v.toFixed(1)}/10`, 'Avg Score']}
                  />
                </RadarChart>
              </ResponsiveContainer>
            </div>

            {/* Focus areas + improved topics */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {progress.weak_topics && progress.weak_topics.length > 0 && (
                <div className="card" style={{ flex: 1 }}>
                  <h3 style={{ margin: '0 0 12px', fontSize: '0.95rem', color: 'var(--clr-warning)' }}>🎯 Focus Areas</h3>
                  {progress.weak_topics.map(t => (
                    <div key={t.topic} style={{ marginBottom: 10 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3, fontSize: '0.85rem' }}>
                        <span style={{ fontWeight: 600 }}>{t.topic}</span>
                        <span style={{ color: 'var(--clr-warning)' }}>{t.avg_score.toFixed(1)}/10</span>
                      </div>
                      <p style={{ margin: 0, fontSize: '0.78rem', color: 'var(--clr-text-muted)', lineHeight: 1.4 }}>
                        💡 {t.tip}
                      </p>
                    </div>
                  ))}
                </div>
              )}
              {progress.improved_topics && progress.improved_topics.length > 0 && (
                <div className="card" style={{ background: 'rgba(34,197,94,0.06)', borderColor: 'rgba(34,197,94,0.3)' }}>
                  <h3 style={{ margin: '0 0 8px', fontSize: '0.9rem', color: 'var(--clr-success)' }}>⬆️ You've Improved In</h3>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                    {progress.improved_topics.map(t => (
                      <span key={t} style={{ background: 'rgba(34,197,94,0.15)', border: '1px solid var(--clr-success)', color: 'var(--clr-success)', borderRadius: 20, padding: '3px 10px', fontSize: '0.78rem', fontWeight: 600 }}>
                        {t} ↑
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── Interview history table ── */}
        {sessions.length > 0 && (
          <div className="card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h2 style={{ margin: 0, fontSize: '1.05rem' }}>📋 Interview History</h2>
              <span style={{ fontSize: '0.75rem', color: 'var(--clr-text-muted)' }}>
                Click any row to view full report
              </span>
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%' }}>
                <thead>
                  <tr>
                    <th style={{ textAlign: 'left', fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--clr-text-muted)', padding: '8px 12px', fontWeight: 600 }}>Date</th>
                    <th style={{ textAlign: 'left', fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--clr-text-muted)', padding: '8px 12px', fontWeight: 600 }}>Role</th>
                    <th style={{ textAlign: 'left', fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--clr-text-muted)', padding: '8px 12px', fontWeight: 600 }}>Target</th>
                    <th style={{ textAlign: 'left', fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--clr-text-muted)', padding: '8px 12px', fontWeight: 600 }}>Mode</th>
                    <th style={{ textAlign: 'center', fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--clr-text-muted)', padding: '8px 12px', fontWeight: 600 }}>Qs</th>
                    <th style={{ textAlign: 'center', fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--clr-text-muted)', padding: '8px 12px', fontWeight: 600 }}>Score</th>
                    <th style={{ textAlign: 'left', fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--clr-text-muted)', padding: '8px 12px', fontWeight: 600 }}>Result</th>
                  </tr>
                </thead>
                <tbody>
                  {sessions.map((s, i) => (
                    <tr
                      key={s.session_id}
                      onClick={() => navigate(`/report/${s.session_id}`)}
                      style={{
                        cursor: 'pointer',
                        transition: 'background 0.14s',
                        borderTop: '1px solid var(--clr-border)',
                      }}
                      onMouseEnter={e => e.currentTarget.style.background = 'var(--clr-surface-2)'}
                      onMouseLeave={e => e.currentTarget.style.background = ''}
                    >
                      <td style={{ padding: '12px 12px', fontSize: '0.82rem', color: 'var(--clr-text-muted)', whiteSpace: 'nowrap' }}>
                        {s.date ? new Date(s.date).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : '—'}
                      </td>
                      <td style={{ padding: '12px 12px', fontSize: '0.85rem', fontWeight: 600, maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {s.job_role || 'Software Engineering'}
                      </td>
                      <td style={{ padding: '12px 12px', fontSize: '0.78rem', color: 'var(--clr-text-muted)' }}>
                        {COMPANY_LABELS[s.company_target] || '—'}
                      </td>
                      <td style={{ padding: '12px 12px' }}>
                        <span style={{
                          fontSize: '0.72rem', padding: '2px 8px', borderRadius: 20,
                          background: 'var(--clr-surface-2)', border: '1px solid var(--clr-border)',
                          textTransform: 'capitalize',
                        }}>
                          {s.interview_mode}
                        </span>
                      </td>
                      <td style={{ padding: '12px 12px', textAlign: 'center', fontSize: '0.82rem', color: 'var(--clr-text-muted)' }}>
                        {s.question_count}
                      </td>
                      <td style={{ padding: '12px 12px', textAlign: 'center' }}>
                        <span style={{
                          fontWeight: 800, fontFamily: 'var(--font-mono)',
                          fontSize: '1rem',
                          color: s.final_score >= 7.5 ? 'var(--clr-success)' : s.final_score >= 5 ? 'var(--clr-warning)' : 'var(--clr-danger)',
                        }}>
                          {(s.final_score || 0).toFixed(1)}
                        </span>
                        <span style={{ fontSize: '0.7rem', color: 'var(--clr-text-muted)' }}>/10</span>
                      </td>
                      <td style={{ padding: '12px 12px' }}>
                        <RecPill rec={s.recommendation} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* ── CTA footer ── */}
        <div style={{
          marginTop: 32, textAlign: 'center',
          padding: '32px 24px',
          background: 'linear-gradient(135deg, rgba(99,102,241,0.1), rgba(139,92,246,0.1))',
          borderRadius: 'var(--r-lg)', border: '1px solid rgba(99,102,241,0.2)',
        }}>
          <div style={{ fontSize: '2.5rem', marginBottom: 12 }}>🚀</div>
          <h2 style={{ margin: '0 0 8px', fontSize: '1.3rem' }}>Ready to practice again?</h2>
          <p style={{ color: 'var(--clr-text-muted)', marginBottom: 20, maxWidth: 400, margin: '0 auto 20px' }}>
            Consistent practice is the fastest way to land your dream job. Start a new mock interview now.
          </p>
          <button
            className="btn btn-primary"
            style={{ padding: '14px 36px', fontSize: '1rem', fontWeight: 700 }}
            onClick={() => navigate('/interview')}
          >
            ▶ Start New Mock Interview
          </button>
        </div>
      </div>
    </div>
  )
}
