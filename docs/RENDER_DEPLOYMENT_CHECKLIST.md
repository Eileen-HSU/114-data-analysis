# Render Deployment Checklist

Use this checklist before and after deploying the project to Render.

## Frontend Static Site

Expected settings:

```txt
Service type: Static Site
Root directory: frontend
Build command: npm ci && npm run build
Publish directory: dist
Branch: main
```

Recommended environment variable:

```txt
VITE_API_BASE_URL=https://one14-data-analysis-uhkg.onrender.com
```

The frontend also has a production fallback in `frontend/src/lib/api.js` for the Render frontend hostname.
The environment variable is still recommended because it is explicit and easier to verify.

## Backend Web Service

Expected settings:

```txt
Service type: Web Service
Root directory: backend
Runtime: Python
```

The exact start command depends on the Render service configuration.
A typical Flask production command is:

```txt
gunicorn app:app
```

Required environment variables usually include:

```txt
DATABASE_URL=...
JWT_SECRET_KEY=...
```

Mail-related values may also be required depending on which authentication flows are used.

## Post-Deploy Checks

After backend deploy:

```txt
https://one14-data-analysis-uhkg.onrender.com/api/status
```

Expected response:

```json
{
  "database": "Connected",
  "environment": "Production",
  "status": "online"
}
```

After frontend deploy:

```txt
https://one14-data-analysis-frontend.onrender.com/
```

The page should load the latest asset bundle.
If the page still behaves like an older version, wait for Render and Cloudflare cache to refresh, or redeploy manually.

## API Routing Check

This URL should return frontend HTML because it is the static site:

```txt
https://one14-data-analysis-frontend.onrender.com/api/status
```

This URL should return backend JSON:

```txt
https://one14-data-analysis-uhkg.onrender.com/api/status
```

If the survey page receives HTML when expecting JSON, the frontend is probably calling the wrong base URL.

## Survey Invite Code Check

When survey invite codes fail:

1. Confirm the backend service is online.
2. Confirm the frontend was redeployed after the latest commit.
3. Confirm the invite code is copied exactly.
4. Test the public survey API directly:

```txt
https://one14-data-analysis-uhkg.onrender.com/api/surveys/<ACCESS_CODE>
```

Expected outcomes:

- `200`: survey exists and is available.
- `404`: invite code does not match an active survey.
- `410`: survey deadline has passed.
- `500`: backend error; check Render logs.

## Manual Redeploy Notes

If auto deploy is disabled:

1. Open the Render service.
2. Select the latest commit from GitHub.
3. Click manual deploy.
4. Wait until the deploy status is live.
5. Re-test the status URL.

Deploying only the frontend will not update backend route behavior.
Deploying only the backend will not update frontend JavaScript behavior.
