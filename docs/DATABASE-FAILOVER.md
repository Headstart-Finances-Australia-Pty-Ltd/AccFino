# Database failover (main Neon + standby database) and CU diagnostics

AccFino can run with a **main** database and one or more **standby** databases
(for example a second free Neon account). If the main one is out of quota
(Neon "compute time quota exceeded", "too many connections", suspended project)
or unreachable, the app moves to the standby **by itself** and keeps serving,
then moves back and merges the data when the main one recovers.

With no `DATABASE_STANDBY_URLS` nothing changes.

## One-time setup

1. Create a second Neon project/account and copy its connection string.
2. Set environment variables (Northflank → service → Environment), then redeploy:

   ```
   DATABASE_URL=postgresql+psycopg2://…main…?sslmode=require
   DATABASE_STANDBY_URLS=postgresql+psycopg2://…standby…?sslmode=require
   DB_ADMIN_TOKEN=<a long random secret>        # protects the controls below
   ```
   More than one standby: separate with commas or new lines.
3. Fill the standby once (creates its tables and copies everything). From a shell
   in the running container (Northflank → Shell) or locally with the same env:

   ```
   python -m db_app.sync_standby --from 0 --to 1
   ```
   Numbers: `0` = `DATABASE_URL`, `1` = first standby, `2` = second …
4. Check the startup log for `Database failover on: 2 databases, active #0`.

## What happens, and when

| Situation | What the app does |
|---|---|
| Normal | Uses database 0. **Nothing is copied on a timer** (same as isift), so the standbys are never woken up needlessly. |
| Main fails / out of quota | The next new connection goes to the standby and logs `DATABASE FAILOVER`. It tries once to copy main → standby (usually impossible when out of quota); the standby carries on with its last copy. |
| On the standby | Every `DB_FAILBACK_MINUTES` (30) it checks whether the main works again. When it does: standby → main merge, switch back, second quick merge for rows written meanwhile. |
| Restart while on a standby | It remembers (file `db_app/.db-active.json`) and starts on the standby. Or set `DATABASE_ACTIVE_INDEX=1`. |

Failover happens only while a connection is being opened, never mid-query, so a
payment or invoice write is never silently repeated.

**Copies are merges.** Rows are inserted/updated by primary key; nothing is
deleted. A row that would break another unique/foreign-key rule is skipped and
counted. ID counters are advanced so new records never collide. The standby gets
its tables from the app's own models and migrations — no seed data — so roles,
admin and licences keep their original ids.

**Honest limits**
- Anything written to the main database *after the last copy* and *before* it
  failed is not on the standby until the main recovers and the two are merged.
  If you want a standby kept warm, set `DB_STANDBY_SYNC_HOURS` (for example 24) or run `python -m db_app.sync_standby --from 0 --to 1` yourself; it is off by default.
- Reconciliation **session files** (`main_app/data/<user>/…`) live on disk, not in
  Postgres, and are not part of the database copy. Mount a persistent volume
  (see `northflank.yml`) if you need them to survive redeploys.
- If both databases changed the same row, the copy direction decides who wins.

## Settings (all optional)

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_STANDBY_URLS` | – | Standby connection strings |
| `DATABASE_ACTIVE_INDEX` | auto | Start on this database (0 = main) |
| `DB_STANDBY_SYNC_HOURS` | 0 | Optional timed copy main → standby; `0` = off (isift behaviour) |
| `DB_FAILBACK_MINUTES` | 30 | Main-recovered check while on a standby; `0` = never |
| `DB_SYNC_SKIP_TABLES` | – | Comma list of tables to leave out of copies |
| `DB_ADMIN_TOKEN` | – | Secret for the controls below (they are off without it) |
| `DB_TRACE` | off | `1` = log every SQL statement (see diagnostics) |

## Checking and manual control

- `GET /api/health` – fast, never touches the database (safe for uptime monitors / Northflank).
- `GET /api/health?deep=1` – also runs `SELECT 1`; shows which database is active.
- With header `X-DB-Admin-Token: <DB_ADMIN_TOKEN>`:
  `GET /api/db-failover/status`, `POST /api/db-failover/sync?source=1&target=0`,
  `POST /api/db-failover/switch?to=0`.
- Command line: `python -m db_app.sync_standby --from 1 --to 0`.

## Why is Neon "busy" when nobody uses AccFino?

Measured on this code: after startup, an idle AccFino sends **no** SQL — 70 s of
health checks and home-page visits produced 0 statements, and its pooled
connections sit `idle` (Neon does not count idle connections as activity; it
*does* count `idle in transaction`, and there are none). The health check
(`/ready`) does not use the database. So look at what else wakes Neon:

1. **Other apps on the same Neon account/project.** CU hours are per account;
   Kutumb's old 60-second timers alone could keep a database awake all day.
2. **Restarts.** Every start of the container runs the schema/migration steps
   (~60 statements) and wakes the database for at least 5 minutes. Check
   Northflank for repeated restarts / failed health checks.
3. **Real or bot traffic.** The login page and API are public; scanners hit
   `/auth/login` all day, and each attempt is a query.
4. **Neon settings.** Make sure scale-to-zero is on (Free plan: always on) and
   that no paid-plan "always active" / minimum-CU setting is set.

Find out which app/process is connected, in the Neon SQL editor:

```sql
SELECT application_name, state, count(*), max(query_start) AS last_query
FROM pg_stat_activity WHERE datname = current_database()
GROUP BY 1, 2 ORDER BY 4 DESC;
```

AccFino connects as `accfino-api`, `accfino-auth` or `accfino-init`; a line with
an `application_name` of `accfino-*` and a recent `last_query` means AccFino is
the one. To see *what* it ran and when, set `DB_TRACE=1` and read the log lines
starting with `[dbtrace]` (turn it off again afterwards).
