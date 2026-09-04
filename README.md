# Briefd

Briefd turns a company name into a sales briefing covering the company overview,
key people, recent news, financials, and risks. Results stream to the browser and
are saved locally in SQLite.

## Setup

Prerequisites: Python 3.11+, Node.js 22.13+, and a Gemini API key.

```sh
make install
cp .env.example .env
# Set GEMINI_API_KEY in .env, then start both servers.
make dev
```

- App: http://localhost:3000
- API documentation: http://localhost:8000/docs

The app starts without an API key, but research requests return a configuration
error until a key is supplied.

## Configuration

Backend settings are loaded from the root `.env` file. Keep credentials local;
only placeholder `.env.example` files belong in source control.

| Variable | Purpose |
| --- | --- |
| `GEMINI_API_KEY` | API key for company research. |
| `GEMINI_MODEL` | Research model; choose one available to your API account. |
| `GEMINI_FALLBACK_MODEL` | Optional fallback when the configured model is no longer available. |
| `GEMINI_GOOGLE_SEARCH_ENABLED` | Enable Google Search grounding when supported by your account. Defaults to `false`. |
| `GEMINI_QUOTA_MAX_RETRIES` | Number of retries for rate limits. Defaults to `2`. |
| `GEMINI_QUOTA_RETRY_BASE_SECONDS` | Initial retry delay; doubles for each retry. Defaults to `20`. |
| `DATABASE_URL` | Database connection string. Defaults to local SQLite. |
| `CORS_ORIGINS` | JSON array of allowed frontend origins. Defaults to `["http://localhost:3000"]`. |

To use a different backend address, copy `frontend/.env.example` to
`frontend/.env.local` and set `NEXT_PUBLIC_API_URL`. This value is public browser
configuration and must never contain credentials.

Set `WATCH_POLLING=true` when starting the frontend if your environment requires
polling for file changes.

## Research behavior

With search grounding enabled, Briefd requests each section separately and attaches
available source links. Without grounding, it requests all five sections together;
recent news and source links remain empty because no live search is performed.
Unknown information is left empty rather than fabricated.

## Development

```sh
make test   # Backend and frontend tests
make check  # Tests, lint, and production build
```

- `backend/app`: FastAPI routes, data models, persistence, and research provider.
- `backend/tests`: API, streaming, retry, and provider tests.
- `frontend/app`: Application routes, layout, and styles.
- `frontend/components`: Briefing views and shared interface components.
- `frontend/lib`: API client, stream decoder, and shared types.

## Limitations

Duplicate-research locking is limited to one API process. SQLite tables are created
at startup; schema migrations and shared locking would be needed for a multi-worker
service. Source links are attached per section rather than per claim.

The default setup runs locally without authentication. Database files, environment
files, logs, and build output are excluded from source control.
