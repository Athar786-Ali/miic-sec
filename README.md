<div align="center">

<img src="https://img.shields.io/badge/MIIC--Sec-AI%20Interview%20Platform-6366f1?style=for-the-badge&logo=shield&logoColor=white" />

# 🛡️ MIIC-Sec
### AI-Powered Mock Interview & Student Career Accelerator Platform

<p>
  <img src="https://img.shields.io/github/stars/Athar786-Ali/miic-sec?style=flat-square&logo=github&label=Stars&color=FFD700" />
  <img src="https://img.shields.io/github/forks/Athar786-Ali/miic-sec?style=flat-square&logo=github&label=Forks&color=6366f1" />
  <img src="https://img.shields.io/github/issues/Athar786-Ali/miic-sec?style=flat-square&logo=github&label=Issues&color=orange" />
  <img src="https://img.shields.io/github/issues-pr/Athar786-Ali/miic-sec?style=flat-square&logo=github&label=PRs&color=brightgreen" />
  <img src="https://img.shields.io/github/last-commit/Athar786-Ali/miic-sec?style=flat-square&logo=git&label=Last%20Commit&color=blue" />
</p>

<p>
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react&logoColor=black" />
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/Ollama-Qwen2.5:7b-FF6B35?style=flat-square" />
  <img src="https://img.shields.io/badge/Deepgram-nova--2-00E599?style=flat-square" />
  <img src="https://img.shields.io/badge/Security-RSA--2048%20%7C%20TOTP%20%7C%20Biometric-red?style=flat-square" />
  <img src="https://img.shields.io/badge/Tests-106%20Passing-brightgreen?style=flat-square&logo=pytest" />
  <img src="https://img.shields.io/badge/License-MIT-green?style=flat-square" />
</p>

<p>
  <b>A fully self-hosted, production-ready AI mock interview platform for students</b><br/>
  5-tier biometric security · adaptive LLM questioning · real-time Deepgram transcription<br/>
  cryptographically signed reports · live code editor · topic-wise growth analytics · PDF export
</p>

<p>
  <a href="#-what-this-project-does">What It Does</a> •
  <a href="#-key-features">Features</a> •
  <a href="#-tech-stack">Tech Stack</a> •
  <a href="#-architecture">Architecture</a> •
  <a href="#-security-model">Security</a> •
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-api-reference">API Reference</a> •
  <a href="#-changelog">Changelog</a> •
  <a href="#-author">Author</a>
</p>

---

</div>

## 🎯 What This Project Does

MIIC-Sec is a **full-stack AI mock interview system** built entirely from scratch. It solves a real problem — students preparing for tech interviews have no safe, pressure-simulated, feedback-rich environment that mirrors real company conditions.

**Core mission**: Help students overcome interview anxiety and fear by simulating realistic interview pressure in a judgment-free environment, with clear, honest, actionable feedback and measurable growth over time.

The platform combines:
- A **local AI interviewer** (Qwen2.5:7b via Ollama) that adapts difficulty in real-time and gives coaching-style feedback
- **Biometric security** (face + voice + liveness + TOTP + multi-person detection) to prevent impersonation
- **Two pressure modes** — relaxed practice or full real-interview simulation
- **Real-time voice transcription** via Deepgram (live streaming, no upload lag)
- **Topic-wise growth tracking** — see exactly which CS topics you've improved in
- **Cryptographically signed PDF reports** (RSA-2048) students can download and keep
- A **Monaco code editor** for coding questions (same engine as VS Code / LeetCode)

> **Built entirely from scratch** — no off-the-shelf interview platform, no pre-built auth library. Every security tier, AI pipeline, and UI component was designed and implemented independently.

---

## 🖼️ Student Experience — Screen by Screen

| Screen | Description |
|--------|-------------|
| `/signup` | **NEW** — Email + password signup with OTP email verification |
| `/login` | Biometric login (Face → Liveness → Voice → TOTP) |
| `/enroll` | Multi-step biometric enrollment — face capture (5 angles) + voice + TOTP QR |
| `/interview` | Mode picker → topic/resume/company setup → live interview with hint button |
| `/dashboard` | Score chart, topic radar, focus areas, practice streak, growth PDF download |
| `/report/:id` | Per-question scores, coaching feedback, RSA signature, PDF download |

---

## ✨ Key Features

### 🚀 Phase 1 — Friction-Free Onboarding
- **Email + Password signup** — no biometric enrollment required to get started
- **OTP email verification** — 6-digit code with 60-second resend cooldown
- Auto-login after OTP verification
- "Create account with email →" link on biometric login page
- Biometric login still available for returning users via Candidate ID

### 📊 Phase 2 — Topic-wise Progress Tracking
- Every session automatically updates per-topic performance in `TopicPerformance` table
- **`GET /user/progress`** returns: avg score, attempt count, trend (last 5), weak/improved topics
- Dashboard shows a **radar chart** of your growth across topics
- **Focus Areas panel** — top 3 lowest topics with tailored study tips
- **"You've Improved In"** chip list — topics with an upward trend

### 🎯 Phase 3 — Realistic Pressure Simulation
Two modes selectable in interview setup:

| Mode | Hints | Timer | Webcam Proctoring | Description |
|------|-------|-------|-------------------|-------------|
| 🌱 **Just Practice** | ✅ On | Soft | Off | Safe learning mode. Focus on improvement. |
| 🔥 **Simulate Real Pressure** | ❌ Off | Strict | On | Closest to a real interview. No safety net. |

- **Hint engine** (`POST /interview/hint`) — Socratic nudge via LLM (blocked in simulated mode)
- 💭 "Need a hint?" button in the live interview UI (hidden in simulated mode)
- Webcam/emotion analysis thread only starts in simulated mode — saving CPU in practice

### 💬 Phase 4 — Human-Feeling Coaching Feedback
After every answer, students see two coaching cards instead of a raw score:

- ✅ **"What was good"** — green card, acknowledges effort and correct thinking
- 💡 **"Next time try"** — amber card, specific actionable improvement tip
- Both cards fade in with animation and auto-clear after 6 seconds
- Feedback tone is warm and encouraging — never harsh or judgmental

### 📄 Phase 5 — Progress Proof (PDF Export)
- **Per-session PDF** — `GET /report/{session_id}/pdf` — includes score table, Q-by-Q breakdown, detailed feedback, RSA signature status
- **Cumulative Growth Report PDF** — `GET /user/progress/pdf` — topic performance table, focus areas, improved topics, session score timeline
- Styled with MIIC-Sec's indigo/violet color palette (ReportLab)
- Download buttons on both the Report page and Dashboard

### ✨ Phase 6 — UX Polish
- 🔥 **Practice Streak** stat card — consecutive days with completed sessions
- 👋 **First-time walkthrough card** — 4-step guide on dashboard (dismissable, remembered in `localStorage`)
- 📱 **Full mobile responsive layout** — `@media 768px` and `480px` breakpoints for all pages
- **Feedback cards animate** on every answer with `fadeInUp`

---

### 🤖 Adaptive AI Interviewer
- **Local LLM** — Qwen2.5:7b via Ollama. Fully self-hosted. Zero data leaves your machine.
- **Adaptive difficulty** — sliding-window algorithm adjusts easy/medium/hard in real-time based on last 3 scores
- **3 Interview Modes** — Topic Based · Resume Based (AI reads your PDF) · Combined
- **3 Company AI Personas:**

| Persona | Target | AI Style |
|---------|--------|----------|
| 🏢 Service Based | TCS / Wipro / Infosys | CS fundamentals, OOP, SQL, verbal logic |
| 🚀 Product / FAANG | Google / Amazon / Microsoft | System design, edge cases, optimal complexity, cross-questioning |
| ⚡ Startup | Fast-paced product cos | Practical skills, frameworks, real-world problem solving |

### 🔐 5-Tier Biometric Security
| Tier | Technology | What It Checks |
|------|-----------|----------------|
| **1 — Face** | DeepFace (ArcFace model) | Biometric face match against enrolled embedding |
| **2 — Liveness** | Dlib + blink detection | Prevents photo/video spoofing |
| **3 — Voice** | wav2vec2-base (HuggingFace) | Voice biometric (cosine similarity ≥ 0.60) |
| **4 — TOTP** | PyOTP (RFC 6238) | 6-digit rotating code — Google Authenticator |
| **5 — Proctoring** | YOLOv8 + PyAnnote | Multi-person/speaker detection during interview |

> 🌱 Biometric security is **gated behind "Simulate Real Pressure" mode**. In practice mode, students can focus on learning without the overhead.

### 🎙️ Real-Time Voice with Deepgram
- **Live WebSocket streaming** — Deepgram nova-2 model, `en-IN` language, smart formatting
- Short-lived **temp API keys** issued per session and revoked immediately after recording ends
- **Whisper fallback** — if `DEEPGRAM_API_KEY` is absent, local Whisper model is used automatically
- Fallback to typed input if microphone unavailable

### 📊 Cryptographic Reports
- **RSA-2048 + SHA-256** signed report JSON after every interview
- **Blockchain-style audit log** — every event linked by SHA-256 hash chain
- **Publicly verifiable** — `GET /report/:id/verify` returns `{ valid: true/false }`
- Shareable on LinkedIn; downloadable as PDF

### 💻 Live Code Editor (Monaco)
- VS Code engine (same as LeetCode, GitHub Codespaces)
- 4 languages: Python · JavaScript · Java · C++
- Isolated Docker sandbox per execution (`--network none --memory 128m --cpus 0.5`)
- Bandit static analysis + custom pattern scanner before running

---

## 🛠️ Tech Stack

### Backend
| Layer | Technology | Why |
|-------|-----------|-----|
| API Framework | **FastAPI 0.115** | Async, fast, automatic OpenAPI docs |
| Database | **SQLAlchemy + SQLite** | Simple, portable, no external DB needed |
| AI / LLM | **Ollama + Qwen2.5:7b** | Self-hosted, private, no API cost |
| Face Auth | **DeepFace (ArcFace)** | State-of-the-art face recognition |
| Voice Auth | **HuggingFace wav2vec2** | Proven voice embedding model |
| Liveness | **Dlib + OpenCV** | Blink-based anti-spoofing |
| Multi-person | **YOLOv8 (Ultralytics)** | Real-time person detection |
| Transcription | **Deepgram nova-2 REST + WS** | Fast, accurate, Indian English optimised |
| Diarization | **PyAnnote.audio** | Multi-speaker detection |
| Cryptography | **`cryptography` (RSA-2048)** | Report signing, key management |
| Auth | **PyJWT (RS256) + PyOTP + passlib[bcrypt]** | Stateless JWT + TOTP 2FA + password hashing |
| PDF Export | **ReportLab** | Styled growth and session PDF reports |
| Resume Parse | **PyPDF** | PDF text extraction |

### Frontend
| Layer | Technology | Why |
|-------|-----------|-----|
| Framework | **React 18 + Vite 5** | Fast HMR, optimised builds |
| Routing | **React Router v6** | Protected routes, SPA navigation |
| HTTP | **Axios** | Auth interceptor, 401 redirect |
| Charts | **Recharts** | Score progress + radar chart + emotion timeline |
| Code Editor | **Monaco Editor** | VS Code engine in-browser |
| Styling | **Vanilla CSS** | Dark glassmorphism, no framework bloat |
| WebSocket | **Native WS API** | Real-time security events |

---

## 🏛️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        MIIC-Sec Platform                        │
│                                                                 │
│  React Frontend (Vite)         FastAPI Backend (port 8000)      │
│  ┌─────────────────┐           ┌───────────────────────────┐   │
│  │ /signup  [NEW]  │◄──HTTP───►│ /auth/*   Biometrics      │   │
│  │ /login          │◄──WS─────►│ /interview/* LLM + AI     │   │
│  │ /enroll         │           │ /user/*   Dashboard       │   │
│  │ /dashboard      │           │ /report/* Signed Reports  │   │
│  │ /interview      │           │ /security/* Proctoring    │   │
│  │ /report/:id     │           │ /ws/*    Live Events      │   │
│  └─────────────────┘           └───────────┬───────────────┘   │
│                                            │                    │
│          ┌─────────────┬──────────┬────────┴──────────┐         │
│    ┌─────▼──────┐ ┌────▼─────┐ ┌──▼──────┐ ┌─────────▼──┐     │
│    │  Ollama    │ │ Deepgram │ │ SQLite  │ │  RSA-2048  │     │
│    │ Qwen2.5:7b │ │ nova-2   │ │ SQLAlch │ │  Keys/JWT  │     │
│    └────────────┘ └──────────┘ └─────────┘ └────────────┘     │
│                                                                 │
│    ┌────────────┐ ┌──────────┐ ┌─────────┐ ┌─────────────┐    │
│    │  DeepFace  │ │ wav2vec2 │ │  YOLO   │ │  PyAnnote   │    │
│    │  ArcFace   │ │   HF     │ │   v8    │ │ Diarization │    │
│    └────────────┘ └──────────┘ └─────────┘ └─────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### Interview Session Data Flow

```
New Student: /signup → email OTP verify → auto-login
Returning:   /login  → Face → Liveness → Voice → TOTP → RS256 JWT
    ↓
Dashboard → Interview Setup:
  - Choose Mode:    Just Practice 🌱 | Simulate Real Pressure 🔥
  - Choose Persona: Service / Product-FAANG / Startup
  - Choose Format:  Topic Based | Resume Based | Combined
    ↓
POST /interview/start → Ollama LLM → First Question
    ↓
Loop per question:
  Deepgram live voice / type answer
  [Practice only] → POST /interview/hint → Socratic nudge
    → POST /interview/respond → LLM score
      + "What was good" (green card)
      + "Next time try" (amber card)
    → Adaptive difficulty update
    → InterviewLog persisted to SQLite
    [Simulated] → YOLO + emotion + diarization in background threads
    ↓
POST /interview/end
  → LLM: Strengths / Weaknesses / Study Topics
  → update TopicPerformance table per topic
  → RSA-2048 sign report → save JSON
  → /report/:sessionId  (Download JSON or PDF)
  → /dashboard          (Radar chart + focus areas + streak)
```

---

## 🔐 Security Model

### Login Flow (Sequential, must pass all 4)
```
① Face biometric     DeepFace ArcFace cosine match vs enrolled embedding
② Liveness check     Dlib blink detection — blocks photo/video attacks
③ Voice biometric    wav2vec2 cosine similarity ≥ 0.60
④ TOTP 6-digit       30-second rotating code (RFC 6238)
                     ↓
                   RS256 JWT issued
```

### Continuous Proctoring (Simulated Pressure Mode Only)
- YOLO checks webcam frame every 30s → multiple persons detected → TOTP step-up challenge
- Tab switch detected → warning → 3 warnings → session terminated
- Voice stream analyzed for multiple speakers (PyAnnote diarization)
- Face re-verification mid-session — mismatch triggers step-up

### Cryptographic Report Integrity
```python
report_json = json.dumps(report, sort_keys=True)  # deterministic
signature   = private_key.sign(report_json, PKCS1v15(), SHA256())
# Embed base64 signature in report JSON
# Verify: GET /report/:id/verify → { "valid": true }
```

### Audit Hash Chain
Every security event stored with:
```json
{
  "event_type": "QUESTION_ANSWERED",
  "detail":     { "score": 8.5, "q_num": 3 },
  "prev_hash":  "sha256(previous_event)",
  "hash":       "sha256(this_event + prev_hash)"
}
```
Tamper any one event → all subsequent hashes break → detectable.

---

## 📁 Project Structure

```
miic-sec/
├── backend/
│   ├── main.py                    # FastAPI app, CORS, lifespan, router registration
│   ├── config.py                  # All constants: thresholds, model names, SMTP
│   ├── database.py                # SQLAlchemy models + _safe_migrate() for schema evolution
│   │    Models: Candidate, Session, InterviewLog, AuditLog, OtpToken, TopicPerformance
│   │
│   ├── auth/
│   │   ├── routes.py              # /enroll, /login, /signup, /verify-email, /password-login
│   │   ├── email_auth.py          # [NEW] Email signup, OTP verify, bcrypt password auth
│   │   ├── face_auth.py           # DeepFace ArcFace enrollment + verification
│   │   ├── voice_auth.py          # wav2vec2 voice embedding + cosine similarity
│   │   ├── liveness.py            # Dlib blink-detection anti-spoofing
│   │   ├── totp_auth.py           # PyOTP TOTP generation + QR code
│   │   └── jwt_manager.py         # RS256 JWT issue + decode + middleware
│   │
│   ├── interview/
│   │   ├── routes.py              # /start, /respond, /end, /transcribe, /hint [NEW]
│   │   ├── llm_interviewer.py     # Adaptive Ollama LLM + coaching-tone feedback parser
│   │   ├── transcriber.py         # Deepgram REST primary + Whisper fallback
│   │   ├── hint_engine.py         # [NEW] Socratic hint generator (practice mode only)
│   │   ├── topic_tracker.py       # [NEW] Per-topic performance upsert + progress analytics
│   │   ├── topic_manager.py       # Topic list management
│   │   ├── dashboard.py           # /user/dashboard, /user/progress, /user/progress/pdf
│   │   ├── adaptive_engine.py     # Sliding-window difficulty adjuster
│   │   ├── emotion_analysis.py    # Background emotion + proctoring thread
│   │   ├── resume_parser.py       # PyPDF resume text extraction
│   │   └── code_sandbox.py        # Docker isolated code execution
│   │
│   ├── security/
│   │   └── routes.py              # /face-recheck, /tab-switch, /step-up-verify
│   │
│   ├── report/
│   │   ├── routes.py              # /report/:id, /verify, /download, /pdf [NEW]
│   │   └── pdf_export.py          # [NEW] ReportLab session + growth PDF generators
│   │
│   ├── crypto/
│   │   ├── report_signer.py       # RSA-2048 sign/verify + report assembly
│   │   └── audit_log.py           # SHA-256 hash-chain audit events
│   │
│   ├── verification/
│   │   ├── proxy_detector.py      # YOLOv8 multi-person detection
│   │   └── continuous_verifier.py # Background identity re-check loop
│   │
│   ├── websocket/
│   │   └── ws_manager.py          # WebSocket ConnectionManager + event types
│   │
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── SignupLogin.jsx     # [NEW] Email/password signup + OTP verification
│   │   │   ├── Login.jsx          # Biometric login (Face→Liveness→Voice→TOTP)
│   │   │   ├── Enrollment.jsx     # Multi-step biometric enrollment wizard
│   │   │   ├── Dashboard.jsx      # Stats + radar chart + streak + focus areas + PDF
│   │   │   ├── Interview.jsx      # Live interview: mode badge + hint button + coaching cards
│   │   │   ├── InterviewSetup.jsx # Mode picker (Practice/Simulated) + persona + topics
│   │   │   └── Report.jsx         # Report viewer + PDF download + LinkedIn share
│   │   ├── utils/
│   │   │   └── api.js             # Axios instance + sessionStorage auth store
│   │   ├── main.jsx               # Router: /signup [NEW] + protected routes
│   │   └── index.css              # Dark glassmorphism + feedback cards + responsive CSS
│   ├── vite.config.js             # Dev proxy for /auth, /interview, /ws etc.
│   └── Dockerfile
│
├── tests/
│   ├── test_phase1.py             # Biometric auth pipeline tests
│   ├── test_phase2.py             # Enrollment + JWT tests
│   ├── test_phase3.py             # LLM interviewer + adaptive engine tests
│   ├── test_phase4.py             # WebSocket, proctoring, audit chain tests
│   ├── test_phase5.py             # Report generation + RSA signing tests
│   └── test_phase6.py             # Transcription pipeline tests
│
├── docker/
│   └── Dockerfile.backend
├── docker-compose.yml
├── keys/                          # RSA keypair (auto-generated on first run)
├── reports/                       # Signed JSON + PDF reports
└── .env.example
```

---

## 💻 System Requirements

### Minimum (runs everything on CPU)
| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **RAM** | 8 GB | 16 GB |
| **CPU** | 4-core (x86-64 or Apple Silicon) | 8-core M2 / Ryzen 7 |
| **Storage** | 10 GB free | 20 GB free |
| **OS** | macOS 13+, Ubuntu 22.04+, Windows 11 (WSL2) | macOS 14 / Ubuntu 24.04 |
| **Python** | 3.11 | 3.11 or 3.12 |
| **Node.js** | 18.x | 20.x LTS |
| **Webcam** | Any 720p USB/built-in | 1080p with good low-light |
| **Microphone** | Any built-in mic | Headset / dedicated mic |

> ⚡ **Apple Silicon (M1/M2/M3)**: Fully supported. Ollama uses Metal acceleration automatically.  
> 🎮 **GPU**: Optional. DeepFace and YOLOv8 auto-use CUDA if available — no code changes needed.

---

## 🚀 Quick Start

### Prerequisites

| Tool | Install |
|------|---------| 
| Python 3.11+ | [python.org](https://python.org) |
| Node.js 18+ | [nodejs.org](https://nodejs.org) |
| Ollama | `brew install ollama` (macOS) |
| Docker + Compose | [docker.com](https://docker.com) |

### Option A — Local Development (Recommended)

```bash
# 1. Clone
git clone https://github.com/Athar786-Ali/miic-sec.git
cd miic-sec

# 2. Pull LLM model (one-time, ~4 GB)
ollama pull qwen2.5:7b
ollama serve            # keep running

# 3. Backend
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 4. Frontend (new terminal)
cd frontend
npm install
npm run dev
```

| Service | URL |
|---------|-----|
| 🌐 Frontend | http://localhost:3000 |
| ⚙️ Backend API | http://localhost:8000 |
| 📖 Swagger UI | http://localhost:8000/docs |

**First-time student flow:**  
→ Go to `http://localhost:3000` → **Create Account** → enter name + email + password → enter OTP from email → auto-signed in → start practicing!

**Returning / biometric users:**  
→ `/login` → Face → Liveness → Voice → TOTP → Dashboard

### Option B — Docker Compose

```bash
cd miic-sec
docker compose up --build

# First time: pull the LLM inside the container
docker exec -it miic_ollama ollama pull qwen2.5:7b
```

### Environment Variables (`backend/.env`)

Copy `.env.example` to `backend/.env` and fill in:

```env
# ── Speech-to-Text ──────────────────────────────────────────────
DEEPGRAM_API_KEY=your_deepgram_key       # Required for live voice transcription
                                          # Free tier: 200 hrs/month at deepgram.com
                                          # If absent, local Whisper fallback activates

# ── Email OTP (Phase 1 — Onboarding) ────────────────────────────
SMTP_HOST=smtp.gmail.com                 # Gmail SMTP (or any SMTP provider)
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASS=your_app_password              # Gmail App Password (not your login password)
SMTP_FROM=your_email@gmail.com

# ── AI / Diarization ────────────────────────────────────────────
HF_TOKEN=hf_your_token                   # Optional — needed only for PyAnnote
                                          # multi-speaker diarization
                                          # Get one free at huggingface.co/settings/tokens

# ── Platform ────────────────────────────────────────────────────
OLLAMA_BASE_URL=http://localhost:11434   # Ollama server URL (change for Docker)
SECRET_KEY=change_me_in_production       # Used for additional HMAC operations
ALLOWED_ORIGINS=http://localhost:3000    # CORS — add your domain for cloud deploy

# ── macOS only ──────────────────────────────────────────────────
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES  # Prevents multiprocessing crashes on macOS
```

> 💡 RSA keypair is **auto-generated** in `keys/` on first startup — no manual setup needed.  
> 💡 `SMTP_*` is only required for email OTP. Without it, students can still use the biometric path via `/enroll` + `/login`.

---

## 📡 API Reference

### Auth
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/auth/enroll` | Register: face + voice + TOTP setup |
| `POST` | `/auth/login` | Biometric login → JWT |
| `POST` | `/auth/signup` | **[NEW]** Email + password signup → OTP sent |
| `POST` | `/auth/verify-email` | **[NEW]** Submit OTP → email verified |
| `POST` | `/auth/resend-otp` | **[NEW]** Resend OTP (60s cooldown) |
| `POST` | `/auth/password-login` | **[NEW]** Email + password → JWT |

### Interview
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/interview/start` | Start session with mode/persona/topics/pressure_mode |
| `POST` | `/interview/respond` | Submit answer → score + coaching cards + next question |
| `POST` | `/interview/end` | End session → sign report + update topic tracker |
| `POST` | `/interview/hint` | **[NEW]** Get a Socratic hint (practice mode only) |
| `POST` | `/interview/transcribe` | Audio → Deepgram text (REST, Whisper fallback) |
| `GET`  | `/interview/deepgram-token` | Issue temporary Deepgram key |
| `POST` | `/interview/upload-resume` | Parse PDF resume |

### Security
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/security/face-recheck` | YOLO + face mid-session check |
| `POST` | `/security/tab-switch` | Log tab switch event |
| `POST` | `/security/step-up-verify` | TOTP step-up after mismatch |

### Reports & Dashboard
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET`  | `/report/:session_id` | Fetch signed report |
| `GET`  | `/report/:session_id/verify` | Verify RSA signature |
| `GET`  | `/report/:session_id/download` | Download report JSON |
| `GET`  | `/report/:session_id/pdf` | **[NEW]** Download report as styled PDF |
| `GET`  | `/user/dashboard` | Stats + full interview history + streak |
| `GET`  | `/user/progress` | **[NEW]** Topic-wise performance analytics |
| `GET`  | `/user/progress/pdf` | **[NEW]** Download cumulative growth PDF |
| `WS`   | `/ws/candidate/:session_id` | Real-time security event stream |

---

## 🗄️ Database Schema

```
Candidate        — id, name, email, password_hash [NEW], is_email_verified [NEW],
                   auth_method [NEW], face_embedding, voice_embedding, totp_secret, created_at

Session          — id, candidate_id, status, started_at, ended_at, final_score,
                   pressure_mode [NEW]

InterviewLog     — id, session_id, question_number, question_text, response_text,
                   score, difficulty, topic

AuditLog         — id, session_id, event_type, detail (json), prev_hash, entry_hash, timestamp

OtpToken [NEW]   — id, candidate_id, email, otp_code, expires_at, used

TopicPerformance [NEW] — id, candidate_id, topic, avg_score, attempt_count,
                         last_scores_json, last_updated
```

> Schema changes are applied automatically via `_safe_migrate()` on startup — no manual `ALTER TABLE` needed.

---

## ⚙️ Configuration Reference

All tunable constants live in [`backend/config.py`](backend/config.py). Edit and restart the backend.

| Constant | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./miic_sec.db` | SQLAlchemy connection string |
| `PRIVATE_KEY_PATH` | `keys/private_key.pem` | RSA-2048 private key — auto-generated |
| `JWT_EXPIRY_HOURS` | `2` | Access token TTL |
| `FACE_SIMILARITY_THRESHOLD` | `0.35` | ArcFace cosine distance upper bound |
| `VOICE_SIMILARITY_THRESHOLD` | `0.60` | wav2vec2 cosine similarity lower bound |
| `CONTINUOUS_VERIFY_INTERVAL` | `30` | Seconds between proctoring checks |
| `MAX_FAILURES_BEFORE_TERMINATE` | `2` | Proctoring failures before termination |
| `OLLAMA_MODEL` | `qwen2.5:7b` | Primary LLM model |
| `OLLAMA_FALLBACK_MODEL` | `qwen2.5:3b` | Smaller fallback model |
| `DEEPGRAM_MODEL` | `nova-2` | Deepgram ASR model |
| `DEEPGRAM_LANGUAGE` | `en-IN` | ASR language hint |
| `YOLO_MODEL` | `yolov8n.pt` | YOLOv8 weights for person detection |

---

## 🧠 AI Pipeline Details

### Adaptive Difficulty Algorithm
```python
# After each answer, recalculate difficulty from last 3 scores
window = scores[-3:]
avg = mean(window)
if avg >= 7.5:   next_difficulty = "hard"
elif avg >= 4.5: next_difficulty = "medium"
else:            next_difficulty = "easy"
```

### Coaching Feedback Format (Phase 4)
The LLM evaluation prompt now includes a structured coaching section:
```
Score: 7|What you did well: Clear explanation of time complexity|Improve: Also discuss space complexity trade-offs
```
Both `what_was_good` and `improve_tip` are parsed and returned in the `/respond` payload.

### Topic Performance Tracking (Phase 2)
```python
# After each session ends, for each question's topic:
upsert_topic_performance(candidate_id, topic, question_score, db)
# Keeps a rolling window of last 5 scores per topic
# Detects upward trend: last_score > avg of previous scores
```

### Voice Authentication Flow
```python
# Enrollment: 10s recording → wav2vec2 → 768-d embedding → stored as pickle blob
# Login:       5s recording  → wav2vec2 → 768-d embedding
# Verify:      cosine_similarity(stored, live) >= 0.60 → pass
```

---

## 😶‍🌫️ Emotion Detection & Proctoring Deep-Dive

During simulated mode, MIIC-Sec runs a **silent background security pipeline**:

```
┌──────────────────────── Background Thread (every 30 s) ───────────────────────────┐
│                                                                                    │
│  1. Capture webcam frame (OpenCV)                                                  │
│       ↓                                                                            │
│  2. YOLOv8 person detection                                                        │
│     • persons == 1  → ✅ OK                                                        │
│     • persons  > 1  → ⚠️  Multi-person event → TOTP step-up challenge             │
│     • persons == 0  → ⚠️  Out-of-frame event → warning (3× → terminate)           │
│       ↓                                                                            │
│  3. DeepFace identity re-check (ArcFace)                                           │
│     • matches enrolled embedding → ✅ OK                                           │
│     • mismatch                   → 🔴 Identity drift → TOTP step-up              │
│       ↓                                                                            │
│  4. Emotion extraction (DeepFace `analyze`)                                        │
│     • dominant_emotion logged per check interval                                   │
│     • stored in AuditLog → rendered as timeline in final report                    │
│       ↓                                                                            │
│  5. Audio diarization (PyAnnote, if HF_TOKEN set)                                  │
│     • 1 speaker  → ✅ OK                                                           │
│     • 2+ speakers → ⚠️  Multiple voices event → AuditLog entry                   │
│                                                                                    │
└────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🐛 Troubleshooting

| Problem | Solution |
|---------|----------|
| `ollama: connection refused` | Run `ollama serve` in a separate terminal |
| OTP email not received | Check `SMTP_*` in `.env`; use Gmail App Password not login password |
| `CUDA out of memory` | App runs on CPU — no GPU needed |
| `Face not detected` | Ensure good lighting, face camera directly |
| `TOTP code invalid` | Check phone clock is synced (NTP) |
| `Deepgram token error` | Check `DEEPGRAM_API_KEY` in `backend/.env` |
| `Module not found` | Run `pip install -r requirements.txt` again |
| `Port 8000 in use` | `lsof -ti:8000 \| xargs kill -9` |
| PDF download fails | Ensure `reportlab` is installed: `pip install reportlab` |

---

## ⚡ Performance & Benchmarks

Benchmarks on **MacBook Pro M2 (16 GB RAM)** running Ollama locally:

| Operation | Avg. Latency | Notes |
|-----------|-------------|-------|
| Email OTP verification | < 1s | bcrypt hash + DB write |
| Face enrollment (5 angles) | ~3–5 s | DeepFace ArcFace embedding |
| Liveness check (blink detect) | ~0.3 s / frame | Dlib 68 landmarks |
| Voice embedding (wav2vec2) | ~1.2 s | 8 s clip → 768-d vector |
| TOTP verification | < 50 ms | In-memory PyOTP check |
| LLM question generation | ~4–8 s | Qwen2.5:7b on CPU via Ollama |
| Deepgram live transcription | < 300 ms | WebSocket streaming |
| RSA-2048 sign report | ~15 ms | Python `cryptography` library |
| YOLOv8 person detection | ~80 ms / frame | `yolov8n.pt` nano model |
| Growth PDF generation | ~200 ms | ReportLab — topic table + timeline |

---

## 🚶 End-to-End User Journey

```
📦 STEP 1 — Setup (One-Time)
   ├── Clone repo & install dependencies
   ├── Pull Ollama LLM model (~4 GB, once)
   ├── Add Deepgram API key + SMTP keys to backend/.env
   └── Start backend + frontend servers

👤 STEP 2A — Quick Start (Email Signup) [NEW]
   ├── Go to /signup → enter name, email, password
   ├── Check email for OTP code → enter it
   └── Auto-signed in → go straight to /interview

👤 STEP 2B — Full Biometric Enrollment (Optional but recommended for Simulate mode)
   ├── Go to /enroll → enter name & email
   ├── Capture face from 5 angles (front, left, right, up, down)
   ├── Record 8-second voice sample
   ├── Scan TOTP QR code with Google Authenticator / Authy
   └── Enrollment complete — biometrics stored locally

⚙️ STEP 3 — Configure Interview
   ├── Choose Pressure Mode: Just Practice 🌱 | Simulate Real Pressure 🔥
   ├── Choose Format:        Topic Based | Resume Based | Combined
   ├── Choose Persona:       Service Based | Product/FAANG | Startup
   └── Select topics or upload PDF resume

🎙️ STEP 4 — Interview
   ├── AI asks adaptive questions (adjusts difficulty per answer)
   ├── [Practice] 💭 "Need a hint?" button available
   ├── Answer by voice (Deepgram) or typed text
   ├── After each answer: ✅ "What was good" + 💡 "Next time try" coaching cards
   ├── [Simulated] Continuous proctoring: YOLO, emotion, diarization
   └── For coding Qs: Monaco editor with Docker sandbox execution

📊 STEP 5 — Report & Growth
   ├── Download PDF report (per-session breakdown)
   ├── Dashboard: radar chart of topic growth
   ├── Focus Areas: top 3 weakest topics with study tips
   ├── "You've Improved In": topics trending upward
   ├── 🔥 Practice streak counter
   └── Download cumulative Growth Report PDF
```

---

## ✅ Self-Hosting Checklist

```
Infrastructure
  [ ] Server with ≥ 8 GB RAM (16 GB recommended for LLM)
  [ ] Domain with HTTPS (Let's Encrypt via Certbot)
  [ ] Nginx proxy: / → frontend, /auth /interview /ws → FastAPI :8000

Backend
  [ ] pip install -r requirements.txt completed
  [ ] backend/.env created with DEEPGRAM_API_KEY + SMTP_* + OLLAMA_BASE_URL
  [ ] Ollama running with qwen2.5:7b pulled
  [ ] RSA keypair auto-generated in keys/ on first startup
  [ ] ALLOWED_ORIGINS set to your production domain
  [ ] SECRET_KEY changed from default

Frontend
  [ ] npm run build → frontend/dist/ generated
  [ ] Nginx serving frontend/dist/ for root /

Verification
  [ ] GET https://your.domain/docs → Swagger UI loads
  [ ] /signup → OTP email received → auto-login works
  [ ] Enrollment + biometric login works end-to-end
  [ ] Interview completes and report PDF downloads
```

---

## 📋 Changelog

### v2.0.0 — Latest (Student-First Redesign)

**Phase 1 — Friction-Free Onboarding**
- ✅ `POST /auth/signup` — email + password account creation
- ✅ `POST /auth/verify-email` — OTP verification with 60s resend cooldown
- ✅ `POST /auth/password-login` — JWT issuance for email-auth users
- ✅ `SignupLogin.jsx` — tabbed Create Account / Login UI with OTP screen
- ✅ Default entry point changed from `/login` to `/signup`
- ✅ `database.py` — added `password_hash`, `is_email_verified`, `auth_method`, `OtpToken` table

**Phase 2 — Topic-wise Progress Tracking**
- ✅ `TopicPerformance` table — per-topic avg, attempts, last-5 scores, trend
- ✅ `GET /user/progress` — analytics with weak/improved topics + study tips
- ✅ Dashboard radar chart (recharts), Focus Areas panel, "You've Improved In" chips

**Phase 3 — Realistic Pressure Simulation**
- ✅ Two modes: **Just Practice** (hints on, no proctoring) vs **Simulate Real Pressure** (strict, proctored)
- ✅ `POST /interview/hint` — Socratic nudge (gated behind practice mode)
- ✅ Webcam/emotion thread only starts in simulated mode

**Phase 4 — Human-Feeling Coaching Feedback**
- ✅ LLM evaluation returns `what_was_good` + `improve_tip` structured fields
- ✅ Interview UI shows green "What was good" + amber "Next time try" animated cards
- ✅ Report labels updated to coaching tone

**Phase 5 — PDF Export**
- ✅ `GET /report/{session_id}/pdf` — styled per-session PDF (ReportLab)
- ✅ `GET /user/progress/pdf` — cumulative growth report PDF
- ✅ Download buttons on Dashboard and Report pages

**Phase 6 — UX Polish**
- ✅ Practice streak stat card (🔥 consecutive days)
- ✅ First-time walkthrough card (dismissable, `localStorage`-persisted)
- ✅ Full mobile responsive CSS (`@media 768px` + `480px`)
- ✅ Whisper fallback in transcriber when `DEEPGRAM_API_KEY` is absent

---

### v1.4.0
- ✅ Configuration Reference — full `config.py` table added to README
- ✅ Emotion Detection deep-dive — pipeline diagram, tab-switch flow, TOTP step-up
- ✅ README restructured with new sections

### v1.3.0
- ✅ End-to-End User Journey, Interview Tips, Self-Hosting Checklist added
- ✅ Author section enriched with LinkedIn and project background

### v1.2.0
- ✅ Expanded test suite — 6 phase files covering every subsystem
- ✅ Nginx HTTPS deployment guide added
- ✅ Competitor comparison table — MIIC-Sec vs HireVue, Interviewing.io, LeetCode

### v1.1.0
- ✅ Replaced Whisper with **Deepgram nova-2** for real-time WebSocket STT (300 ms latency)
- ✅ Ephemeral Deepgram key management — keys issued per session and immediately revoked
- ✅ Non-blocking biometric pipeline — parallel face + voice enrollment
- ✅ SHA-256 hash-chain audit log for tamper-evident event history

### v1.0.0 — Initial Release
- ✅ 5-tier biometric authentication (Face → Liveness → Voice → TOTP → Proctoring)
- ✅ Adaptive Ollama LLM interviewer with 3 modes and 3 personas
- ✅ Monaco code editor with isolated Docker sandbox execution
- ✅ RSA-2048 signed interview reports with public verification endpoint
- ✅ Full-stack React + FastAPI + SQLite implementation

---

## 🗺️ Roadmap

### ✅ Completed (v2.0)
- [x] Email + password onboarding with OTP verification
- [x] Topic-wise performance tracking + radar chart
- [x] Just Practice vs Simulate Real Pressure modes
- [x] Coaching-tone feedback (what was good + improve tip)
- [x] PDF report + PDF growth report export
- [x] Mobile responsive layout + practice streak + walkthrough card
- [x] 5-tier biometric security (face · liveness · voice · TOTP · proctoring)
- [x] Adaptive Ollama LLM interviewer with 3 personas and 3 modes
- [x] Real-time Deepgram voice transcription (WebSocket + REST)
- [x] Monaco code editor with Docker sandbox execution
- [x] RSA-2048 signed + SHA-256 hash-chained reports

### 🔮 Planned (v3.0)
- [ ] **Multimodal LLM upgrade** — LLaVA / Gemma3 for image-based whiteboard questions
- [ ] **PostgreSQL support** — migration path from SQLite for multi-user deployments
- [ ] **Admin dashboard** — institution-level monitoring, bulk enrollment, analytics
- [ ] **Emotion heatmap export** — timeline visualization exportable as PNG
- [ ] **Interview replay** — recorded session review with synchronized transcript
- [ ] **Group interview mode** — multi-candidate, single interviewer session
- [ ] **SSO / LDAP integration** — enterprise single sign-on for institutional deployments
- [ ] **Webhook notifications** — POST results to a custom URL (LMS, Slack, etc.) on session end
- [ ] **Difficulty progression graph** — visualize adaptive difficulty changes per session

---

## 🌐 Production Deployment (Nginx + HTTPS)

```nginx
server {
    listen 443 ssl;
    server_name your.domain.com;

    ssl_certificate     /etc/letsencrypt/live/your.domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your.domain.com/privkey.pem;

    # Serve React build
    root /var/www/miic-sec/frontend/dist;
    index index.html;
    location / { try_files $uri /index.html; }

    # Proxy API + WebSocket to FastAPI
    location ~ ^/(auth|interview|security|report|user|ws)/ {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade $http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
    }
}

server {
    listen 80;
    server_name your.domain.com;
    return 301 https://$host$request_uri;
}
```

---

## ❓ FAQ

**Q: Can I use a different LLM instead of Qwen2.5:7b?**  
Any Ollama-supported model works. Change `OLLAMA_MODEL` in `config.py`. Llama 3.1, Mistral, Gemma 2 all work. Smaller models (3b) are faster; larger (14b) are more accurate.

**Q: What if I don't have a Deepgram API key?**  
Voice transcription falls back to local **Whisper** automatically. No config change needed — just don't set `DEEPGRAM_API_KEY` in `.env`.

**Q: Do I need biometric enrollment to use the platform?**  
No. With v2.0, students can sign up via email + password at `/signup` and start practicing immediately. Biometric enrollment is optional and unlocks the "Simulate Real Pressure" mode.

**Q: Is student data sent to any cloud service?**  
Only speech audio is sent to Deepgram (if key set). All biometric data (face, voice embeddings) and interview logs stay on your local machine in SQLite.

**Q: Can I run this for a whole class of students?**  
Yes, but SQLite is recommended for single-user or small groups. For large deployments, swap `DATABASE_URL` to PostgreSQL in `config.py`. Each student gets their own `Candidate` row and session history.

**Q: Why does face enrollment sometimes fail?**  
Lighting is the #1 cause. Ensure: face the light source directly, no strong backlighting, no sunglasses. DeepFace needs clear facial landmarks across all 5 capture angles.

---

## 👤 Author

**Athar Ali**  
B.Tech CSE student | AI + Security enthusiast

- 🐙 GitHub: [Athar786-Ali](https://github.com/Athar786-Ali)  
- 💼 LinkedIn: [linkedin.com/in/atharali](https://linkedin.com/in/atharali)
- 📧 Email: available on GitHub profile

> MIIC-Sec was built as a major personal project to explore the intersection of biometric security, local LLM inference, and student-focused UX design. Every component was implemented from scratch — no off-the-shelf interview SaaS, no pre-built auth SDK.

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

> ⚠️ This platform is intended for **student practice only**. Do not use it as a real hiring decision tool. Biometric data is stored locally and never transmitted to third parties (except audio to Deepgram if configured).

---

<div align="center">
  <sub>Built with ❤️ for students who want to ace their interviews without fear.</sub><br/>
  <sub>🛡️ MIIC-Sec — Mock Interview with Intelligence, Integrity & Confidence</sub>
</div>
