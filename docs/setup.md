# Setup and operations

## Requirements

- Python 3.11+
- Optional: a reachable local Ollama server or an authorized, server-side provider key for
  model-assisted evaluation.
- Optional: Docker Engine with the Compose plugin for the container path.

Deterministic/offline evaluation needs no network access, API key, or model download.

## Install from source

```bash
python -m venv .venv
source .venv/bin/activate             # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
cp .env.example .env
```

`requirements.txt` installs runtime dependencies. The editable install above adds test, lint, and
screenshot extras. `.env` is gitignored; never commit provider keys or real customer data.

## Run locally

Terminal 1:

```bash
uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000
```

Terminal 2:

```bash
streamlit run frontend/app.py --server.address 0.0.0.0 --server.port 8501
```

- UI: <http://localhost:8501>
- Health: <http://localhost:8000/api/health>
- OpenAPI/Swagger UI: <http://localhost:8000/docs>

The API initializes tables, ensures the `default` workspace, and loads the policy directory at
startup. SQLite is the default. The forward migration helper supports SQLite and PostgreSQL, but a
new PostgreSQL installation is optional and PostgreSQL migrations were not tested here. For a
production schema lifecycle, adopt a reviewed migration system rather than relying only on startup
DDL.

`API_BASE_URL` configures the Streamlit server's API target (default `http://localhost:8000`). In
Compose it is `http://api:8000`. The browser does not call the API directly.

## Environment variables

See `.env.example` for the complete template.

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | SQLAlchemy URL; default `sqlite:///./auditor.db`. |
| `API_ACCESS_TOKEN` | Optional shared bearer token for protected API routes. Leave blank only for trusted local single-user use. |
| `AUDITOR_SECRET_KEY` | Encrypts saved provider keys at rest. If blank, a `0600` key file is generated at `data/.provider_key`. |
| `CORS_ALLOWED_ORIGINS` | Comma-separated browser origins allowed to call the API. |
| `MAX_REQUEST_BYTES` | Pre-parse JSON request size cap; default 2 MB. |
| `MAX_UPLOAD_MB` | Maximum policy upload size; default 10 MB. |
| `REQUEST_TIMEOUT_S` | Provider HTTP request timeout. |
| `PROVIDER_RETRY_ATTEMPTS` | Provider call attempts, clamped to 1–5; default 2. |
| `DAILY_TOKEN_BUDGET` | Estimated worst-case token reservation cap per UTC day. |
| `DAILY_SPEND_LIMIT_USD` | Optional estimated-cost cap; `0` disables it. |
| `PROVIDER_PRICING_JSON` | Operator-maintained current input/output price per million tokens. No rates are assumed. |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` | OpenAI adapter configuration. |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | Anthropic adapter configuration. |
| `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `OPENROUTER_MODEL` | OpenRouter configuration. |
| `CUSTOM_API_KEY`, `CUSTOM_BASE_URL`, `CUSTOM_MODEL` | Any OpenAI-compatible endpoint. |
| `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_API_KEY` | Local Ollama OpenAI-compatible endpoint; default URL `http://localhost:11434/v1`. |
| `*_HEADERS_JSON` | Optional JSON object of provider-specific HTTP headers. Prefer API-key variables for secrets. |

The API enforces `MAX_UPLOAD_MB`; Streamlit also applies `.streamlit/config.toml`
(`server.maxUploadSize`, currently 10 MB). Keep them aligned and restart Streamlit after editing its
configuration. The lower cap wins.

## Provider connections

The UI and API support two configuration paths:

1. **Environment variables** (recommended for shared/server deployments).
2. **Saved connections** in Settings → Providers & models. A saved field overrides the matching
   environment value; unset fields continue to use the environment.

Saved profiles live in `data/provider_connections.json`. API keys are encrypted with Fernet using
`AUDITOR_SECRET_KEY`, or a generated `0600` file at `data/.provider_key`. The API returns only a
masked hint, never the decrypted key, and keys are never written to audits. This is encryption at
rest, not a hardware-backed vault: protect the data directory and process environment, and use a
managed secret store for shared deployments.

The optional temporary key in the connection test is used for that one request only and is not
stored. Model discovery uses the saved/environment configuration. Connection tests and discovery can
make outbound requests; restrict egress in shared environments.

### Local Ollama example

```bash
ollama pull qwen2.5:3b
ollama serve
```

Use base URL `http://localhost:11434/v1`, model `qwen2.5:3b`, and a generous timeout for CPU-only
inference (the captured real run used 300 s and completed in 165.5 s). Local model output is
non-deterministic; malformed output falls back to deterministic evaluation and is labeled as a
fallback.

## Workspaces and demo data

- The API creates a `default` workspace on startup.
- `python scripts/seed_db.py --n 60` writes synthetic audits only if the configured database contains
  no audit records. It seeds 60 audits into `default` and 30 into `eu-support` under batch ID
  `synthetic_demo_seed_v1`. It refuses to append to an existing audit history.
- Workspaces scope new audits and can restrict the active policy catalogue through `policy_ids`.
- Seeded rows are marked synthetic and are excluded from annotation-agreement calculations.
- The test suite uses a temporary SQLite file and does not need a live API.

Back up the database before changing settings or running retention with `--apply`.

## Batch resume

Send a `batch_id` and set `resume: true` to resume an interrupted batch. Each saved item carries a
SHA-256 digest of its case input plus the active rubric weights/thresholds. A changed case,
provider/model/mode, or rubric produces a hash mismatch instead of silently reusing a prior result.
Use a new `batch_id` for intentionally changed input. Batches are limited to 500 cases per request;
external-provider usage is reserved per attempted case.

## Screenshots

```bash
python -m pip install -e ".[screenshots]"
python -m playwright install chromium
# API and Streamlit must be running with demo data
python scripts/capture_screenshots.py
```

The script drives the real UI, creates real temporary audits, trims blank capture space, and deletes
its temporary audits through the API. It does not mock the UI or API.

## Retention

`python scripts/prune_audits.py --days 365` is a dry run. Add `--apply` to delete audits, linked human
reviews, and provider-usage rows older than the cutoff. Policy documents and custom scenarios are not
deleted by that script. Review the output and back up the database first.

## Docker Compose

```bash
cp .env.example .env
# Set a strong API_ACCESS_TOKEN if anything beyond localhost can reach the ports.
docker compose up --build
```

Compose uses an API container, a Streamlit container, a named SQLite volume, a writable API data
mount, and a read-only frontend data mount. The frontend calls the API through the published host
port (`host.docker.internal:8000`) so it also works where container-to-container traffic is blocked;
on a normal Docker network, `API_BASE_URL=http://api:8000` can be used instead. The image build,
container startup, API health endpoint, and UI-to-API connection were exercised in the development
environment. It remains a local-development configuration, not a hardened production deployment.

## Troubleshooting

- **Backend unreachable:** check `/api/health`, `API_BASE_URL`, and port 8000.
- **401 responses:** ensure Streamlit and API use the same `API_ACCESS_TOKEN`.
- **Saved key cannot be decrypted:** restore the original `AUDITOR_SECRET_KEY` / `data/.provider_key`
  or re-enter the key. A corrupt key file raises an explicit error rather than silently generating a
  new key.
- **Policy evidence missing:** check policy ID, active status, effective/expiry dates, workspace
  scope, category, and retrieved excerpts. Lexical retrieval may miss paraphrases or non-English
  queries.
- **Provider unavailable:** check server-side key/model/base URL, network access, model discovery, and
  timeout. API responses intentionally avoid returning raw provider exceptions.
- **Model fallback:** the result is labeled when the judge fails, times out, or returns invalid JSON.
  A fallback is not a successful model audit; retry with a smaller prompt/model or inspect the local
  model server.
- **Uploads rejected:** supported extensions are `.md`, `.txt`, `.json`, `.pdf`, `.csv`, and `.jsonl`;
  check `MAX_UPLOAD_MB`. PDF extraction is capped at 100 pages and 200,000 characters.
- **Slow first Ollama call:** the model may need to load into memory. CPU-only 3B inference can take
  several minutes for an audit; this is not a production latency target.
- **Slow first startup:** SQLite schema creation and reading policies happen at API startup. No LLM
  download occurs automatically.
