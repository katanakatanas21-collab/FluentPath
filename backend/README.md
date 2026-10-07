# Backend Development Setup

## PostgreSQL persistence (Phase 2)

The application now reads and writes through a persistence layer in `backend/persistence/`. The active backend is chosen once at startup from the environment and fails closed:

* `development` and `test` default to the JSON files under `backend/data/`, so existing tests and local work are unaffected. `FLUENT_PATH_PERSISTENCE=postgres` opts in explicitly.
* `staging` and `production` always resolve to PostgreSQL. Requesting `json` in either is refused, so a JSON file can never receive a production write.
* There is no PostgreSQL-to-JSON fallback. A storage failure raises `DataStoreError`, which the existing handler reports as HTTP 503 with `{"detail": "DATA_STORE_UNAVAILABLE"}`.

`FLUENT_PATH_ENVIRONMENT` must be `development`, `test`, `staging`, or `production`. Keep URLs and credentials in the local ignored `.env` or deployment secret manager. `.env.example` contains blank values only.

Both backends keep the existing record shapes, so route and response behaviour is unchanged. Reads and writes stay whole-store, as they were with JSON files; the store coroutines run on one dedicated background event loop so synchronous helpers can keep calling them. Converting the routes to `async def` with request-scoped sessions is a later step, not part of this phase.

Tests that need a PostgreSQL connection must use `TEST_DATABASE_URL` explicitly, with a database name containing `test`. There is no fallback to `DATABASE_URL`. The PostgreSQL runtime is exercised separately against a disposable database; the default suite runs entirely on the JSON backend.

### Transport security

Staging and production connections are always verified, and the policy lives in code rather than in configuration text:

* The Supabase pooler presents a private three-certificate chain rooted at `Supabase Root 2021 CA`. That authority is self-signed and is in neither the Windows nor the certifi trust store, so `db/certs/supabase_root_2021_ca.pem` pins it and `db/session.py` checks its SHA-256 fingerprint before use.
* `build_verified_ssl_context()` sets `CERT_REQUIRED` and `check_hostname`, so both the chain and the hostname are validated. Connecting by IP instead of the hostname fails.
* `ssl*` query parameters are stripped from `DATABASE_URL`, and a caller-supplied `ssl` context is refused in staging and production, so `sslmode=require`, `sslmode=disable`, or a substituted certificate cannot take effect.
* Python 3.13+ enables `VERIFY_X509_STRICT` by default, which rejects this legacy root because it carries no `keyUsage`/`basicConstraints` extensions. Only that extra RFC 5280 conformance check is relaxed; signature and hostname verification stay enabled.
* Earlier tooling connected with `sslmode=require`, which asyncpg documents as "no server certificate or host verification". Those connections were encrypted but unauthenticated. Do not reintroduce that setting.

`backend/test_database_tls.py` asserts each of these properties offline, including that the pinned certificate matches its expected fingerprint.

Alembic uses `DATABASE_URL` and the async PostgreSQL driver. The initial revision is `0001_initial_schema`; later schema changes must be new Alembic revisions. Revision `0002_nullable_user_created_at` permits NULL for a genuinely unknown imported legacy user creation time; application registration continues to write a timezone-aware UTC timestamp. Revision `0003_unknown_history_times` extends that permission to the other historical timestamps the legacy JSON never recorded. Downgrade refuses to restore NOT NULL if any such row is NULL.

### Runtime schema revision guard

`backend/db/revision.py` holds the single expected revision, `EXPECTED_SCHEMA_REVISION`, and both the importer and the runtime read it from there so they cannot drift apart. Adding a migration therefore means updating that one constant.

Before any PostgreSQL read or write, and before any token revocation check, the backend confirms the target really is at that revision. Without it, an older database fails with an opaque undefined-column error, or worse, succeeds while quietly returning less data than the code expects. The guard runs once per process and only on success, in its own short-lived session so a write never holds a table lock while the schema is judged. A refusal is not cached, so a migration applied underneath a running process is picked up.

The refusal is a `SchemaVersionMismatch`, a `DataStoreError`, so the API returns its existing generic 503 rather than leaking schema detail. Messages name only the revisions involved, never a host, database, or credential. A missing `alembic_version` table, an empty one, and one holding several rows are all refused, because each means the migration history is not trustworthy.

This is a refusal, not a repair. The guard never migrates anything, and it never falls back to JSON: staging and production cannot resolve to file storage under any condition. Because a successful check is cached for the life of the backend instance, the guard is a deploy-ordering check, not a continuous monitor; a revision change made under a running process is detected when the process restarts.

### JSON importer

Run a non-mutating preflight from this directory:

```powershell
.\venv\Scripts\python.exe import_json_to_postgres.py --source .\data
```

Dry-run is the default. It reads only the explicitly supplied `data` directory, rejects `.qa-disposable`, validates known IDs/references and row transforms, prints record counts and sanitized validation status, and never opens a target connection. It never edits source files. Unknown or malformed timestamps fail by default. The one inspected legacy anomaly is allowed only by passing `--allow-legacy-unknown-created-at ac541972745fe045` and a new `--audit-report` path outside the source directory; that rule is pinned to the exact observed record and original-value SHA-256. The report contains only the internal record ID, store/field, safe format label, digest, and planned NULL value; choose a protected output location. The original JSON value remains untouched. Arbitrary malformed timestamps still fail even with this flag.

The importer’s apply path is intended only for a reviewed, empty, migrated development/staging database. It requires `IMPORT_DATABASE_URL`, `FLUENT_PATH_ENVIRONMENT=development` or `staging`, `FLUENT_PATH_IMPORT_CONFIRM=I_CONFIRM_STAGING_IMPORT`, and `--confirm-target` exactly matching the non-secret `host[:port]/database` identity. It refuses production-marked hosts/database names, any non-empty application table, and any schema version other than Alembic head (`EXPECTED_SCHEMA_REVISION` in `backend/db/revision.py`, currently `0003_unknown_history_times`). Never use this mechanism for production cutover in Phase 1.

## Development staff accounts

The local data store contains development-only teacher and administrator accounts (`devOnly: true`). To create or reset them, run `python seed_dev_accounts.py` from this directory. The script prompts for separate passwords of at least 16 characters, stores only salted password hashes, and refuses to run when `FLUENT_PATH_ENVIRONMENT` is not `development` or to overwrite a non-development account. Passwords are never embedded in frontend code or source files.

The development sign-in emails are `teacher.dev@fluentpath.local` and `admin.dev@fluentpath.local`. Choose and retain the passwords locally when running the seed script.

For production, set `FLUENT_PATH_ENVIRONMENT=production` and provide a randomly generated `FLUENT_PATH_JWT_SECRET` of at least 32 characters. Do not seed development staff accounts in production.

## AI Teacher

Install backend dependencies with `python -m pip install -r requirements.txt`. Set `OPENAI_API_KEY` in the backend process environment to enable AI practice. `OPENAI_MODEL` is optional and defaults to `gpt-4o-mini`. Keep the API key on the backend; never commit it or expose it to the frontend. Without the key, AI session creation returns a configuration response and does not save a false AI reply.

## Zoom class meetings

Teachers can create, edit, start, and cancel Zoom meetings from class scheduling. Configure an activated Zoom Server-to-Server OAuth app in the backend process with:

- `ZOOM_ACCOUNT_ID`
- `ZOOM_CLIENT_ID`
- `ZOOM_CLIENT_SECRET`
- `ZOOM_HOST_USER_ID` (the Zoom account user ID or email that hosts classes)

Grant the app only the meeting permissions needed for create, update, and delete (`meeting:write:admin` for the configured account/host). Keep these values in the deployment secret manager; do not commit them or send them to the browser. Students receive the participant join URL. The teacher start action fetches a current host URL from Zoom because start URLs can expire.

This integration uses Zoom's `account_credentials` Server-to-Server OAuth grant and Meetings REST API. A webhook endpoint and webhook signature verification are not implemented; attendance events are not processed. Automated tests mock provider requests, so live Zoom calls still require configured credentials and verification.
