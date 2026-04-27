# MIIC-Sec — AI-Powered Secure Interview Platform

A fully local, AI-powered interview platform with multi-modal identity verification,
adaptive questioning, and blockchain-style audit logging.

## Architecture

```
miic-sec/
├── backend/          # FastAPI backend
│   ├── auth/         # JWT + TOTP authentication
│   ├── interview/    # AI-powered adaptive interviews
│   ├── verification/ # Face, voice, behavior verification
│   ├── crypto/       # RSA signing, hash chains
│   └── websocket/    # Real-time communication
├── frontend/         # Next.js frontend (Phase 2+)
├── keys/             # RSA keypair (auto-generated)
└── tests/            # Test suite
```

## Tech Stack

- **Backend**: FastAPI + SQLAlchemy + SQLite
- **AI Models**: Ollama (Qwen3), Whisper, DeepFace, YOLO
- **Security**: RSA-2048, JWT (RS256), TOTP, Hash-chain audit log
- **Rule**: No external API calls — everything runs locally

## Quick Start

```bash
# 1. Generate RSA keys
python keys/generate_keys.py

# 2. Install dependencies
pip install -r backend/requirements.txt

# 3. Start backend
cd backend && uvicorn main:app --reload

# 4. Verify
curl http://localhost:8000/health
```

## Phase 1 Checklist

- [x] Project skeleton & folder structure
- [x] RSA keypair generation
- [x] SQLAlchemy database models (4 tables)
- [x] FastAPI app with health check
- [x] Configuration constants
- [x] Phase 1 test suite

## License

Private — All rights reserved.
