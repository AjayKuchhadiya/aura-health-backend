# Aura Health — API Contract

**Base URL (Production):** `https://aura-health-backend-2xhl.onrender.com/api/v1`  
**Base URL (Local):** `http://localhost:8000/api/v1`  
**Interactive Docs:** `{base_url_no_version}/docs`

---

## Authentication

Every endpoint (except `/calendar/callback`) requires a Firebase ID token:

```
Authorization: Bearer <firebase_id_token>
```

The token is obtained from Firebase Auth after sign-in on the client.

---

## Endpoints

### Auth

#### `POST /auth/signup`
Register a new user in the database after Firebase sign-up. Call **once only** on first sign-up.

**Request**
```json
{
  "name": "John Doe",
  "role": "patient"
}
```
`role` must be `"patient"` or `"doctor"`.

**Response `201`**
```json
{
  "id": 11,
  "firebase_uid": "abc123",
  "email": "john@example.com",
  "name": "John Doe",
  "role": "patient"
}
```

---

### Users

#### `POST /users/patient-profile`
Create or update the patient's medical profile (Digital Twin). Stores the full payload in a JSONB column.

**Request**
```json
{
  "full_name": "John Doe",
  "date_of_birth": "1990-05-14",
  "gender": "male",
  "blood_type": "O+",
  "allergies": ["Penicillin"],
  "chronic_conditions": ["Type 2 Diabetes"],
  "current_medications": ["Metformin 500mg"],
  "emergency_contact": {
    "name": "Jane Doe",
    "phone": "+1234567890",
    "relationship": "Spouse"
  }
}
```

**Response `200`**
```json
{
  "message": "Patient profile created successfully",
  "data": { ...user object with medical_profile... }
}
```

---

### Chat (AI Agent)

#### `POST /chat/`
Send a message to Aura, the AI Health Companion. Maintains conversation history per session.

**Request**
```json
{
  "message": "Add Metformin 500mg once daily and remind me at 8am starting 2026-06-15",
  "session_id": "optional-uuid-to-continue-a-conversation",
  "location": {
    "latitude": 37.7749,
    "longitude": -122.4194,
    "city": "San Francisco",
    "country": "US",
    "timezone": "America/Los_Angeles"
  }
}
```

- `session_id` — omit on first message; reuse the returned value to continue the conversation.
- `location` — optional; used by Aura to find nearby doctors.

**Response `200`**
```json
{
  "reply": "I've scheduled a daily reminder for Metformin 500mg at 8:00 AM...",
  "session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**What Aura can do via chat:**
- Log daily health updates (symptoms, weight, blood pressure, mood, sleep)
- Explain prescriptions and lab results in plain language
- Find nearby doctors or Aura platform doctors by specialty
- Schedule medication reminders on Google Calendar (if calendar is connected)
- Help prepare questions for doctor appointments

---

### Medications

All medication endpoints are scoped to the authenticated user — users can only access their own records.

#### `POST /medications/`
Add a new medication to the user's regimen.

**Request**
```json
{
  "medication_name": "Metformin",
  "dosage": "500mg",
  "frequency": "once daily",
  "start_date": "2026-06-15",
  "end_date": null,
  "notes": "Take with food"
}
```
`frequency` values Aura understands for calendar scheduling: `"once daily"`, `"twice daily"`, `"weekly"`, `"monthly"`.

**Response `201`**
```json
{
  "id": 3,
  "user_id": 11,
  "medication_name": "Metformin",
  "dosage": "500mg",
  "frequency": "once daily",
  "start_date": "2026-06-15",
  "end_date": null,
  "notes": "Take with food",
  "google_calendar_event_id": null,
  "created_at": "2026-06-14T19:45:00",
  "updated_at": "2026-06-14T19:45:00"
}
```

> After creating a medication, send a follow-up message to Aura via `POST /chat/` asking it to schedule reminders — it will call the Calendar tool automatically using the user's connected Google Calendar.

---

#### `GET /medications/`
List all medications for the authenticated user, newest first.

**Response `200`**
```json
[
  {
    "id": 3,
    "user_id": 11,
    "medication_name": "Metformin",
    "dosage": "500mg",
    "frequency": "once daily",
    "start_date": "2026-06-15",
    "end_date": null,
    "notes": "Take with food",
    "google_calendar_event_id": "abc123_google_event_id",
    "created_at": "2026-06-14T19:45:00",
    "updated_at": "2026-06-14T19:45:00"
  }
]
```

---

#### `GET /medications/{medication_id}`
Get a single medication record.

**Response `200`** — same shape as the item above.  
**Response `404`** — medication not found or doesn't belong to this user.

---

#### `PATCH /medications/{medication_id}`
Partially update a medication. Send only the fields you want to change.

**Request**
```json
{
  "dosage": "1000mg",
  "notes": "Increased dose per doctor",
  "google_calendar_event_id": "abc123_google_event_id"
}
```
Use `google_calendar_event_id` to store the Calendar event ID returned by Aura after scheduling, so it can be updated/deleted later.

**Response `200`** — full updated medication object.

---

#### `DELETE /medications/{medication_id}`
Delete a medication record.

**Response `204 No Content`**

> To also delete the Google Calendar event, send Aura a chat message: *"Delete calendar event abc123_google_event_id"*

---

### Health Records

#### `POST /health-records/upload`
Upload a prescription image or lab report PDF. Aura extracts structured data via Gemini AI and stores it in the user's Digital Twin.

**Request** — `multipart/form-data`

| Field | Type | Description |
|-------|------|-------------|
| `file` | file | The document to upload |

**Allowed MIME types:** `image/jpeg`, `image/png`, `image/webp`, `image/heic`, `application/pdf`  
**Max size:** 10 MB

**Response `201`**
```json
{
  "file_url": "https://ldsvdefrwtblgnalbvrr.supabase.co/storage/v1/object/public/health-records/11/abc.pdf",
  "extraction": {
    "medications": ["Metformin 500mg twice daily"],
    "diagnoses": ["Type 2 Diabetes Mellitus"],
    "lab_results": [],
    "doctor_name": "Dr. Sarah Johnson",
    "clinic_name": "City Health Clinic",
    "document_date": "2026-05-20",
    "notes": "Follow-up in 3 months"
  },
  "message": "Health record uploaded and extracted successfully."
}
```

The extracted data is automatically merged into the user's `medical_profile` Digital Twin so Aura has context in future conversations.

---

### Google Calendar Integration

Users connect **their own** Google Calendar via OAuth. Tokens are encrypted and stored per-user. Once connected, Aura can create medication reminder events directly in that user's calendar.

---

#### `GET /calendar/auth`
**Step 1** — Get the Google OAuth consent URL to send the user to.

Requires: `Authorization: Bearer <firebase_token>`

**Response `200`**
```json
{
  "auth_url": "https://accounts.google.com/o/oauth2/v2/auth?...",
  "message": "Open this URL in a browser to connect your Google Calendar."
}
```

**Frontend flow:**
```
1. GET /calendar/auth  →  receive auth_url
2. Open auth_url in browser / WebView
3. User signs in with Google and grants Calendar access
4. Google redirects to /calendar/callback automatically
5. Backend saves encrypted tokens → redirects to frontend with ?calendar_connected=true
```

---

#### `GET /calendar/callback`
**Step 2** — Google redirects here automatically. The frontend does **not** call this directly.

After success, redirects browser to:
```
https://aura-health-frontend-five.vercel.app?calendar_connected=true
```

---

#### `GET /calendar/status`
Check whether the authenticated user has connected their Google Calendar.

**Response `200` — connected**
```json
{
  "connected": true,
  "google_email": "john@gmail.com",
  "granted_at": "2026-06-14T19:45:43"
}
```

**Response `200` — not connected**
```json
{
  "connected": false,
  "google_email": null
}
```

---

#### `DELETE /calendar/revoke`
Disconnect the user's Google Calendar. Deletes stored tokens from DB and revokes them at Google.

**Response `204 No Content`**

---

## Error Responses

All errors follow this shape:

```json
{
  "detail": "Human-readable error message"
}
```

| Status | Meaning |
|--------|---------|
| `400` | Bad request / validation error |
| `401` | Missing or invalid Firebase token |
| `403` | Forbidden |
| `404` | Resource not found |
| `413` | File too large (> 10 MB) |
| `502` | Upstream service error (Google, Supabase) |
| `503` | Feature not configured on server |

---

## Suggested Frontend Flow (New User)

```
1. Firebase signup / login
2. POST /auth/signup              ← create DB record (first time only)
3. POST /users/patient-profile    ← save medical profile
4. GET  /calendar/auth            ← get consent URL
5. Open consent URL in browser    ← user grants Google Calendar access
6. Show calendar_connected=true   ← backend redirected here after success
7. POST /medications/             ← add medications
8. POST /chat/  "Schedule reminders for Metformin at 8am" ← Aura creates calendar events
9. POST /health-records/upload    ← upload prescriptions/lab reports
10. POST /chat/ (ongoing)         ← chat with Aura for health guidance
```
