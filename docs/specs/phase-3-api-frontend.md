# Phase 3 Spec — API, Auth, Observability, and Frontend

**Prerequisite**: Phase 1 complete (RAG working). Phase 2 optional but
baseline.md should exist.

**Objective**: Wrap the agent pipeline in a FastAPI service with JWT auth,
session persistence, and LangFuse tracing. Build a React frontend that
consumes the API. Deploy both publicly.

**Verification**: The Vercel URL is publicly accessible, shows the three-panel
UI, and a research query returns a grounded report with source citations.

**Must not change**: `agents/`, `app.py`, `requirements.txt`

---

## Part A — FastAPI Service

### Task 3.1 — FastAPI Skeleton

**Estimated agent time**: 10 minutes
**Files to create**: `api/main.py`, `api/schemas.py`, `api/models.py`

```python
# api/main.py — expected structure
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialise DB connection pool on startup
    yield
    # Close pool on shutdown

app = FastAPI(
    title="Deep Research API",
    description="Enterprise Knowledge Intelligence — research sessions with RAG",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://*.vercel.app", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Pydantic schemas to define in `api/schemas.py`:

```python
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str  # min 8 chars

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class SessionCreate(BaseModel):
    query: str
    route_override: str | None = None  # quick/deep/technical/comparative/None

class SessionResponse(BaseModel):
    id: str
    query: str
    route: str | None
    report: str | None
    sources: list[dict] | None
    cost_usd: float | None
    latency_ms: int | None
    created_at: str
    trace_url: str | None  # LangFuse trace URL
```

**Verification**: `uv run uvicorn api.main:app --reload` starts without
import errors. Visit `http://localhost:8000/docs` — OpenAPI UI loads.

---

### Task 3.2 — Auth Endpoints

**Estimated agent time**: 10 minutes
**Files to create**: `api/auth.py`

```python
# Endpoints to implement:
# POST /auth/register  — hash password, insert user, return token
# POST /auth/login     — verify password, return token
# GET  /auth/me        — return current user from token

# JWT config:
# Algorithm: HS256
# Expiry: 7 days
# Secret: from JWT_SECRET env var
```

Requirements:
- Use `passlib[bcrypt]` for password hashing
- Use `python-jose[cryptography]` for JWT
- Return `TokenResponse` from both register and login
- Create `get_current_user` dependency for protected routes
- Store users in Supabase `users` table (schema created in Task 1.1)

**Verification**: 
```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@test.com","password":"testpass123"}'
# Returns: {"access_token": "...", "token_type": "bearer"}
```

---

### Task 3.3 — Session Endpoints

**Estimated agent time**: 15 minutes
**Files to create**: `api/sessions.py`

```python
# Endpoints to implement:
# POST /sessions        — start a research session (streams output)
# GET  /sessions        — list current user's sessions (paginated)
# GET  /sessions/{id}   — retrieve a specific session
```

The `POST /sessions` endpoint is the most important. It must:
- Accept `SessionCreate` body
- Run `research_manager.run(query, route_override=route_override)` as a stream
- Yield server-sent events (SSE) for each chunk: `data: {chunk}\n\n`
- On completion, persist the session to Supabase `research_sessions`
- Include LangFuse trace URL in the persisted session record

SSE streaming pattern:
```python
from fastapi.responses import StreamingResponse

async def stream_research(query: str, route_override: str | None):
    async def generate():
        report_chunks = []
        async for chunk in manager.run(query, route_override=route_override):
            report_chunks.append(chunk)
            yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream")
```

**Verification**:
```bash
TOKEN="<token from register>"
curl -X POST http://localhost:8000/sessions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "What is GitLabs blameless post-mortem policy?"}'
# Returns streaming SSE output ending with "done: true"
# Then: curl http://localhost:8000/sessions -H "Authorization: Bearer $TOKEN"
# Returns list with 1 session
```

---

### Task 3.4 — LangFuse Integration

**Estimated agent time**: 10 minutes
**Files to modify**: `api/sessions.py` (add tracing around the run call)

Requirements:
- Initialise `langfuse.Langfuse()` client using env vars
- Wrap each `research_manager.run()` call in a LangFuse trace
- Record: query, route, token count, cost_usd, latency_ms
- Store the trace URL (`https://cloud.langfuse.com/trace/{trace_id}`)
  in the session record so the frontend can link to it

```python
# Pattern:
from langfuse import Langfuse
lf = Langfuse()

trace = lf.trace(name="research-session", input={"query": query})
# ... run research ...
trace.update(output={"route": route, "cost": cost})
trace_url = f"https://cloud.langfuse.com/trace/{trace.id}"
```

**Verification**: After running a session, the LangFuse dashboard at
`cloud.langfuse.com` shows a trace with the correct query and route.

---

### Task 3.5 — Dockerfile and docker-compose

**Estimated agent time**: 10 minutes
**Files to create**: `Dockerfile`, `docker-compose.yml`

```dockerfile
# Dockerfile — FastAPI service only
FROM python:3.12-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```yaml
# docker-compose.yml — local dev stack
services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - SUPABASE_URL=${SUPABASE_URL}
      - SUPABASE_SERVICE_KEY=${SUPABASE_SERVICE_KEY}
      - SUPABASE_DB_URL=${SUPABASE_DB_URL}
      - LANGFUSE_PUBLIC_KEY=${LANGFUSE_PUBLIC_KEY}
      - LANGFUSE_SECRET_KEY=${LANGFUSE_SECRET_KEY}
      - LANGFUSE_HOST=${LANGFUSE_HOST}
      - JWT_SECRET=${JWT_SECRET}
      - SENDGRID_API_KEY=${SENDGRID_API_KEY}
    env_file:
      - .env
```

**Verification**: `docker-compose up` starts the API service.
`curl http://localhost:8000/docs` returns the OpenAPI UI.

---

### Task 3.6 — GitHub Actions: Deploy FastAPI to Railway

**Estimated agent time**: 5 minutes
**Files to create**: `.github/workflows/deploy-railway.yml`

```yaml
name: Deploy FastAPI to Railway

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install Railway CLI
        run: npm install -g @railway/cli
      - name: Deploy to Railway
        env:
          RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}
        run: railway up --service deep-research-api
```

**Note for developer**: Set `RAILWAY_TOKEN` in GitHub Secrets.
Set all env vars (OPENAI_API_KEY etc.) in the Railway dashboard
under the service's Variables tab.

---

## Part B — React Frontend

### Task 3.7 — React Project Scaffold

**Estimated agent time**: 10 minutes
**Files to create**: `frontend/` directory with Vite + React + Tailwind + shadcn/ui

```bash
# Commands to scaffold (run these, don't recreate manually):
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npx tailwindcss init -p
npx shadcn-ui@latest init
npm install @radix-ui/react-scroll-area lucide-react
```

`frontend/src/lib/api.ts` — typed API client:
```typescript
const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export async function startSession(
  query: string,
  token: string,
  onChunk: (chunk: string) => void,
): Promise<void> {
  const res = await fetch(`${API_BASE}/sessions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ query }),
  });
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const text = decoder.decode(value);
    for (const line of text.split("\n")) {
      if (line.startsWith("data: ")) {
        const data = JSON.parse(line.slice(6));
        if (data.chunk) onChunk(data.chunk);
      }
    }
  }
}

export async function getSessions(token: string): Promise<Session[]> {
  const res = await fetch(`${API_BASE}/sessions`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return res.json();
}
```

**Verification**: `cd frontend && npm run dev` starts without errors.

---

### Task 3.8 — Three-Panel Layout

**Estimated agent time**: 20 minutes
**Files to create**: 
- `frontend/src/App.tsx`
- `frontend/src/components/SessionPanel.tsx`
- `frontend/src/components/ResearchPanel.tsx`
- `frontend/src/components/CitationCard.tsx`

Layout requirements:
- Three-column layout: session history (left, 20%), research panel (center, 60%), trace info (right, 20%)
- On mobile: single column, tabs between panels
- Use shadcn/ui `Card`, `ScrollArea`, `Badge`, `Button` components
- Dark/light mode toggle in the header

**SessionPanel** (left):
- List of past sessions: query text (truncated), route badge, relative timestamp
- Clicking a session loads it into the ResearchPanel
- "New Research" button at the top clears the panel

**ResearchPanel** (centre):
- Query input with a "Research" button
- Route selector: Auto / Quick / Deep / Technical / Comparative
- While streaming: show "Route: technical" badge as soon as route is determined
- Report rendered as markdown (use `react-markdown`)
- Citation cards below the report — one card per unique source
- Cost and latency summary line: "Cost: $0.12 · 34s · 5 sources"

**CitationCard**:
```typescript
interface CitationCardProps {
  sourceName: string;
  sectionTitle: string;
  sourceUrl: string;
}
// Renders as a small card with an external link icon
```

**Trace link** (top-right of header):
- If current session has a `trace_url`, show a clickable badge: "🔍 View trace"
- Opens LangFuse in a new tab

**Verification**: The three-panel layout renders in browser at localhost:5173.
A research query streams output into the centre panel.

---

### Task 3.9 — Auth Flow

**Estimated agent time**: 15 minutes
**Files to create**: `frontend/src/components/AuthModal.tsx`

Requirements:
- Modal with Register / Login tabs
- On success: store JWT in React state (NOT localStorage — memory only)
- Pass token in `Authorization: Bearer` header on all API calls
- Show user email in header when logged in
- "Sign out" clears the token from state

**Verification**: Register a new user, log in, run a research session,
sign out, and confirm sessions are no longer visible.

---

### Task 3.10 — Vercel Deployment

**Estimated agent time**: 5 minutes
**Files to create**: `frontend/vercel.json`

```json
{
  "buildCommand": "npm run build",
  "outputDirectory": "dist",
  "framework": "vite",
  "env": {
    "VITE_API_URL": "https://your-railway-service.railway.app"
  }
}
```

**Note for developer**: 
1. Push to GitHub. 
2. Connect the `frontend/` subdirectory to a new Vercel project.
3. Set `VITE_API_URL` to the Railway service URL in Vercel's Environment Variables.

Also create `.github/workflows/deploy-hf.yml`:
```yaml
name: Deploy Gradio to Hugging Face

on:
  push:
    branches: [main]

jobs:
  deploy-hf:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Push to Hugging Face
        env:
          HF_TOKEN: ${{ secrets.HF_TOKEN }}
        run: |
          git config user.email "action@github.com"
          git config user.name "GitHub Action"
          git remote add huggingface https://user:$HF_TOKEN@huggingface.co/spaces/cameronbell/deep-research-workflow
          # Push only the files HF Spaces needs
          git subtree push --prefix=. huggingface main || true
```

**Verification**: After merging to main, the Hugging Face Space updates
within 2 minutes and the Gradio demo is still functional.

---

## Phase 3 Done When

- [ ] `docker-compose up` starts the FastAPI service cleanly
- [ ] `POST /auth/register` and `POST /auth/login` work and return JWT tokens
- [ ] `POST /sessions` streams a research session and persists to Supabase
- [ ] LangFuse dashboard shows traces with route and cost data
- [ ] React app at localhost:5173 renders three panels
- [ ] Source citation cards appear below the report
- [ ] React app deployed to Vercel — public URL accessible to anyone
- [ ] FastAPI deployed to Railway — Vercel frontend can reach it
- [ ] Gradio on HF Spaces still functional after GitHub Actions deploy workflow
- [ ] `docs/design-decisions.md` updated with: JWT rationale, React vs Next.js,
      Railway choice, two-remote setup
