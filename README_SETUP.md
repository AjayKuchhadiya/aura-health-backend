# Aura Health Backend

A FastAPI-based backend for the Aura Health application with support for user management, ambulance dispatch, and document processing.

## Features

- **User Authentication**: Registration and login functionality
- **User Management**: CRUD operations for user profiles
- **Ambulance Dispatch**: Search and request ambulances
- **OCR Processing**: Document scanning and text extraction
- **Cloud Storage**: R2/S3 integration for file uploads
- **Async Database**: SQLAlchemy async support with PostgreSQL

## Project Structure

```
aura-health-backend/
├── alembic/                    # Database migrations
├── app/
│   ├── api/
│   │   └── v1/
│   │       ├── endpoints/      # Route handlers
│   │       │   ├── auth.py
│   │       │   ├── users.py
│   │       │   └── ambulance.py
│   │       └── router.py       # API router aggregator
│   ├── core/
│   │   ├── config.py          # Configuration (env vars)
│   │   └── database.py        # Database setup
│   ├── models/                # SQLAlchemy models
│   │   ├── user.py
│   │   └── doctor.py
│   ├── schemas/               # Pydantic validation models
│   │   ├── user.py
│   │   └── doctor.py
│   ├── services/              # Business logic
│   │   ├── ocr.py
│   │   ├── ambulance.py
│   │   └── storage.py
│   └── main.py                # FastAPI app entry point
├── .env                       # Environment variables (local)
├── .gitignore
├── alembic.ini               # Alembic configuration
├── Dockerfile                # Docker configuration
├── fly.toml                  # Fly.io deployment config
└── requirements.txt          # Python dependencies
```

## Getting Started

### Prerequisites

- Python 3.11+
- PostgreSQL
- pip

### Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd aura-health-backend
```

2. Create virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your configuration
```

5. Run database migrations:
```bash
alembic upgrade head
```

6. Start the development server:
```bash
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`

## API Documentation

Once the server is running, visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Environment Variables

Create a `.env` file with the following variables:

```
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/aura_health
SECRET_KEY=your-secret-key
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_S3_BUCKET_NAME=your-bucket-name
GOOGLE_VISION_API_KEY=your-vision-api-key
```

## Deployment

### Docker

Build and run with Docker:
```bash
docker build -t aura-health-backend .
docker run -p 8000:8000 --env-file .env aura-health-backend
```

### Fly.io

Deploy to Fly.io:
```bash
flyctl deploy
```

## Contributing

1. Create a feature branch
2. Make your changes
3. Submit a pull request

## License

See LICENSE file for details.
