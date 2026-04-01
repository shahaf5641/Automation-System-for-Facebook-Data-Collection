# Facebook Data Extractor

Web-based Facebook groups scraper that opens Chrome, searches groups, extracts posts, and exports CSV.

## Quick Start

For the full startup flow, see:

- [RUN_SYSTEM.md](/C:/Users/shaha/Desktop/facebook-scraper-polished/RUN_SYSTEM.md)

## System Flow

![System Flow](docs/system-flow.png)

## What This Project Does

- Searches Facebook groups by your search phrase
- Enables `Public groups` filter before collecting links
- Collects posts from groups and writes CSV rows with:
  - `Author`
  - `Post Time`
  - `Content`
  - `Post Link`
- Provides a modern web UI to run, stop, monitor progress, and download CSV

## Who Needs Installation?

- **End users (people you send the link to):** no installation needed.
- **Only the host machine (your PC/server):** needs Docker Desktop and project setup.

## Host Requirements

- Windows
- Docker Desktop
- Internet connection
- A Facebook account available on the machine running the scraper

## Run with Docker (Recommended)

```powershell
docker compose up --build -d
```

Open:

```powershell
http://localhost:5000
```

For Facebook login inside the Selenium browser container, open:

```text
http://localhost:7900
```

The noVNC password is disabled for local development in the current compose file.

`requirements.txt` is still required because the Docker image for the Flask app installs Python packages from it during build.

### Docker Services

- `app` - Flask web app
- `redis` - queue and live job state
- `postgres` - persistent run history
- `selenium` - Chrome browser automation

If you expose this app with ngrok, users open the ngrok URL in their browser and use it directly.
They do **not** install Python, ChromeDriver, Docker, or this repository.

### Web UI Features

- `Run` starts a new scraping job
- `Stop` stops your own current job
- `Process Timeline` shows user-friendly progress logs
- `Download CSV` becomes active when run is complete
- `Clear` clears timeline logs for your job
- `My Runs` shows your own run history
- `Delete` removes a specific saved run and its CSV
- `Delete All` removes all saved runs and CSV files for the current browser user

### Queue Behavior (Important)

- Only **one** scraping run can execute at a time on one machine (one Chrome automation session).
- If another user starts while a run is active, the new run is queued.
- Each browser gets its own `client_id`, and users can control only their own jobs.
- The project now supports storing queue and job state in `Redis` when configured.

### Docker Notes

- `Redis` stores queue and live job state
- `PostgreSQL` stores persistent run history
- default cleanup removes:
  - Redis terminal jobs older than `48` hours
  - PostgreSQL run history older than `30` days
- `Selenium` exposes:
  - `4444` for WebDriver
  - `7900` for noVNC browser access

## Input Fields

### `Search in Facebook`

Phrase sent to Facebook search.

### `Group links number`

Requested number of groups to process.

### `Posts from each group`

Requested number of posts per group.

> Expected rows = `group_links_number * posts_from_each_group` (best effort, based on available data and page behavior).

## Output

- Web mode: files are created under `web_outputs\facebookposts-<job_id>.csv`
- Download endpoint serves the result as `facebookposts.csv`

## Share with Others (ngrok)

If you want to share a temporary public link to your local app:

1. Run the app:

```powershell
docker compose up --build -d
```

2. Run ngrok to expose port 5000:

```powershell
ngrok http 5000
```

3. Send the `https://...ngrok...` URL.

### What End Users Need

- Only the link
- A browser
- No local installation

### ngrok Notes

- The scraping still runs on **your** machine.
- Remote users trigger jobs on your Dockerized local server and Selenium browser.
- If your machine/app is off, the link will not work.
- If multiple users run at the same time, jobs are queued (one active run at a time).

## Troubleshooting

### Push blocked by GitHub secret scanning

Do not commit browser profile/cache/history folders (`web_profiles/**` should be ignored).  
If sensitive data was already committed, rewrite history and rotate exposed credentials.

### ngrok not recognized

Make sure ngrok is installed and in PATH, or run the full executable path.

### Chrome/FB login behavior

When Facebook login is required, use:

- `http://localhost:7900`

That page shows the Selenium browser through noVNC so you can log in manually when needed.
