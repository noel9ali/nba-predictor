# Scheduler Migration Guide

The daily workflow currently runs via **Windows Task Scheduler**. This guide shows how to swap it out for any other scheduler without changing the core logic.

The scheduler only calls one command:

```
python daily_workflow.py
```

All business logic lives in `daily_workflow.py` and `app.py` — the scheduler is just the trigger.

---

## Current: Windows Task Scheduler

**Setup:** Run once as Administrator:
```powershell
powershell -ExecutionPolicy Bypass -File scheduler\task_scheduler_setup.ps1
```

This registers a job named `NBA-Predictor-Daily` that fires at **6:00 AM** daily.

**Manual test run:**
```powershell
Start-ScheduledTask -TaskName "NBA-Predictor-Daily"
```

**Remove:**
```powershell
Unregister-ScheduledTask -TaskName "NBA-Predictor-Daily" -Confirm:$false
```

---

## Migrating to Linux / macOS cron

1. SSH into your server and activate your virtualenv.
2. Edit crontab:
   ```
   crontab -e
   ```
3. Add a line (runs at 6 AM server time):
   ```
   0 6 * * * cd /path/to/nba-predictor && source venv/bin/activate && python daily_workflow.py >> logs/workflow.log 2>&1
   ```

---

## Migrating to GitHub Actions

Create `.github/workflows/daily.yml`:

```yaml
name: NBA Daily Workflow

on:
  schedule:
    - cron: '0 11 * * *'   # 11:00 UTC = 6:00 AM EST
  workflow_dispatch:         # allow manual trigger from GitHub UI

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run daily workflow
        env:
          ODDS_API_KEY:        ${{ secrets.ODDS_API_KEY }}
          TWILIO_ACCOUNT_SID:  ${{ secrets.TWILIO_ACCOUNT_SID }}
          TWILIO_AUTH_TOKEN:   ${{ secrets.TWILIO_AUTH_TOKEN }}
          TWILIO_FROM:         ${{ secrets.TWILIO_FROM }}
          TWILIO_TO:           ${{ secrets.TWILIO_TO }}
        run: python daily_workflow.py
```

Add all secrets under **Settings → Secrets and variables → Actions**.

---

## Migrating to a Cloud Scheduler (GCP / AWS / Azure)

### Google Cloud Scheduler → Cloud Run Jobs

1. Containerise with a `Dockerfile`:
   ```dockerfile
   FROM python:3.11-slim
   WORKDIR /app
   COPY . .
   RUN pip install -r requirements.txt
   CMD ["python", "daily_workflow.py"]
   ```
2. Push to Google Artifact Registry, create a **Cloud Run Job**.
3. Create a **Cloud Scheduler** job pointing to it with cron `0 11 * * *`.
4. Inject env vars via Secret Manager.

### AWS EventBridge → Lambda / ECS

Same pattern — wire `daily_workflow.py` as the Lambda handler or ECS task entry point, trigger via EventBridge cron rule.

---

## Environment variables needed on any platform

```
ODDS_API_KEY
TWILIO_ACCOUNT_SID
TWILIO_AUTH_TOKEN
TWILIO_FROM
TWILIO_TO
FLASK_SECRET_KEY  (only needed for the web dashboard)
```

See `.env.example` for the full list.
