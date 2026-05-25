# Project Overview

This project is a full-stack data analysis platform with a React frontend and a Flask backend.
The current production deployment uses Render for hosting.

## Main Components

### Frontend

The frontend lives in `frontend/`.

Key responsibilities:

- User authentication pages
- Workspace interface
- Collection and trash views
- Profile page
- Survey creation flow
- Survey fill flow
- Client-side routing with React Router
- API URL resolution through `src/lib/api.js`

Important files:

- `frontend/src/App.jsx`
- `frontend/src/router/config.jsx`
- `frontend/src/lib/api.js`
- `frontend/src/pages/survey/CreateSurveyPage.jsx`
- `frontend/src/pages/survey/FillSurveyPage.jsx`
- `frontend/src/pages/profile/page.jsx`
- `frontend/vite.config.js`

### Backend

The backend lives in `backend/`.

Key responsibilities:

- User registration
- Login and JWT authentication
- Password reset
- Two-factor authentication
- Profile APIs
- Workspace APIs
- Survey APIs
- Database schema bootstrap checks

Important files:

- `backend/app.py`
- `backend/models.py`
- `backend/extensions.py`
- `backend/routes/auth/login.py`
- `backend/routes/auth/register.py`
- `backend/routes/auth/profile.py`
- `backend/routes/auth/survey.py`
- `backend/routes/auth/workspace.py`

## Deployment Shape

The current Render setup separates frontend and backend:

- Frontend static site: `https://one14-data-analysis-frontend.onrender.com`
- Backend API service: `https://one14-data-analysis-uhkg.onrender.com`

The frontend must call backend endpoints through the backend URL, not through the static frontend URL.

Example:

```txt
Correct:
https://one14-data-analysis-uhkg.onrender.com/api/status

Incorrect:
https://one14-data-analysis-frontend.onrender.com/api/status
```

If the frontend static site receives an `/api/...` request, it may return `index.html` because static sites use SPA rewrites.
That response is HTML, not JSON, and will break API flows.

## Survey Flow Summary

### Create Survey

1. User logs in.
2. User opens `/survey/create`.
3. Frontend posts survey data to `POST /api/surveys`.
4. Backend creates a `Survey_Template` record.
5. Backend returns an `access_code`.
6. Frontend shows the invite code and fill link.

### Fill Survey

1. Respondent opens `/survey/fill`.
2. Respondent enters an invite code.
3. Frontend requests `GET /api/surveys/<access_code>`.
4. Backend returns public survey content.
5. Respondent submits answers to `POST /api/surveys/<access_code>/responses`.

## Common Local Notes

The frontend can usually be run with:

```bash
cd frontend
npm install
npm run dev
```

The backend requires a working Python installation and the backend requirements.
If the local virtual environment points to the Windows Store Python launcher, recreate the virtual environment with a real Python installation.

## Files That Should Not Be Committed

Generated files should generally stay out of commits:

- `__pycache__/`
- `*.pyc`
- local virtual environments
- build output
- local environment variable files

Keeping generated files out of commits makes deployment diffs cleaner and prevents confusing review noise.
