# World Cup Prediction Pool

A small web app for friends to predict the 90-minute outcome of World Cup matches — Team A win, Team B win, or Draw. Wrong prediction = forfeit the round wager; correct = keep it. The app is a **tracker only**: it shows who owes what, real money is settled offline.

App has been deployed using Neon and Railway: https://world-cup-prediction-production.up.railway.app/



## How it works

- Each person has one account. They predict once per match, and that prediction counts across every group they're in.
- Predictions lock at kickoff — the server enforces this, no client tricks accepted.
- Groups have configurable per-round wagers (separate win and loss amounts per tournament phase). A group owner shares an 8-character join code; anyone with it can join.
- A background task fetches live match results and runs settlement automatically. One finished match can settle differently in each group depending on who was a member and what wagers are set.

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
| Rate limiting | slowapi — 200 req/min global, 20/hour on register + login |
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
| `FOOTBALL_LEAGUE_ID` | No | Defaults to `27` (World Cup). Change to test with another league. |
| `ROUND_DATE_RULES` | No | Staging only — see [Staging environment](#staging-environment). |
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

### Staging environment

For end-to-end testing with a live active league before the World Cup starts, add a `staging` Neon branch and point a staging deployment at it with a different `FOOTBALL_LEAGUE_ID`.

Many active leagues return `round_name=""` for all fixtures. Use `ROUND_DATE_RULES` to assign round names by date range so per-round wager settlement can be tested properly:

```
# staging .env
FOOTBALL_LEAGUE_ID=31   # or whichever active league you're testing with
ROUND_DATE_RULES=[{"from":"2026-06-01","to":"2026-06-07","name":"Group Stage"},{"from":"2026-06-08","to":"2026-06-09","name":"Round of 16"},{"from":"2026-06-10","to":"2026-06-10","name":"Quarterfinals"},{"from":"2026-06-11","to":"2026-06-11","name":"Semifinals"},{"from":"2026-06-12","to":"2026-06-12","name":"Final"}]
```

Rules are applied during fixture sync when the API returns an empty `round_name`. Adjust the date ranges to match the test league's actual schedule. Leave `ROUND_DATE_RULES` unset in production — the World Cup API provides its own round names.

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

Four HTTP endpoints, all guarded by `X-Task-Secret`:

| Endpoint | What it does |
|---|---|
| `POST /tasks/sync` | Fetch fixtures from the football API and upsert into the DB. Automatically triggers settlement if any match transitions to finished during the sync. **Use this for the main cron job.** |
| `POST /tasks/odds` | Fetch bookmaker 1x2 odds for upcoming scheduled matches. Skips matches fetched within the last hour. **Use a separate, less frequent cron job for this.** |
| `POST /tasks/settle` | Settle finished, unsettled matches only. No fixture sync. Useful as a manual fallback. |
| `POST /tasks/poll` | Runs sync then settle unconditionally. Kept for backward compatibility. |

`/tasks/sync` detects the live → finished transition during the API loop (no extra DB query) and calls settlement immediately, so it replaces `/tasks/poll` as the recommended cron target.

Prediction locking is enforced at the endpoint (`match.kickoff_time <= now`), not by this task.

Running manually:
```bash
make poll      # sync + settle
make sync      # sync only
make odds      # fetch odds only
```

Via HTTP:
```bash
curl -X POST http://localhost:8000/tasks/sync \
  -H "X-Task-Secret: your_task_secret"
# Returns 202 Accepted; task runs in the background
```

### Re-settling after wager changes

If you change wager settings after matches have already been settled, re-run settlement for a specific group:

```bash
make resettle GROUP_ID=1
```

Or use the "Re-settle with current wagers" button on the scoreboard (group owners only). This deletes existing settlements for the group, resets the match flags, and re-runs settlement — no fixture sync involved.

## Scheduling the poll task

The `POST /tasks/sync` endpoint is triggered by **cron-job.org** (free). GitHub Actions' scheduled workflows are too unreliable (can run hours late on free plans).

Two cron-job.org jobs (free tier supports multiple):

**Fixtures (main job):**
- URL: your production app URL + `/tasks/sync`
- Method: POST
- Header: `X-Task-Secret: <your TASK_SECRET>`
- Schedule: every 1–2 minutes during live games; every 20 minutes otherwise

**Odds:**
- URL: your production app URL + `/tasks/odds`
- Method: POST
- Header: `X-Task-Secret: <your TASK_SECRET>`
- Schedule: every 60 minutes (matches fetched within the last 59 minutes are skipped)

The workflow at [.github/workflows/poll.yml](.github/workflows/poll.yml) is kept as a manual trigger only (`workflow_dispatch`) — useful for forcing a one-off run from the GitHub Actions tab.

## House rules (enforced in code)

- **Kickoff lock** — the server checks `match.kickoff_time <= now` before accepting any prediction. The client is never trusted for this.
- **Late joiners** — a member who made a prediction before joining the group always has that prediction count. A member with no prediction who joined after kickoff is excluded by default; group owners can toggle this to count those as losses instead.
- **No prediction = auto loss** — if a member has no prediction when a match finishes, the settlement records a loss for that match.
- **Idempotency** — the settlement task uses `INSERT ... ON CONFLICT DO NOTHING` and the `match.settled` flag, so running it twice on the same match produces no duplicate rows.

## Wager settings

Each group has per-round wagers set by the owner on the scoreboard page. Rounds follow the World Cup structure:

| Round | Example win | Example loss |
|---|---|---|
| Group Stage | 5 | 5 |
| Round of 32 | 10 | 10 |
| Round of 16 | 15 | 15 |
| Quarterfinals | 20 | 20 |
| Semifinals | 25 | 25 |
| Match for 3rd place | 20 | 20 |
| Final | 30 | 30 |

Win and loss amounts are independent — you can set asymmetric wagers (e.g. win 10, lose 5). Leave a round blank for no wager on that round. Changes only affect future settlements; use "Re-settle" to retroactively apply new wagers.

## Scoreboard

Each group has a scoreboard at `/groups/{id}/scoreboard` showing:

- **Reminder to vote for upcoming games** — collapsible section at the top. Amber with warning icon if any group member hasn't predicted for a match starting within 24h; neutral gray ("Everyone has voted for upcoming games") once all predictions are in. Hidden when no matches are upcoming.
- **Overall standings** — cumulative correct/wrong/net for each member, ranked by correct predictions then net. Includes a per-member multiplier column (editable by group owner, read-only for others) applied to the net amount.
- **Wager settings** — editable by group owner (win/loss amounts per round); read-only view for other members.
- **Standings By Round** — per-round standings (collapsible), same columns
- **Group Members' Prediction History by Match** — settled matches grouped by round (collapsible), showing each member's pick, outcome, and amount

Match kickoff times are displayed in the visitor's local timezone (converted client-side from UTC).

Upcoming matches display bookmaker implied probabilities (home % / draw % / away %) when odds have been fetched, normalised from decimal odds so they sum to 100%.

## Data model

```
users           — name, pin_hash (bcrypt), failed_attempts, locked_until
groups          — name, owner_id, join_code, late_join_counts_as_loss
group_wagers    — group_id, round_name, win_amount, loss_amount
memberships     — group_id, user_id, role (owner/member), joined_at, multiplier
matches         — team_a, team_b, kickoff_time, status, score_a, score_b, result, settled
                  league_id, round_number, round_name, group_name
                  odds_a, odds_draw, odds_b, odds_fetched_at
predictions     — user_id, match_id, pick (A/B/draw), locked, created_at, updated_at
                  odds_visible (null = no odds on match, true = odds shown, false = odds hidden at decision time)
settlements     — group_id, user_id, match_id, correct, amount
```

`groups.stake` was replaced by `group_wagers` to support per-round win/loss amounts.

## Auth

- **Register**: name + 6-digit PIN → bcrypt hash stored, session cookie set.
- **Login**: name + PIN → 5 failed attempts per account trigger a 15-minute lockout.
- **Rate limiting**: 200 req/min per IP globally; POST `/register` and POST `/login` additionally capped at 20/hour per IP.
- **Auth middleware**: all routes except `/login`, `/register`, `/set-pin`, `/logout`, `/health`, and `/tasks/*` require a valid session cookie — unauthenticated requests are redirected to `/login`.
- **PIN reset**: the app admin (user ID = 1) can clear a user's PIN hash at `/admin`. The user is prompted to set a new PIN on their next login attempt.
- **Session**: itsdangerous signed cookie, 60-day expiry, httponly + samesite=lax.

## Make targets

```bash
make run                          # start dev server with hot reload
make migrate                      # apply pending migrations (dev branch)
make migrate-prod PROD_DATABASE_URL=<url>  # apply to production
make poll                         # run poll-and-settle once (CLI)
make sync                         # sync fixtures only — no settlement
make odds                         # fetch bookmaker odds for upcoming matches
make resettle GROUP_ID=<id>       # re-settle one group with current wagers
make install                      # create .venv and install dependencies
```

## Project layout

```
app/
├── auth/               # Session cookie, PIN service, FastAPI dependency
├── football_client/    # API client (swappable), fixture sync
├── limiter.py          # slowapi rate limiter instance (shared across routers)
├── models/             # SQLAlchemy models (one file per table)
├── routers/            # auth, groups, matches, scoreboard, admin, tasks
├── tasks/              # poll_and_settle.py, sync_fixtures_cli.py, resettle.py
└── templates/          # Jinja2 HTML templates
alembic/                # Migration scripts
.github/workflows/      # GitHub Actions cron (poll.yml)
tests/                  # pytest fixtures (uses a separate local Postgres DB)
```
