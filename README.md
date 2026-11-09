# Supplier Capability Hub — HTML + Python API

An internal-tool styled **website** (HTML/CSS/JavaScript) supported by a Python FastAPI backend and session database. **No Streamlit.**

## Included and demonstrated

- The existing corporate-style purple homepage, navigation, overview and supplier workspace
- Four fictional supplier cases; 16 capability criteria in domains A/B/C; comparison of up to three suppliers
- Assessments, questionnaires, eight-stage records, intervention shortlist (21 illustrative research-derived mechanisms)
- Python-calculated intervention matching, assessment coverage, four Step 4 feasibility gates, Siemens and supplier economics
- Server-side validation: missing ratings do not equal zero; financial updates reopen approvals; cannot approve when any gate fails
- Browser-to-backend saving and per-browser session isolation; `Backup session` downloads an export
- API endpoints for future **Copilot Studio** tools; synthetic Snowflake-shaped data only

## Run on a Mac

1. Unzip this folder and open Terminal in it.
2. Install Python packages (Python 3.10+ recommended):

   ```bash
   python3 -m pip install -r requirements.txt
   ```
3. Start the application:

   ```bash
   python3 -m uvicorn server:app --host 127.0.0.1 --port 8000
   ```
4. Open **http://127.0.0.1:8000** in Chrome. The complete HTML site and API are served by the same Python server.

**Don't open `web/index.html` by double-clicking it**—this version requires its backend. The page will explain if the API is unreachable.

Local data is stored in `storage/sessions.sqlite3` unless `DATABASE_PATH` is set. That file is ignored by Git so supplier work doesn't accidentally get committed.

## Host the HTML + backend at one URL: Render

The `render.yaml` file describes a **Free Python Web Service** for a **demonstration**, not production.

1. Create a **new GitHub repository** and upload the *contents* of this folder, including `web/`, `data/`, `server.py`, `requirements.txt` and `render.yaml`. Do not upload it over your old Streamlit-only repository unless you deliberately switch the hosting configuration.
2. At [dashboard.render.com](https://dashboard.render.com), click **New → Blueprint**, connect that GitHub repo, and select `render.yaml`. Alternatively create **New → Web Service** manually with build command `pip install -r requirements.txt` and start command `uvicorn server:app --host 0.0.0.0 --port $PORT`.
3. Set the **`APP_PASSWORD`** secret in Render's environment settings. `render.yaml` deliberately requires you to supply it. The demo username is `supplier-demo`. `REQUIRE_AUTH=1` is set by the blueprint and the server will refuse to start without a password.
4. Render gives you an `https://...onrender.com` link that serves the corporate HTML *and* its API. Test `/healthz` and load the website with the password.
5. Keep the GitHub repository **private**, and get authorization before hosting any Siemens-owned data or source material externally. The supplied cases and Snowflake-shaped records are fictional; the intervention library is a research-derived draft and should still be reviewed before publication.

**Important data limitation:** Render **Free** web services lose local SQLite data when the instance sleeps or redeploys. Your edits can survive a browser reload but **not necessarily a hosting restart**. Use **Backup session** and **Restore** for demo records; restoring resets approval decisions for human review. For durable persistence use a paid Render web service with a persistent disk (`render-persistent.yaml`, review charges before creating) or an approved managed database. Do not use this as a production data system.

Read the current provider documentation for free instance limits: https://render.com/docs/free.

## Architecture

```text
Browser: index.html (HTML/CSS/JavaScript, original corporate interface)
         |  same-origin HTTP requests
         v
Python FastAPI server (server.py) — authentication + validation
         |                   |
         v                   v
SQLite session store   Calculations + intervention scoring
         |                   |
         +---------> JSON response + supplier status

Separate future integrations:
Copilot Studio agent -> approved authenticated API (identity changes required)
Snowflake read-only views -> approved server-side connector (not connected)
```

## API endpoints

- `GET /healthz`: health check, no supplier data
- `GET /api/bootstrap`: session state + authoritative evaluations
- `POST /api/state`: save validated changes (used by the HTML)
- `GET /api/suppliers`, `GET /api/suppliers/{id}`
- `PATCH /api/suppliers/{id}/assessment`
- `PATCH /api/suppliers/{id}/interventions`
- `PATCH /api/suppliers/{id}/business-case`
- `PATCH /api/suppliers/{id}/questionnaire`
- `POST /api/suppliers/{id}/decision`: server validates approval gates
- `GET /api/compare?ids=DEMO-EX-001,DEMO-NEW-002`
- `POST /api/assistant`: deterministic demo response, **not** a connected AI model
- `GET /api/catalog`: synthetic demo catalog + mock supplier data
- `GET /api/export`: download a JSON backup of your session
- `POST /api/import`: restore a session backup (resets approval decisions)
- `POST /api/reset`: restore demo cases to their initial condition
- `GET /openapi.json` and `/api/docs`: API description intended for future integration design

Demo authentication uses HTTP Basic Auth over HTTPS and a secure browser session cookie. For real Siemens deployment replace this with Microsoft Entra ID, fine-grained permissions, tenant approval, audited data access, source licensing review, approved hosting, and a durable database.

## Testing

To run API and browser-code tests:

```bash
python3 -m pip install pytest httpx
python3 -m pytest -q tests/test_api.py
node --check tests/client_script_for_check.js  # generated in release package
```

This environment verified 10 API test cases and a scripted HTML/JS smoke test covering 13 pages, server persistence, and an assistant response. The full interactive site has not yet been visually verified in a live browser in the hosting environment.

## Siemens access boundaries

This package does **not** connect to Siemens Snowflake, Microsoft Copilot Studio, Entra ID, SharePoint, or real supplier systems. Do not describe it as integrated. The API exposes the needed business logic for a later authorized integration; production connectivity is a separate step.
