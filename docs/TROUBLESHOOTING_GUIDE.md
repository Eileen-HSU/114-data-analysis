# Troubleshooting Guide

This guide lists common problems, likely causes, and practical checks.
It is written for local development, Render deployment, and demo preparation.

## Quick Diagnosis Table

| Symptom | Likely Cause | First Check |
| --- | --- | --- |
| Frontend loads but API fails | Wrong API base URL | Check backend URL in browser devtools |
| `/api/status` returns HTML | Request hit frontend static site | Use backend Render URL |
| Invite code not found | Code does not exist or wrong database | Test backend survey endpoint |
| Invite code causes server error | Backend route exception | Check Render backend logs |
| Survey is expired | Deadline passed | Check survey deadline |
| Login fails | Token, credential, or backend issue | Check login response |
| Build fails | Dependency or syntax issue | Run frontend build locally |
| Render deploy fails | Wrong root/build command | Check Render logs |
| Local backend cannot run | Broken Python virtual environment | Recreate `.venv` |

## Frontend Problems

### Frontend Page Is Blank

Possible causes:

- JavaScript bundle failed to load.
- React render crashed.
- Static assets are missing.
- Browser cached an old bundle.

Checks:

1. Open browser devtools.
2. Check Console tab.
3. Check Network tab.
4. Confirm `index.html` references existing assets.
5. Hard refresh the page.

Commands:

```bash
cd frontend
npm run build
```

If build succeeds locally but production is broken:

- Confirm Render deployed the latest commit.
- Confirm publish directory is `dist`.
- Confirm root directory is `frontend`.

### Frontend Shows Old Version

Possible causes:

- Render has not redeployed yet.
- Browser cache is stale.
- Cloudflare/edge cache is still serving old HTML.

Checks:

1. Open Render deploy list.
2. Confirm latest Git commit hash.
3. Hard refresh the browser.
4. Open in incognito mode.
5. Wait several minutes and retry.

### API Call Returns HTML

This is a common production issue.

Expected backend API response:

```json
{
  "status": "online"
}
```

Wrong response:

```html
<!doctype html>
<html>
```

Cause:

The frontend called the static site URL:

```txt
https://one14-data-analysis-frontend.onrender.com/api/status
```

Instead of backend URL:

```txt
https://one14-data-analysis-uhkg.onrender.com/api/status
```

Fix:

- Set `VITE_API_BASE_URL`.
- Confirm `frontend/src/lib/api.js` fallback logic.
- Redeploy frontend.

### Survey Fill Page Cannot Load Survey

Possible causes:

- Wrong API base URL.
- Invite code does not exist.
- Survey is inactive.
- Survey is expired.
- Backend raised an exception.

Checks:

1. Copy the invite code.
2. Test direct backend URL:

```txt
https://one14-data-analysis-uhkg.onrender.com/api/surveys/<ACCESS_CODE>
```

3. Interpret status:

```txt
200 means active
404 means not found
410 means expired
500 means backend error
```

4. Check browser network response.

### Frontend Build Warning About Tailwind

Observed warning:

```txt
[lightningcss minify] Unknown at rule: @tailwind
```

Meaning:

- Build can still complete.
- This is a warning, not necessarily a failure.
- The CSS toolchain may not be processing Tailwind directives exactly as expected.

Action:

- If output CSS looks correct, do not change during a demo.
- If styling breaks, review PostCSS and Tailwind configuration.

## Backend Problems

### Backend Health Check Fails

Check:

```bash
curl -i https://one14-data-analysis-uhkg.onrender.com/api/status
```

Possible causes:

- Render backend is sleeping.
- Deploy failed.
- App crashed during startup.
- Database connection failed.
- Required environment variable missing.

Actions:

1. Wait for Render cold start.
2. Check Render logs.
3. Confirm environment variables.
4. Confirm database URL.
5. Redeploy backend.

### Backend Starts Locally But Production Fails

Possible causes:

- Missing production environment variables.
- Database SSL settings differ.
- Python version differs.
- Render root directory differs.
- Start command differs.

Checks:

- Render root directory should point to backend if backend is a separate service.
- Start command should launch Flask through Gunicorn.
- `DATABASE_URL` should be valid.
- `JWT_SECRET_KEY` should be set.

### Backend Fails Locally

Observed local issue:

The virtual environment may point to the Windows Store Python launcher.

Possible error:

```txt
Unable to create process using WindowsApps Python...
```

Fix:

1. Install real Python from python.org.
2. Recreate virtual environment.
3. Install requirements.

Typical commands:

```bash
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python app.py
```

Do not perform this during a time-sensitive demo unless necessary.

### Database Connection Error

Possible causes:

- `DATABASE_URL` missing.
- Database service unavailable.
- SSL option incompatible.
- Credentials changed.
- Network restriction.

Checks:

- Confirm Render env vars.
- Confirm database provider dashboard.
- Confirm backend logs.
- Confirm `app.py` database URL normalization.

### Runtime Schema Check Error

The backend attempts to ensure some columns exist at startup.

Possible affected columns:

- `User.email_2fa_enabled`
- `User_Verification.attempts`
- `Workspace.is_deleted`
- `Workspace.deleted_at`
- `Survey_Template.user_id`
- `Survey_Template.due_date`
- `Survey_Template.is_anonymous`

If startup logs show schema check failure:

- Check database permissions.
- Check table names.
- Check column definitions.
- Confirm database dialect compatibility.

## Survey Problems

### Invite Code Returns 404

Meaning:

The backend did not find an active survey with that code.

Possible causes:

- Code copied incorrectly.
- Survey was created in another database.
- Survey creation failed.
- Survey is inactive.
- Frontend is using stale local data.

Checks:

1. Confirm exact invite code.
2. Test backend URL directly.
3. Create a new survey and test immediately.
4. Check Render backend logs.

### Invite Code Returns 410

Meaning:

The survey deadline has passed.

Actions:

- Extend the survey deadline from profile if supported.
- Create a new survey.
- Confirm the device time is reasonable.

### Invite Code Returns 500

Meaning:

The backend encountered an exception.

Likely areas:

- Deadline parsing.
- Timezone comparison.
- Database query.
- JSON field shape.

Actions:

1. Check Render backend logs.
2. Copy the error detail if returned.
3. Reproduce with direct API URL.
4. Fix backend route.
5. Redeploy backend.

### Response Submission Fails

Possible causes:

- Missing `answers`.
- Survey expired between load and submit.
- Backend database write failed.
- API base URL is wrong.

Checks:

- Browser Network tab.
- Response status code.
- Request payload.
- Backend logs.

### Survey Shows Zero Questions

Possible causes:

- Backend stored question JSON under unexpected key.
- Frontend expects `questions`, backend returns empty list.
- Survey creation payload had empty questions.

Expected backend stored structure:

```json
{
  "description": "...",
  "identity_mode": "anonymous",
  "items": []
}
```

Expected public API response:

```json
{
  "questions": []
}
```

If questions are missing:

- Confirm create survey payload.
- Confirm backend saved `items`.
- Confirm get survey route returns `items` as `questions`.

## Authentication Problems

### Token Missing

Possible causes:

- User is not logged in.
- Local storage was cleared.
- Login response did not include token.

Checks:

- Inspect local storage key `dataanalysis_auth`.
- Log in again.
- Confirm Authorization header in Network tab.

### Token Expired

Possible behavior:

- Backend returns `401`.
- Frontend redirects to login.
- Protected API calls fail.

Actions:

- Log in again.
- Confirm local storage was refreshed.

### Two-Factor Problems

Possible causes:

- Code expired.
- Wrong code.
- Email delivery delayed.
- Verification attempts exceeded.

Actions:

- Request a new code.
- Check spam folder.
- Confirm backend mail provider configuration.

## Render Problems

### Deploy Does Not Start

Possible causes:

- Auto deploy disabled.
- Wrong branch.
- GitHub integration disconnected.

Actions:

- Trigger manual deploy.
- Confirm branch is `main`.
- Confirm repository access.

### Deploy Fails During Build

Frontend checks:

- Root directory is `frontend`.
- Build command is `npm ci && npm run build`.
- Publish directory is `dist`.

Backend checks:

- Root directory is `backend`.
- Dependencies exist in `requirements.txt`.
- Start command is valid.
- Python runtime is supported.

### Deploy Succeeds But App Fails

Possible causes:

- Missing env vars.
- Runtime exception after startup.
- API base URL mismatch.
- Database unavailable.

Actions:

- Check logs after deploy.
- Hit `/api/status`.
- Hard refresh frontend.

## Git Problems

### Push Rejected

Message:

```txt
Updates were rejected because the remote contains work that you do not have locally.
```

Fix:

```bash
git pull --rebase --autostash origin main
git push origin main
```

### Only `__pycache__` Files Are Modified

Meaning:

Python generated bytecode files changed.

Recommendation:

- Do not commit them.
- Add ignore rules if safe.
- Remove tracked generated files only in a planned cleanup commit.

### Index Lock Error

Message:

```txt
Unable to create .git/index.lock
```

Possible causes:

- Another Git process is running.
- IDE is using Git.
- OneDrive temporarily locked the folder.

Actions:

- Wait and retry.
- Close Git UI operations.
- Avoid deleting lock files unless sure no Git process is active.

## Demo Recovery Plan

If something breaks during a presentation:

1. Use the production frontend URL.
2. Check backend `/api/status`.
3. If backend is sleeping, wait and refresh.
4. If survey code fails, create a new survey.
5. If login fails, use a backup test account.
6. If production deploy is broken, show local screenshots or documentation.
7. Keep the troubleshooting guide open for status code interpretation.

## Safe Change Policy

When the app is already working:

- Avoid large formatting changes.
- Avoid dependency upgrades.
- Avoid changing database schema unless necessary.
- Avoid changing deployment config before a demo.
- Prefer documentation updates.
- Prefer targeted bug fixes.

## Escalation Notes

Ask for help or stop changing code when:

- A database migration may be needed.
- Production data could be affected.
- Authentication behavior changes.
- The fix requires deleting files.
- The fix requires force-pushing.
- Render logs show unknown repeated crashes.
