# API Reference

This document summarizes the backend API surface used by the frontend.
It focuses on request shape, response shape, common failure modes, and manual test notes.

The production backend base URL is:

```txt
https://one14-data-analysis-uhkg.onrender.com
```

For local development, the backend usually runs on:

```txt
http://localhost:5000
```

## General Rules

### Content Type

Most write endpoints expect JSON:

```http
Content-Type: application/json
```

### Authentication

Protected endpoints expect a JWT bearer token:

```http
Authorization: Bearer <TOKEN>
```

Public survey fill endpoints do not require login.
This allows respondents to fill a survey by invite code.

### Common Response Codes

```txt
200 OK
201 Created
400 Bad Request
401 Unauthorized
404 Not Found
410 Gone
500 Internal Server Error
```

### CORS

The backend allows frontend calls under `/api/*`.
If a browser request fails before reaching Flask, check the browser console for CORS messages.

## Health Check

### GET `/api/status`

Checks whether the backend service is online.

Example:

```bash
curl https://one14-data-analysis-uhkg.onrender.com/api/status
```

Expected response:

```json
{
  "database": "Connected",
  "environment": "Production",
  "status": "online"
}
```

Notes:

- This endpoint does not verify every feature.
- It is a quick deployment check.
- If this endpoint returns HTML, the request likely hit the frontend static site instead of the backend.

## Authentication APIs

The authentication routes are split across several backend files:

```txt
backend/routes/auth/register.py
backend/routes/auth/login.py
backend/routes/auth/pwd.py
backend/routes/auth/two_factor.py
```

The exact request payloads should be verified against those route files before changing the frontend.
The frontend pages using these routes live in:

```txt
frontend/src/pages/auth/
```

### Login Flow

Typical frontend flow:

1. User enters email and password.
2. Frontend posts credentials to the login endpoint.
3. Backend verifies credentials.
4. Backend returns token and user data.
5. Frontend stores auth data in local storage.
6. If two-factor authentication is required, frontend routes user to the 2FA flow.

Expected frontend storage key:

```txt
dataanalysis_auth
```

Manual validation:

- Try correct credentials.
- Try wrong password.
- Try unknown email.
- Try empty email.
- Try empty password.
- Confirm the UI shows friendly error messages.

### Register Flow

Typical frontend flow:

1. User enters registration data.
2. Frontend posts registration request.
3. Backend creates the account or returns validation errors.
4. Frontend moves user to login or verification flow.

Manual validation:

- Register with a new email.
- Register with an existing email.
- Register with invalid email format.
- Register with weak password if validation exists.
- Confirm duplicate email is handled.

### Password Reset Flow

Typical frontend flow:

1. User opens forgot password page.
2. User requests a reset code.
3. Backend creates a verification record.
4. User submits reset code and new password.
5. Backend updates password hash.

Manual validation:

- Request reset for existing email.
- Request reset for unknown email.
- Submit valid reset code.
- Submit expired reset code.
- Submit reused reset code.
- Submit mismatched password fields if the frontend has confirmation fields.

### Two-Factor Flow

Typical frontend flow:

1. User logs in.
2. Backend indicates two-factor verification is required.
3. Frontend sends or verifies a 2FA code.
4. Backend returns successful authentication state.

Manual validation:

- Enable 2FA.
- Login with 2FA enabled.
- Submit valid 2FA code.
- Submit invalid 2FA code.
- Submit expired 2FA code.
- Disable 2FA if the user is authenticated.

## Profile APIs

Profile functionality is used by:

```txt
frontend/src/pages/profile/page.jsx
frontend/src/pages/profile/components/
```

Typical features:

- Read user profile.
- Update profile details.
- Display survey records owned by the user.
- Display recent activity.
- View survey details.
- Update survey deadline.

Manual validation:

- Load profile while logged in.
- Load profile without token.
- Update profile fields.
- Refresh page after updating.
- Confirm local activity display does not break.

## Workspace APIs

Workspace functionality is used by:

```txt
frontend/src/pages/workspace/page.jsx
backend/routes/auth/workspace.py
```

Typical features:

- Create workspace.
- List workspaces.
- Update workspace.
- Soft-delete workspace.
- Restore deleted workspace.
- Attach survey content for analysis.

Manual validation:

- Create a workspace.
- Rename a workspace.
- Delete a workspace.
- Restore a workspace if supported.
- Confirm deleted workspaces do not appear in active lists.

## Survey APIs

Survey APIs are central to the current project.

Backend file:

```txt
backend/routes/auth/survey.py
```

Frontend files:

```txt
frontend/src/pages/survey/CreateSurveyPage.jsx
frontend/src/pages/survey/FillSurveyPage.jsx
frontend/src/pages/profile/page.jsx
frontend/src/pages/profile/components/SurveyDetailPage.jsx
```

## Create Survey

### POST `/api/surveys`

Creates a new survey template.

Authentication:

```txt
Required
```

Headers:

```http
Authorization: Bearer <TOKEN>
Content-Type: application/json
```

Example request:

```json
{
  "title": "Product Satisfaction Survey",
  "description": "A short survey for product feedback.",
  "identity_mode": "anonymous",
  "deadline_at": "2026-06-01T18:00",
  "questions": [
    {
      "id": "question-1",
      "type": "short",
      "title": "What did you like most?",
      "required": true,
      "options": []
    }
  ],
  "user_id": 1
}
```

Successful response:

```json
{
  "message": "問卷建立成功",
  "access_code": "A1B2C",
  "template_id": 10
}
```

Validation rules:

- `title` is required.
- `questions` must be a list.
- `deadline_at` is required.
- Deadline must be in the future.
- `identity_mode` must be `anonymous` or `identified`.

Possible failures:

```txt
400 missing title/questions/deadline
400 invalid deadline format
400 deadline is not in the future
401 missing or invalid token
500 database or server error
```

Manual test cases:

- Create anonymous survey.
- Create identified survey.
- Create survey with one short question.
- Create survey with one rating question.
- Create survey with empty title.
- Create survey with past deadline.
- Create survey without token.

## Get Public Survey

### GET `/api/surveys/<access_code>`

Reads public survey content by invite code.

Authentication:

```txt
Not required
```

Example:

```bash
curl https://one14-data-analysis-uhkg.onrender.com/api/surveys/A1B2C
```

Successful response:

```json
{
  "template_id": 10,
  "title": "Product Satisfaction Survey",
  "description": "A short survey for product feedback.",
  "identity_mode": "anonymous",
  "deadline_at": "2026-06-01T18:00:00+08:00",
  "questions": [
    {
      "id": "question-1",
      "type": "short",
      "title": "What did you like most?",
      "required": true,
      "options": []
    }
  ],
  "access_code": "A1B2C",
  "created_at": "2026-05-25T12:00:00+08:00"
}
```

Possible failures:

```txt
404 survey not found
410 survey expired
500 server error
```

Important notes:

- The invite code is normalized to uppercase.
- The backend trims accidental spaces.
- Expired surveys return `410 Gone`.
- Public survey content should not require login.

Manual test cases:

- Existing active code.
- Existing expired code.
- Invalid code.
- Lowercase code.
- Code with spaces.

## Update Survey Deadline

### PATCH `/api/surveys/<access_code>/deadline`

Updates the deadline for an existing survey.

Authentication:

```txt
Required
```

Headers:

```http
Authorization: Bearer <TOKEN>
Content-Type: application/json
```

Example request:

```json
{
  "deadline_at": "2026-06-10T20:30"
}
```

Successful response:

```json
{
  "message": "截止時間已更新",
  "access_code": "A1B2C",
  "deadline_at": "2026-06-10T20:30:00+08:00"
}
```

Possible failures:

```txt
400 invalid deadline format
400 deadline is not in the future
401 unauthorized
404 survey not found
500 update failed
```

Manual test cases:

- Update to a future deadline.
- Update to a past deadline.
- Update with missing token.
- Update invalid invite code.
- Confirm fill page respects new deadline.

## Submit Survey Response

### POST `/api/surveys/<access_code>/responses`

Submits respondent answers.

Authentication:

```txt
Not required
```

Headers:

```http
Content-Type: application/json
```

Example request:

```json
{
  "answers": {
    "question-1": "The interface was clear."
  },
  "respondent_identity": ""
}
```

Successful response:

```json
{
  "message": "問卷送出成功",
  "response_id": 25
}
```

Possible failures:

```txt
400 missing answers
404 invite code not found
410 survey expired
500 submission failed
```

Manual test cases:

- Submit anonymous response.
- Submit identified response.
- Submit missing answers object.
- Submit after deadline.
- Submit invalid invite code.

## Frontend API Helper

The frontend resolves API URLs through:

```txt
frontend/src/lib/api.js
```

Expected behavior:

- Use `VITE_API_BASE_URL` when it is set.
- Fall back to backend Render URL when running on the production frontend Render hostname.
- Use relative API paths for local development and Vite proxy behavior.

This helps avoid accidentally calling:

```txt
https://one14-data-analysis-frontend.onrender.com/api/...
```

The static frontend site may return `index.html` for that path, which breaks JSON parsing.

## Debugging API Responses

When something fails, check the actual response first.

Health check:

```bash
curl -i https://one14-data-analysis-uhkg.onrender.com/api/status
```

Survey lookup:

```bash
curl -i https://one14-data-analysis-uhkg.onrender.com/api/surveys/A1B2C
```

Frontend static site check:

```bash
curl -i https://one14-data-analysis-frontend.onrender.com/api/status
```

Expected difference:

- Backend URL returns JSON.
- Frontend static URL returns HTML.

## API Change Checklist

Before changing any API route:

- Confirm the frontend file that calls the route.
- Confirm the request payload shape.
- Confirm the response shape.
- Confirm status codes.
- Confirm whether authentication is required.
- Confirm CORS behavior.
- Confirm Render environment variables.
- Add or update this document if behavior changes.

After changing any API route:

- Run frontend build.
- Test backend health.
- Test route manually with `curl`.
- Test route through the browser UI.
- Push to GitHub.
- Wait for Render deploy.
- Re-test production URL.
