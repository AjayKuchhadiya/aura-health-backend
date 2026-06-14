# Aura Health Backend

A production-ready **Personal Digital Twin Health Companion** API built with **FastAPI**, **PostgreSQL (Supabase)**, and **Google Gemini 2.5 Flash**. Powers an AI assistant that helps users track health records, understand prescriptions, log daily health updates, and schedule medication reminders on Google Calendar — all on a fully free-tier stack.

**Live UI:** [https://aura-health-frontend-five.vercel.app](https://aura-health-frontend-five.vercel.app)  
**Live API:** [https://aura-health-backend-2xhl.onrender.com/health](https://aura-health-backend-2xhl.onrender.com/health)  
**Docs (Swagger):** [https://aura-health-backend-2xhl.onrender.com/docs](https://aura-health-backend-2xhl.onrender.com/docs)

---

## Features

| Feature | Details |
|---|---|
| **AI Health Companion ("Aura")** | Conversational agent powered by Gemini 2.5 Flash via Google ADK. Understands the user's full medical profile as context on every turn. |
| **Digital Twin Profile** | Patient medical history, allergies, conditions, and daily health logs stored as JSONB — live context for the AI on every conversation. |
| **Health Record Upload** | Upload prescription images or lab-report PDFs. Gemini 2.5 Flash reads the file natively (multimodal) and extracts medications, dosages, diagnoses, and lab results into the Digital Twin — no OCR API cost. |
| **Medication Diary** | Full CRUD for a user's medication regimen. Stores name, dosage, frequency, start/end dates, and the linked Google Calendar event ID. |
| **Google Calendar Reminders** | When a medication is added, Aura automatically schedules recurring dosage reminder events on the user's own Google Calendar via an SSE-connected MCP server — no Node.js process on this server. |
| **Doctor Search** | Find Aura platform doctors by specialty, or locate real-world clinics near GPS coordinates via OpenStreetMap. |
| **Firebase Auth** | Stateless Bearer token authentication using Firebase Admin SDK. |
| **Supabase Storage** | Health record files stored in a Supabase `health-records` bucket — free tier, no AWS/R2. |
| **Database Migrations** | Alembic — runs automatically on every deploy. |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI (async) |
| Database | PostgreSQL via Supabase — SQLAlchemy async + asyncpg |
| Migrations | Alembic |
| Auth | Firebase Admin SDK |
| AI Agent | Google ADK + Gemini 2.5 Flash |
| File Storage | Supabase Storage (free tier) |
| Medical Extraction | Gemini 2.5 Flash multimodal (replaces Google Vision API) |
| Calendar Integration | Google Calendar MCP server over SSE (remote, no local Node.js) |
| Geo Search | OpenStreetMap Overpass API |
| Deployment | Render (Docker) + GitHub Actions CI/CD |

---

## Local Development

### Prerequisites
- Python 3.11+
- A [Supabase](https://supabase.com) project (free tier is fine)
- Firebase project with a service account key
- A running [Google Calendar MCP server](https://github.com/nspady/google-calendar-mcp) deployed somewhere with SSE transport (e.g. Render)

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
# Edit .env with your actual values (see table below)

# 5. Run database migrations
alembic upgrade head

# 6. Start the server
uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000/docs` for the interactive API docs.

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL URL (`postgresql+asyncpg://...`) |
| `SECRET_KEY` | Yes | Random secret for signing tokens |
| `GEMINI_API_KEY` | Yes | Google Gemini API key (free tier) |
| `FIREBASE_CREDENTIALS` | Yes | Absolute path to your Firebase service account JSON |
| `SUPABASE_URL` | Yes | Your Supabase project URL (e.g. `https://xxxx.supabase.co`) |
| `SUPABASE_KEY` | Yes | Supabase **service-role** key — keep this server-side only |
| `CALENDAR_MCP_SSE_URL` | Yes | URL of your deployed Google Calendar MCP SSE server |

### Supabase Storage Setup
1. Go to your Supabase dashboard → **Storage** → **New bucket**
2. Name it `health-records`, set it to **Public**
3. The backend will upload files automatically on `/health-records/upload`

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/api/v1/auth/signup` | Register via Firebase token |
| `POST` | `/api/v1/users/patient-profile` | Save / update patient medical profile |
| `POST` | `/api/v1/users/doctor-profile` | Create or update doctor profile |
| `POST` | `/api/v1/chat/run` | Converse with Aura — health diary, Q&A, calendar scheduling |
| `POST` | `/api/v1/health-records/upload` | Upload a prescription image or lab PDF for AI extraction |
| `POST` | `/api/v1/medications/` | Add a medication to the user's regimen |
| `GET` | `/api/v1/medications/` | List the user's medications |
| `GET` | `/api/v1/medications/{id}` | Get a single medication |
| `PATCH` | `/api/v1/medications/{id}` | Update a medication (also stores `google_calendar_event_id`) |
| `DELETE` | `/api/v1/medications/{id}` | Delete a medication |

Full interactive docs available at `/docs` when the server is running.

---

## Architecture: Google Calendar Integration

Calendar reminders use a **network-connected MCP toolset** — no Node.js runs on this server.

```
FastAPI (Render, 512 MB)
  └── AuraAgentService (Google ADK)
        └── McpToolset ──SSE──► Google Calendar MCP Server (separate Render service)
                                    └── Google Calendar API
```

When a user adds a medication, they can tell Aura: *"Set up daily reminders for my Metformin 500mg starting tomorrow."* Aura calls `create-event` through the MCP toolset, which creates a recurring event directly on the user's Google Calendar. The `google_calendar_event_id` is then stored on the medication record for future updates and deletions.

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