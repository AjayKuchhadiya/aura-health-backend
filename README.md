# Aura Health Backend

A production-ready healthcare platform API built with **FastAPI**, **PostgreSQL**, and **Google Gemini AI**. Powers an intelligent health navigator that connects patients with doctors, provides AI-assisted medical guidance, and locates nearby clinics and ambulance services.

[![CI/CD](https://github.com/YOUR_GITHUB_USERNAME/aura-health-backend/actions/workflows/deploy.yml/badge.svg)](https://github.com/YOUR_GITHUB_USERNAME/aura-health-backend/actions/workflows/deploy.yml)

**Live API:** `https://aura-health-backend.onrender.com`  
**Docs (Swagger):** `https://aura-health-backend.onrender.com/docs`

---

## Features

| Feature | Details |
|---|---|
| **AI Health Navigator** | Conversational agent ("Aura") powered by Google Gemini via Google ADK. Injects the user's medical profile as context on every turn. |
| **Doctor Search** | Search platform doctors by specialty or locate real-world clinics near GPS coordinates via OpenStreetMap Overpass API. |
| **Firebase Auth** | Stateless Bearer token authentication using Firebase Admin SDK. |
| **Digital Twin** | Patient medical profiles stored as JSONB — used as live context for the AI agent. |
| **Ambulance Locator** | Finds the nearest ambulance service using GPS coordinates. |
| **Database Migrations** | Alembic — runs automatically on every deploy via pre-deploy command. |

---

## Tech Stack

- **Framework:** FastAPI (async)
- **Database:** PostgreSQL (Supabase) via SQLAlchemy async + asyncpg
- **Migrations:** Alembic
- **Auth:** Firebase Admin SDK
- **AI Agent:** Google ADK + Gemini
- **Geo:** OpenStreetMap Overpass API
- **OCR:** Google Cloud Vision
- **Storage:** AWS S3 / Cloudflare R2
- **Deployment:** Render (Docker) with GitHub Actions CI/CD

---

## Local Development

### Prerequisites
- Python 3.11+
- PostgreSQL database (or a Supabase project)
- Firebase project with a service account key

### Setup

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_GITHUB_USERNAME/aura-health-backend.git
cd aura-health-backend

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env
# Edit .env with your actual values

# 5. Run database migrations
alembic upgrade head

# 6. Start the server
uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000/docs` for the interactive API docs.

---

## Environment Variables

See [.env.example](.env.example) for all required and optional variables.

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL URL (`postgresql+asyncpg://...`) |
| `SECRET_KEY` | Yes | Random secret for signing tokens |
| `GEMINI_API_KEY` | Yes | Google Gemini API key for the AI agent |
| `FIREBASE_CREDENTIALS` | Yes | Firebase service account JSON (as a string) |
| `GOOGLE_VISION_API_KEY` | No | Google Cloud Vision for OCR |
| `AWS_ACCESS_KEY_ID` | No | S3 / R2 file storage |

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/api/v1/auth/signup` | Register / login via Firebase token |
| `POST` | `/api/v1/users/patient-profile` | Save patient medical profile |
| `POST` | `/api/v1/users/doctor-profile` | Create or update doctor profile |
| `POST` | `/api/v1/chat/run` | Run AI health navigator conversation |
| `GET` | `/api/v1/ambulance` | Find nearest ambulance service |

Full interactive docs available at `/docs` when the server is running.

---

## Deployment (Render)

This project auto-deploys to [Render](https://render.com) on every push to `main` via GitHub Actions.

### First-time setup

1. Push this repo to GitHub.
2. Create a new **Web Service** on Render → connect your GitHub repo → select **Docker** runtime.
3. Add all required environment variables in Render's dashboard (**Environment** tab).
4. Copy the **Deploy Hook URL** from Render's service **Settings** tab.
5. Add it as a GitHub repository secret named `RENDER_DEPLOY_HOOK_URL` (**Settings → Secrets → Actions**).

After that, every push to `main` will:
1. Run the CI smoke test in GitHub Actions.
2. On success, trigger a Render deploy.
3. Render runs `alembic upgrade head` before swapping traffic.

---

## CI/CD Pipeline

```
Push to main
    │
    ▼
GitHub Actions: Install deps → Import smoke test
    │
    ▼ (on pass)
Render Deploy Hook triggered
    │
    ▼
Render: Build Docker image
    │
    ▼
Pre-deploy: alembic upgrade head
    │
    ▼
New version live at same URL
```

---

## License

[MIT](LICENSE)