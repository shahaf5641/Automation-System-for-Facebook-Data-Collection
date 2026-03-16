# Facebook Groups Scraper

A simple tool for collecting Facebook group posts based on a search keyword.

## System Flow

![System Flow](docs/system-flow.svg)

The script:
- opens Chrome
- uses the Facebook account already logged in, or waits for manual login
- searches for groups by keyword
- enables the `Public groups` filter before collecting links
- opens groups
- collects posts
- saves the results to a CSV file

## What It Is For

Use this tool if you want to collect Facebook group posts into a clean CSV or Excel-friendly file.

Examples:
- apartment posts
- car posts
- job posts
- posts about any topic you search for

## What You Need

Before running the script, make sure you have:
- Windows
- Python installed
- Google Chrome installed
- internet connection
- a Facebook account you can log into through Chrome

## Installation

Open a terminal inside the project folder and run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## How To Run

```powershell
python main.py
```

A setup app window opens and asks for 3 values:

1. `Search word`
2. `Group links number`
3. `Posts from each group`

Use `Run` to start and `Stop` to cancel the current process.

The app also includes a built-in terminal panel that streams all scraper logs in real time.

If the GUI cannot open in your environment, the script automatically falls back to terminal prompts.

## Run As Website

To run the project as a web app:

```powershell
python app.py
```

Then open:

```text
http://localhost:5000
```

The web app lets a client:
- enter the scraper inputs from the browser
- start and stop a scraping job
- watch process logs
- download the finished CSV

Important:
- the scraping still runs on the server machine
- Chrome must be installed on that machine
- the Facebook login also happens on that machine
- if you want to send a public link to a client, you need to deploy this app on a server or a Windows machine you control

## Build EXE For Client

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

The client-ready package will be created under:
- `release\FacebookDataExtractor-<timestamp>`

Inside that folder, send everything as-is to the client.

## What Each Input Means

### `Search word`

The keyword or phrase used to search for Facebook groups.

Examples:
- `house`
- `jobs`
- `cars`
- `apartments`

### `Group links number`

How many groups the script should try to process.

Example:
- if you enter `10`, the script will try to work on 10 groups

### `Posts from each group`

How many posts to collect from each group.

Example:
- if you enter `30`, the script will try to collect up to 30 posts from each group

## Output File

CSV file that contains these columns:
- `Author`
- `Post Time`
- `Content`
- `Post Link`

## Quick Summary

1. Install the requirements
2. Run `python main.py`
3. Fill the setup window (search word, number of groups, and number of posts)
4. Log into Facebook if needed
5. Wait for the script to finish
6. Open `facebookposts.csv`
