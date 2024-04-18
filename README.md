# AI Customer Support Response Quality Auditor

Audits AI customer-support replies for tone, accuracy, policy compliance, and resolution quality.

## Features

- Weighted 0–100 score and configurable thresholds — default weights are versioned with the rubric; every audit snapshots its weights, thresholds, and rubric version.
- Hard stops that cannot be overridden by a model — critical policy, privacy, and severe-hallucination findings force non-approval, and the review API rejects Approve for a hard-stopped audit.
- Escalation intelligence — compares expected and apparent escalation, detects under- and over-escalation, and surfaces urgency, destination, and reasoning. It records recommendations; it never contacts a customer or executes an action.
- Workspace/project profiles — group audits and restrict the policy catalogue by project. The demo ships with default and eu-support workspaces.
- Responder generation and model comparison — draft a candidate response with a chosen model, preview the responder prompt, or run two responder outputs through the same audit path side by side.
- Batch auditing with safe resume — CSV/JSON/JSONL/NDJSON upload, per-item error isolation, batch inspection, and SHA-256 content/rubric hashing so changed input cannot silently reuse old results.
- Human review in the loop — separate reviewer scoring, decisions, and notes; hard-stop approval is rejected; agreement analytics require two distinct reviewer IDs (which are not authenticated identities).

## Stack

Python, FastAPI, Uvicorn, Streamlit, SQLAlchemy, Pydantic, pandas, Plotly, HTTPX, OpenAI

## Clone

```bash
git clone https://github.com/sanjaymouraly/ai-customer-support-quality-auditor.git
cd ai-customer-support-quality-auditor
```

## Setup

```bash
# The project ships a Docker Compose setup.
docker compose up --build
```

See `docs/` or the compose file for environment variables and ports.

## Run

```bash
docker compose up --build
```

## Tests

```bash
pytest -q
```

## Notes

- Sample data, when included, is synthetic.

## License

MIT © 2024 [Sanjay Mouraly](https://github.com/sanjaymouraly)
