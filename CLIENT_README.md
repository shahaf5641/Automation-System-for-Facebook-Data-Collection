# Facebook Data Extractor - Client Guide

## What This System Is

This system runs as a Docker-based web app.

It includes:
- a Flask web app
- Redis for queue and live job state
- PostgreSQL for run history
- Selenium + Chrome for Facebook automation

## What You Need

- Docker Desktop
- Internet connection
- A Facebook account
- ngrok (optional, only if you want to share the app publicly)

## Start The System

From the project folder:

```powershell
docker compose up --build -d
```

## Open The System

Main app:

```text
http://localhost:5000
```

Selenium browser view:

```text
http://localhost:7900
```

## How To Use It

1. Open `http://localhost:5000`
2. Fill in:
   - `Search in Facebook`
   - `Group links number`
   - `Posts from each group`
3. Click `Run`
4. If Facebook login is required, open `http://localhost:7900`
5. Log in there and let the automation continue
6. When the run finishes, download the CSV from the app
7. Use `My Runs` if you want to download or delete older runs

## Output

CSV files are created in:

- `web_outputs\facebookposts-<job_id>.csv`

The app also lets you download the CSV directly from the UI.

## Share With Other Devices

If you want to share the system outside your machine:

```powershell
ngrok http 5000
```

Send the generated `https://...ngrok...` URL.

## Stop The System

```powershell
docker compose down
```

## Hard Reset

```powershell
docker compose down -v
docker compose up --build -d
```

## Notes

- `localhost:5000` is the app itself
- `localhost:7900` is the Selenium browser view
- You only need `7900` when login or browser inspection is needed
- Run history is stored in PostgreSQL
- Live queue/job state is stored in Redis
- You can delete one run or all runs from the `My Runs` section
