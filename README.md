# World Cup Prediction Pool

A small web app for friends to predict the 90-minute outcome of World Cup matches — Team A win, Team B win, or Draw. Wrong prediction = forfeit the group stake; correct = keep it. The app is a **tracker only**: it shows who owes what, real money is settled offline.

## How it works

- Each person has one account. They predict once per match, and that prediction counts across every group they're in.
- Predictions lock at kickoff — the server enforces this, no client tricks accepted.
- Groups have a configurable stake (or no stake for a free pool). A group owner shares an 8-character join code; anyone with it can join.
- A background task fetches live match results and runs settlement automatically. One finished match can settle differently in each group depending on who was a member at kickoff.

## Architecture

Two decoupled pieces sharing one Postgres database (Neon, free tier, scale-to-zero):

```
┌─────────────────────┐        ┌──────────────────────────────┐
│  Web app (FastAPI)  │        │  Poll-and-settle task         │
│  Serves pages       │  ───▶  │  Runs every 20 min via        │
│  Takes predictions  │  (DB)  │  GitHub Actions → POST /tasks/poll │
│  Shows scoreboard   │        │  Fetches fixtures, settles    │
└─────────────────────┘        └──────────────────────────────┘
            │                              │
            └──────────┬───────────────────┘
                       │
              Neon Postgres (pooled)
```

The task is also runnable as a CLI: `python -m app.tasks.poll_and_settle`.

## Stack

| Layer | Choice |
|---|---|
| Web framework | FastAPI + Jinja2 templates |
| Interactivity | HTMX (no SPA, no build step) |
| Database | PostgreSQL via Neon (async: asyncpg / migrations: psycopg2) |
| ORM + migrations | SQLAlchemy 2.x + Alembic |
| Auth | 6-digit PIN, bcrypt hash, itsdangerous signed cookie (60-day session) |
| Football data | sports.bzzoiro.com v2 API (league_id=27 for World Cup) |
| Scheduler | GitHub Actions cron → POST /tasks/poll |

## Local setup

```bash
# 1. Install dependencies
make install

# 2. Configure environment
cp .env.example .env
# Edit .env — fill in DATABASE_URL (Neon dev branch), SESSION_SECRET, TASK_SECRET, FOOTBALL_API_KEY

# 3. Run migrations
make migrate

# 4. Start the dev server
make run
```

Visit `http://localhost:8000` → redirects to `/login`.

Use a Neon **dev branch** for `DATABASE_URL` locally — keep the production (main) branch URL only on your hosting platform. See [Database environments](#database-environments).

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | Neon pooled connection string (`postgresql+asyncpg://...`) |
| `SESSION_SECRET` | Yes | Random string (32+ chars) for signing session cookies |
| `TASK_SECRET` | Yes | Shared secret for the `POST /tasks/poll` endpoint |
| `FOOTBALL_API_KEY` | Yes | API key from [sports.bzzoiro.com](https://sports.bzzoiro.com) |
| `FOOTBALL_API_BASE_URL` | No | Defaults to `https://sports.bzzoiro.com/api/v2` |
| `FOOTBALL_LEAGUE_ID` | No | Defaults to `27` (World Cup) |
| `DEBUG` | No | Set `true` to enable SQL query logging |

For local development, copy `.env.example` to `.env` and fill in the values.

## Database environments

Use Neon's branching to keep local and production data separate:

```
Neon project
├── main   ← production (hosting platform DATABASE_URL)
└── dev    ← local development (local .env DATABASE_URL)
```

Create the `dev` branch in the Neon console (Branches → Create branch from main), then put its pooled connection string in your local `.env`.

### Running migrations

```bash
# Apply to dev (reads .env)
make migrate

# Apply to production once verified
make migrate-prod PROD_DATABASE_URL="postgresql+psycopg2://...main-branch..."

# Generate a new migration after changing a model
alembic revision --autogenerate -m "describe_the_change"
```

Alembic uses the sync `psycopg2` driver internally — it strips `+asyncpg` from the URL automatically.

## Poll-and-settle task

Each run does two things:

1. **Sync fixtures** — fetch upcoming matches from the football API and upsert into the `matches` table. Also deletes unsettled matches from other leagues so switching `FOOTBALL_LEAGUE_ID` keeps the DB clean (settled matches are never deleted).
2. **Settle finished matches** — for each finished, unsettled match: create `settlements` rows for every group member who joined before kickoff. No prediction = automatic loss. Marks `match.settled = True` when done.

Prediction locking is enforced at the endpoint (`match.kickoff_time <= now`), not by this task.

Running it manually:
```bash
python -m app.tasks.poll_and_settle
```

Via HTTP (e.g. from curl or a test):
```bash
curl -X POST http://localhost:8000/tasks/poll \
  -H "X-Task-Secret: your_task_secret"
# Returns 202 Accepted; task runs in the background
```

## GitHub Actions cron

The workflow at [.github/workflows/poll.yml](.github/workflows/poll.yml) POSTs to `/tasks/poll` every 20 minutes, which also wakes the web app if the hosting platform has scaled it to zero.

Add these secrets to your GitHub repository (`Settings → Secrets → Actions`):

| Secret | Value |
|---|---|
| `TASK_SECRET` | Same as your `TASK_SECRET` env var |
| `APP_URL` | Your deployed app URL, e.g. `https://your-app.fly.dev` |

## House rules (enforced in code)

- **Kickoff lock** — the server checks `match.kickoff_time <= now` before accepting any prediction. The client is never trusted for this.
- **Late joiners** — a member who joined a group after a match's kickoff is not settled for that match (`membership.joined_at < match.kickoff_time`).
- **No prediction = auto loss** — if a member has no prediction when a match finishes, the settlement records a loss for that match.
- **Idempotency** — the settlement task uses `INSERT ... ON CONFLICT DO NOTHING` and the `match.settled` flag, so running it twice on the same match produces no duplicate rows.

## Data model

```
users           — name, pin_hash (bcrypt), failed_attempts, locked_until
groups          — name, owner_id, join_code, stake
memberships     — group_id, user_id, role (owner/member), joined_at
matches         — team_a, team_b, kickoff_time, status, score_a, score_b, result, settled
                  league_id, round_number, round_name, group_name
predictions     — user_id, match_id, pick (A/B/draw), locked, created_at, updated_at
settlements     — group_id, user_id, match_id, correct, amount
```

## Auth

- **Register**: name + 6-digit PIN → bcrypt hash stored, session cookie set.
- **Login**: name + PIN → 5 failed attempts per account trigger a 15-minute lockout.
- **Rate limiting**: POST `/register` and POST `/login` are capped at 20 requests per hour per IP (slowapi).
- **PIN reset**: the app admin (user ID = 1) can clear a user's PIN hash at `/admin`. The user is prompted to set a new PIN on their next login attempt.
- **Session**: itsdangerous signed cookie, 60-day expiry, httponly + samesite=lax.

## Make targets

```bash
make run            # start dev server with hot reload
make migrate        # apply pending migrations (dev branch)
make migrate-prod   # apply to production: PROD_DATABASE_URL=<url>
make poll           # run poll-and-settle once (CLI)
make install        # create .venv and install dependencies
```

## Project layout

```
app/
├── auth/               # Session cookie, PIN service, FastAPI dependency
├── football_client/    # API client (swappable) + fixture sync
├── limiter.py          # slowapi rate limiter (shared across routers)
├── models/             # SQLAlchemy models (one file per table)
├── routers/            # Route handlers: auth, groups, matches, admin, tasks
├── tasks/              # poll_and_settle.py — standalone, no web server dependency
└── templates/          # Jinja2 HTML templates
alembic/                # Migration scripts
.github/workflows/      # GitHub Actions cron
tests/                  # pytest fixtures (uses a separate local Postgres DB)
```
