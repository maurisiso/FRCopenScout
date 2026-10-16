# FRC Open Scout

A free scouting web app for FIRST Robotics Competition teams, especially teams that don't have enough people to scout every match.
It combines public data from **The Blue Alliance (TBA)** and **Statbotics** with your own scouts' observations.

**Phase 1 (this code):** the scouting dashboard. **Phase 2:** a locally trained AI assistant plugged into the same app.

## Features

- **Accounts:** email sign-up, plus Google sign-in once you add OAuth keys. English and Spanish, with English as the default.
- **Teams:** mentors and coaches request to manage a team, and platform staff verify them on `/staff/approvals/`.
  - Roles are **Admin / Scout / Viewer**.
  - Admins invite members with codes or links and can remove members at any time.
  - A user can belong to several teams, and their profile page lists all of them.
- **Custom scouting forms:** each team defines its own fields: counters, numbers, yes/no, single choice, multiple choice, 1–5 ratings and text. Fields are grouped by phase (pre-match, auto, teleop, endgame, general) and can carry optional points so the app can estimate scouted points.
- **Offline scouting (PWA):** the scouting page keeps working without signal.
  - Entries are queued on the phone (IndexedDB) and upload automatically when the connection returns.
  - Retrying an upload is safe, because the server de-duplicates entries by `client_uuid`.
  - Scouts pick their station (Red 1–Blue 3) and the robot fills in automatically for each match.
- **TBA + Statbotics sync:** your team's events for a season, plus team lists, the match schedule, results, rankings, OPR, EPA and match win probabilities.
- **Regional dashboard:**
  - Overview of your rank, record, upcoming matches and the event rankings.
  - A sortable teams table showing EPA alongside your own scouting averages.
  - Team and match pages with alliance breakdowns.
  - Match notes (robot issue, radio, strategy, fouls…).
  - Scouting data with CSV export.
- **Team database:** every team you have ever scouted, across all events.
- **Alliance selection:**
  - An automatic prediction, with a "where we land" summary for your team.
  - An interactive simulator that follows the real rules: serpentine order, lower captains being picked (alliances below move up and the next-ranked team becomes the new last captain), declines (a team that declines can't be picked later but can still become a captain), a backup pool, and a third pick round for Championship divisions.
  - You can enter your own predicted ranking order and save scenarios.
- **AI assistant (placeholder):** "Ask the assistant" panels on match and team pages.
  - Today it gives rule-based tips computed from the data.
  - In Phase 2 the same endpoint calls your local model (Ollama provider included).
  - Every question, the data it was based on and the 👍/👎 feedback are logged in `AIQuery`, which gives you data for evaluating the model later.

## Run it on Windows 11

You need **Python 3.11 or newer** (from python.org; tick "Add python.exe to PATH" when installing) and Git.

Run these commands in PowerShell:

```powershell
cd $HOME\Documents\frc-open-scout
py -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt
copy .env.example .env                # then edit .env (see below)
python manage.py migrate
python manage.py createsuperuser      # this is YOU, the platform staff who approves teams
python manage.py runserver
```

Open http://127.0.0.1:8000.

### Try it without an API key (demo data)

```powershell
python manage.py seed_demo --team 9999 --email you@example.com
```

This creates team 9999, makes your user its admin, and adds a fake event ("Demo Regional") with 36 teams, played qualification matches, EPA and about 300 scouting entries.
Go to **Team 9999 → Demo Regional**. Running the command again resets the demo.

### Connect real data

1. Get a **TBA Read API key** at https://www.thebluealliance.com/account (under "Read API Keys") and put it in `.env` as `TBA_API_KEY=...`.
2. Restart the server. On your team page, click **Load my 2026 events from TBA**, or add any event by its key (for example `2025mxmo`).
3. You can also sync from the command line: `python manage.py sync_event 2025txhou`.

Statbotics needs no key.

### Google sign-in (optional)

In Google Cloud Console, go to APIs & Services → Credentials → **Create OAuth client ID** and choose Web application.

- Authorized redirect URI: `http://127.0.0.1:8000/accounts/google/login/callback/`. Add your real domain later.
- Put the client ID and secret in `.env` as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.

The "Continue with Google" button appears automatically.

### Testing on phones

Browsers only enable offline mode (service workers) over **HTTPS** or on `localhost`. To test the full offline flow on a phone, expose your PC with an HTTPS tunnel such as `cloudflared tunnel --url http://localhost:8000` or ngrok. Then add that hostname to `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` in `.env`.

Plain `http://192.168.x.x:8000` still works for scouting while online, but offline mode won't activate.

## Approving teams (staff)

When a mentor registers a team, it appears on **`/staff/approvals/`**, which you can see because you are a superuser.

- Check the evidence (team website, FRC Events listing), then click Approve or Reject.
- Approving activates the team and makes that person its admin.
- You can also approve from the Django admin at `/admin/` → Team claims.

## Translations

Text is wrapped in `{% trans %}` and `{% blocktrans %}` in templates, and in `_()` in Python. After adding text, run:

```powershell
python tools/i18n.py           # updates locale/es/LC_MESSAGES/django.po and compiles it
python tools/i18n.py --check   # lists strings still missing a Spanish translation
```

Fill the empty `msgstr ""` lines in the `.po` file, then run the script again. No GNU gettext install is needed.

## Tests

```powershell
python manage.py test
```

The tests cover the alliance-selection rules, API parsing, the offline sync endpoint (including duplicates and permissions), and the team approval, invite and kick flows.

## Project layout

```
config/       settings, URLs, PWA views (service worker, manifest)
accounts/     custom User (email login), profile page, language preference
teams/        Team, Membership (roles), TeamClaim (staff approval), Invite; permission decorator
frcdata/      local cache of TBA/Statbotics data, API clients, parsers, sync, seed_demo command
scouting/     custom forms (ScoutingForm/FormField), ScoutEntry (JSON answers), MatchNote, sync API, stats
events/       team dashboard, regional dashboard pages, alliance_selection.py engine, saved predictions
ai/           context.py (the data contract for the AI), providers.py (stub + Ollama), AIQuery log
templates/    HTML (Django templates + a little HTMX)
static/       app.css, app.js, scout.js (offline form), sw.js (service worker), htmx
locale/       Spanish translations
tools/        i18n.py
```

Good places to start reading:

- `events/alliance_selection.py`: pure Python, with a docstring explaining the rules.
- `scouting/models.py`: how custom forms work.
- `teams/permissions.py`: how every team page checks access.
- `ai/context.py`: exactly what the AI will see.

## Phase 2 hook

Set `AI_PROVIDER=ollama` in `.env` and run a model with [Ollama](https://ollama.com), for example `ollama run llama3.1:8b`, which fits an RTX 3070 Ti (8 GB).

To use your own fine-tuned model, add a class with an `answer(question, context)` method in `ai/providers.py`.

## Credits

Data comes from [The Blue Alliance](https://www.thebluealliance.com) and [Statbotics](https://www.statbotics.io). Not affiliated with FIRST®.
