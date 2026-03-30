# Run The Full System

This project now runs as a full Docker-based system.

## What You Need

- Docker Desktop
- ngrok (optional, only if you want to share the app publicly)
- Internet connection

## Services In The System

- `app` - Flask web app
- `redis` - queue and live job state
- `postgres` - persistent run history
- `selenium` - Chrome automation browser

## Start The System

From the project folder:

```powershell
docker compose up --build -d
```

## Open The App

Main UI:

```text
http://localhost:5000
```

Browser used by Selenium:

```text
http://localhost:7900
```

Open `7900` only when you need to:
- log in to Facebook manually
- watch the browser automation

## First Login Flow

1. Open `http://localhost:5000`
2. Click `Run`
3. If Facebook login is needed, open `http://localhost:7900`
4. Log in to Facebook there
5. Let the run continue

After a successful login, the system tries to reuse saved cookies so future runs should require fewer manual logins.

## Stop The System

```powershell
docker compose down
```

## Hard Reset

This removes containers and Docker volumes:

```powershell
docker compose down -v
```

Then start again:

```powershell
docker compose up --build -d
```

## Share The App Publicly

Run:

```powershell
ngrok http 5000
```

Send the `https://...ngrok...` URL to other users.

## Useful Checks

See running services:

```powershell
docker compose ps
```

See app logs:

```powershell
docker compose logs app --tail=120
```

See Selenium logs:

```powershell
docker compose logs selenium --tail=120
```

## Notes

- `requirements.txt` is still needed because the `app` Docker image installs Python dependencies from it during build.
- `Redis` stores queue and live run state.
- `PostgreSQL` stores persistent run history.
- Default cleanup policy:
  - `Redis` terminal jobs older than 48 hours are removed
  - `PostgreSQL` run history older than 30 days is removed
- You can delete a single run or all saved runs directly from `My Runs`
- CSV files are written to `web_outputs`.
