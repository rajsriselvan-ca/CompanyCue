# CompanyCue

CompanyCue creates a live, source-backed sales briefing from a company name. It
searches the web, streams five report sections to the browser, and stores
completed briefings locally.

## What is implemented

- Groq planning and synthesis using `openai/gpt-oss-20b` and
  `openai/gpt-oss-120b`
- SerpAPI Google web and news search
- Streaming Server-Sent Events with progressive section rendering
- Overview, key people, recent news, financials, and risks with source links
- SQLite report history
- Request cancellation, retry handling, search limits, and duplicate-run locks
- Recorded mock providers for offline development and tests

## Stack

- Backend: Python 3.11+, FastAPI, SQLAlchemy, SQLite, HTTPX
- Frontend: Node 20.19+, React 19, TypeScript, Vite, Tailwind CSS

## Run locally

Install dependencies and create `.env`:

```sh
./scripts/setup.sh
```

Add your provider keys to `.env`:

```env
GROQ_API_KEY=your_groq_key
SERPAPI_API_KEY=your_serpapi_key
MOCK_PROVIDERS=false
```

Start the API and frontend:

```sh
./scripts/dev.sh
```

- App: <http://localhost:5173>
- API docs: <http://localhost:8000/docs>

To run without provider keys, set `MOCK_PROVIDERS=true` in `.env`.

## Tests and build

```sh
./scripts/test.sh
npm --prefix frontend run build
```

The test suites use recorded provider responses and do not require network
access or API keys.

## Project layout

```text
backend/app/       FastAPI routes, persistence, SSE, and research agent
backend/tests/     Backend unit and integration tests
frontend/src/      React application
frontend/tests/    Frontend tests
scripts/           Setup, development, and test commands
.env.example       Configuration reference
```

## Main API routes

- `POST /api/research` — stream a new briefing
- `GET /api/reports` — list saved briefings
- `GET /api/reports/{id}` — get one briefing
- `DELETE /api/reports/{id}` — delete one briefing
- `GET /api/health` — show provider configuration status
