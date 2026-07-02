# Aura Health — Backend

A production-ready **Personal Digital Twin** API built with **FastAPI**, **PostgreSQL (Supabase)**, and **Google Gemini 2.5 Flash**. It powers Aura — an AI health navigator that helps patients with chronic illnesses understand their medical data, track lab results over time, manage medications, and stay adherent to their treatment plans.

**Live UI:** [https://aura-health-frontend-five.vercel.app](https://aura-health-frontend-five.vercel.app)  
**Live API:** [https://aura-health-backend-2xhl.onrender.com/health](https://aura-health-backend-2xhl.onrender.com/health)  
**Swagger Docs:** [https://aura-health-backend-2xhl.onrender.com/docs](https://aura-health-backend-2xhl.onrender.com/docs)

---

## What is a Digital Twin?

Each registered patient gets a **Digital Twin** — a live JSONB document in the database that holds their full medical profile: conditions, allergies, current medications, lab history, and daily health logs. Every conversation with Aura is seeded with this profile, so the AI always has complete context without the user having to repeat themselves.

---

## Features

| Feature | Details |
|---|---|
| **Aura AI Navigator** | Conversational health agent powered by Google Gemini 2.5 Flash via Google ADK. Acts as a medical translator, lab-trend analyst, and adherence coach. |
| **Digital Twin Profile** | Patient medical history, allergies, chronic conditions, and daily health logs stored as JSONB and injected into every AI conversation as live context. |
| **Health Record Upload** | Upload prescription images (JPEG, PNG, WEBP, HEIC) or lab-report PDFs (up to 10 MB). Gemini reads the file natively (multimodal) and extracts medications, dosages, diagnoses, and lab results — no separate OCR service needed. |
| **Lab Result Tracking** | Structured lab results (test name, value, unit, reference range, flag) are stored per-upload and surfaced on the home dashboard with trend indicators. |
| **Medication Management** | Full CRUD for a patient's medication regimen — name, dosage, frequency, reminder time, start/end dates, and notes. Drug interaction checking via the RxNav API. |
| **Google Calendar Reminders** | Patients connect their Google Calendar via OAuth. When a medication is added, Aura can schedule recurring reminder events directly on their calendar. Tokens are stored encrypted in the database. |
| **Doctor Profiles** | Doctors can create a platform profile with specialty, qualifications, availability, and location. Patients can browse doctors by specialty. |
| **FHIR Export** | Patient data can be exported as a FHIR R4 Bundle (JSON) for portability. |
| **Firebase Auth** | Stateless Bearer-token authentication using Firebase Admin SDK — no session state on the server. |
| **Supabase Storage** | Uploaded health record files are stored in a Supabase `health-records` bucket. |
| **Database Migrations** | Alembic — runs automatically on every deploy. |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI (async) |
| Database | PostgreSQL via Supabase — SQLAlchemy (async) + asyncpg |
| Migrations | Alembic |
| Auth | Firebase Admin SDK |
| AI Agent | Google ADK + Gemini 2.5 Flash |
| File Storage | Supabase Storage |
| Medical Extraction | Gemini 2.5 Flash multimodal |
| Calendar Integration | Google Calendar OAuth 2.0 — tokens stored encrypted in DB |
| Drug Interactions | RxNav API (NIH, free) |
| Deployment | Render (Docker) + GitHub Actions CI/CD |

---

## Local Development

### Prerequisites
- Python 3.11+
- A [Supabase](https://supabase.com) project (free tier works)
- A Firebase project with a service account key
- Google Cloud project with the Calendar API enabled (for OAuth)

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
| `DATABASE_URL` | Yes | PostgreSQL connection URL (`postgresql+asyncpg://...`) |
| `SECRET_KEY` | Yes | Random secret used for signing internal tokens |
| `GEMINI_API_KEY` | Yes | Google Gemini API key |
| `FIREBASE_CREDENTIALS` | Yes | Path to your Firebase service account JSON file |
| `SUPABASE_URL` | Yes | Your Supabase project URL (e.g. `https://xxxx.supabase.co`) |
| `SUPABASE_KEY` | Yes | Supabase **service-role** key — never expose this client-side |
| `GOOGLE_CLIENT_ID` | Yes | OAuth 2.0 client ID for Google Calendar integration |
| `GOOGLE_CLIENT_SECRET` | Yes | OAuth 2.0 client secret |
| `CALENDAR_REDIRECT_URI` | Yes | The redirect URI registered in Google Cloud Console |
| `CALENDAR_STATE_SECRET` | Yes | Secret used to sign CSRF state tokens for the OAuth flow |
| `TOKEN_ENCRYPTION_KEY` | Yes | Fernet key for encrypting stored Google Calendar tokens |
| `FRONTEND_URL` | Yes | Frontend base URL (used for OAuth redirect after calendar connect) |

### Supabase Storage Setup
1. Go to your Supabase dashboard → **Storage** → **New bucket**
2. Name it `health-records` and set it to **Public**
3. The backend will upload files automatically on `POST /api/v1/health-records/upload`

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/api/v1/auth/signup` | Register a new user via Firebase token |
| `POST` | `/api/v1/users/patient-profile` | Create or update a patient's medical profile (Digital Twin) |
| `POST` | `/api/v1/users/doctor-profile` | Create or update a doctor's platform profile |
| `GET` | `/api/v1/users/me` | Get the current user's profile |
| `PATCH` | `/api/v1/users/me` | Update profile settings (name, timezone, blood type, etc.) |
| `GET` | `/api/v1/users/fhir-export` | Export the patient's Digital Twin as a FHIR R4 Bundle |
| `POST` | `/api/v1/chat/run` | Send a message to Aura — health Q&A, diary logging, calendar scheduling |
| `POST` | `/api/v1/health-records/upload` | Upload a prescription or lab PDF/image for AI extraction |
| `GET` | `/api/v1/health-records/` | List all uploaded health records |
| `GET` | `/api/v1/health-records/labs/timeline` | Get all extracted lab results sorted by date |
| `DELETE` | `/api/v1/health-records/{upload_id}` | Delete a health record and its lab results |
| `POST` | `/api/v1/medications/` | Add a medication to the user's regimen |
| `GET` | `/api/v1/medications/` | List the user's medications |
| `GET` | `/api/v1/medications/{id}` | Get a single medication |
| `PATCH` | `/api/v1/medications/{id}` | Update a medication |
| `DELETE` | `/api/v1/medications/{id}` | Delete a medication |
| `GET` | `/api/v1/calendar/auth` | Get the Google OAuth consent URL for calendar connection |
| `GET` | `/api/v1/calendar/callback` | OAuth callback — exchanges code for tokens |
| `GET` | `/api/v1/calendar/status` | Check if the user has connected Google Calendar |
| `DELETE` | `/api/v1/calendar/revoke` | Disconnect Google Calendar (deletes stored tokens) |

Full interactive docs available at `/docs` when the server is running.

---

## Aura AI Agent

Aura is a **Medical Record Analyst and Adherence Coach** persona built on top of Google ADK and Gemini 2.5 Flash. It is seeded with the user's full Digital Twin profile on every session.

**What Aura can do:**
- **Medical Translator** — Explain lab results, prescriptions, and medical documents in plain, empathetic language.
- **Lab Trend Analyst** — Identify whether values like HbA1c, cholesterol, or kidney function are improving or worsening over time, and suggest relevant questions for the patient's doctor.
- **Adherence Coach** — Help users stay on top of their medication schedules and create Google Calendar reminder events on their behalf.
- **Health Diary** — Gather context through a natural back-and-forth conversation before logging symptoms, mood, vitals, or other health updates into the Digital Twin.
- **Appointment Prep** — Help users build structured question lists based on their recent lab trends and medication changes before a doctor visit.

**Agent Tools:**
| Tool | Description |
|---|---|
| `log_health_update` | Logs a daily health entry (symptoms, vitals, mood, weight, etc.) into the patient's Digital Twin `daily_logs` array. |
| `create_calendar_event` | Creates a recurring medication reminder event on the user's connected Google Calendar. |

---

## Architecture

```
Client (React)
    │  Bearer token (Firebase)
    ▼
FastAPI  ──► Firebase Admin SDK (token verification)
    │
    ├── PostgreSQL (Supabase)       ← Digital Twin, medications, lab results, calendar tokens
    ├── Supabase Storage            ← Uploaded health record files
    │
    └── AuraAgentService (Google ADK)
            └── Gemini 2.5 Flash
                    ├── log_health_update  (direct DB write)
                    └── create_calendar_event  ──► Google Calendar API (OAuth tokens from DB)
```

---

## Deployment (Render)

This project auto-deploys to [Render](https://render.com) on every push to `main` via GitHub Actions.

### First-time setup

1. Push this repo to GitHub.
2. Create a new **Web Service** on Render → connect your GitHub repo → select **Docker** runtime.
3. Add all required environment variables in the Render dashboard (**Environment** tab).
4. Copy the **Deploy Hook URL** from Render's service **Settings** tab.
5. Add it as a GitHub Actions secret named `RENDER_DEPLOY_HOOK_URL`.

After that, every push to `main` will:
1. Run the CI smoke test in GitHub Actions.
2. On success, trigger a Render deploy.
3. Render runs `alembic upgrade head` before swapping traffic.

### CI/CD Pipeline

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
Render: Build Docker image → alembic upgrade head → live
```

---

## License

[MIT](LICENSE)