# Render Frontend Deploy

Create a new Render Static Site from:

```txt
https://github.com/Eileen-HSU/114-data-analysis
```

Use these settings:

```txt
Name: one14-data-analysis-frontend
Branch: main
Root Directory: frontend
Build Command: npm ci && npm run build
Publish Directory: dist
```

Environment variables:

```txt
VITE_API_BASE_URL=https://one14-data-analysis.onrender.com
```

The project also includes `render.yaml`, so Render Blueprint can create the same Static Site automatically.

After deploy, open the new Render Static Site URL, not the old backend URL.
