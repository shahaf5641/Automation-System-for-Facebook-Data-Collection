# Facebook Data Extractor - Client Guide

## Quick Start

1. Extract the folder you received (if zipped).
2. Open the extracted folder.
3. Double-click `Run-App.bat`.
4. In the app window, fill:
   - `SEARCH IN FACEBOOK`
   - `GROUP LINKS NUMBER`
   - `POSTS FROM EACH GROUP`
5. Click `Run`.
6. Log in to Facebook in Chrome if needed.
7. Wait until status says finished.

## Output File

The app creates:
- `facebookposts.csv`

The CSV is saved in the same folder where the app is running.

## Buttons

- `Run`: starts the process.
- `Stop`: stops the current process and closes Chrome.
- `Clear Logs`: clears the terminal panel in the app.

## Requirements

- Windows
- Internet connection
- Google Chrome installed
- Facebook account

## Notes

- If Chrome asks for permissions or login, complete them in the opened browser window.
- If there are not enough matching groups/posts, the final CSV may contain fewer rows than requested.
