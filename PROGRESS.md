# Progress

| Phase | Scope | Status |
|---|---|---|
| 0 | Foundation | Done |
| 1 | Prove PayPal | Not started |
| 2 | Data model and money engine | Not started |
| 3 | Agents and negotiation | Not started |
| 4 | Telegram bot | Not started |
| 5 | Web app | Not started |
| 6 | Hero features F2–F5 | Not started |
| 7 | Supporting features and polish | Not started |
| 8 | Deploy and submission | Not started |

---

## Phase 0: Foundation

**Built**
- Repo layout from `SWARM_SPEC.md` section 4, its own git repository (the home directory is
  also a git repo, so Swarm must never be committed from there).
- `docker-compose.yml`: Postgres 16 on host port **5434** (5432/5433 are used by other local
  projects), plus a `swarm_test` database for the test suite.
- Backend: Python 3.11 venv, FastAPI app with `/` and `/health` (reports DB status without
  failing), settings from `.env`, Swarm Clock, SQLAlchemy 2 async session, declarative base with
  UUID + timestamp mixins and constraint naming, Alembic wired to the app settings.
- Frontend: Next.js 16 (App Router) + TypeScript + Tailwind v4, header with a live backend
  status pill, landing page, placeholder routes for `/live`, `/demo`, `/shop/[id]`,
  `/supplier/[id]`, `/connect/[shopId]`, and a REAL/Simulated badge component.
- Tooling: ruff, mypy, pytest (+ asyncio, respx), eslint, prettier, `Makefile`, GitHub Actions CI
  (runs once the repo is pushed), MIT license, README skeleton, `.env.example`.
- `.githooks/commit-msg` with `core.hooksPath` set.

**Works**
- `make check`: ruff, mypy, eslint, tsc, prettier, pytest (10 tests) all green.
- `alembic upgrade head` / `alembic check` run against the local database.
- `npm run build` succeeds.

**Pending**
- Everything from phase 1 on.

**Manual steps for you**
- None.
