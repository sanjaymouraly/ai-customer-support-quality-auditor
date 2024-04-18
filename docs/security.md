# Security and data handling

This repository is a local-first development foundation, not a security-certified or hardened
production service. Conduct a threat model, privacy review, dependency review, and deployment
assessment before using real customer data.

## Deployment boundary and authentication

- The FastAPI service is open when `API_ACCESS_TOKEN` is empty. That is intended only for a trusted
  local single-user development environment. Do not expose the API port to a LAN, public network, or
  shared workspace without additional access controls.
- When configured, `API_ACCESS_TOKEN` applies a shared bearer token to protected API routes. `/`,
  health, and OpenAPI documentation remain open. The shared token does not provide user accounts,
  roles, reviewer identity, per-user audit, rate limiting, or key rotation.
- The Streamlit reviewer ID is self-entered. Distinct reviewer IDs do not prove distinct people.
  Annotation-agreement output is not authenticated independent review.
- Put a network-facing deployment behind TLS, a trusted reverse proxy, strong
  authentication/authorization, request/rate limits, a secret manager, and monitored egress. Restrict
  `CORS_ALLOWED_ORIGINS` and bind only intended interfaces. Do not treat the optional token as a
  complete production boundary.
- The Settings provider-test endpoint accepts a one-time key and optional endpoint from the local UI.
  On a shared/network deployment, protect it and restrict server egress/allowed endpoints; otherwise
  an authorized caller could direct a provider test to a user-supplied host.
- API responses set `X-Content-Type-Options`, `X-Frame-Options`, and `Referrer-Policy` headers.
  Request bodies are size-bounded before parsing, in addition to Pydantic field limits.

## Provider credentials and saved connections

- Environment variables are the recommended credential path for shared deployments. They are read by
  the API process and are not included in saved audits or ordinary API responses.
- A key saved from Settings is encrypted at rest with Fernet. The encryption key comes from
  `AUDITOR_SECRET_KEY`, or a generated `0600` file at `data/.provider_key`. The API returns only a
  masked hint; decrypted keys are not sent back to the browser or written to audit results.
- This is encryption at rest, not a hardware-backed vault or KMS. Anyone who can read the data
  directory and process environment can decrypt saved keys. Restrict filesystem access, encrypt
  backups, and use a managed secret store for production.
- The connection-test key is transient to that request. Do not submit it over an untrusted network.
- Deleting a saved connection removes the encrypted key for that provider. Losing or changing the
  encryption key requires re-entering saved provider keys.

## Submitted data and external providers

- Single and batch audit requests persist customer text, candidate response, facts, and evaluation
  results in the configured database. Human comments are also stored. Treat the database, backups,
  exports, and filesystem as sensitive.
- Deterministic/offline mode makes no external model call. LLM/hybrid modes transmit the customer
  message, candidate response, supplied facts/actions/escalation context, category/severity, and
  retrieved policy excerpts to the selected provider. Review authorization, provider contracts,
  retention, data residency, and regulatory requirements before use.
- Responder generation sends the customer message, facts, category, and retrieved policy excerpts to
  the selected responder provider. Generated text is not trusted until it has been audited.
- Avoid passwords, CVVs, payment credentials, access tokens, secrets, and unnecessary personal data
  in support messages, case facts, policies, reviewer IDs, and reviewer comments.
- Output-side redaction covers a limited set of common patterns (payment-card-like numbers, SSNs,
  email addresses, and some Indian-format phone numbers) in model-generated result text and JSON
  exports. It does not anonymize input before transmission, delete text from SQLite, identify all PII,
  or guarantee redaction of names, addresses, or unique identifiers. Do not treat it as a DLP system.

## Application safeguards

- Pydantic input bounds, a 500-case batch maximum, bounded uploads, extension checks, PDF page/text
  limits, path-safe policy IDs, and immutable policy versions.
- Prompt instructions identify support text, facts, expected actions, and imported policy content as
  untrusted data. A small phrase filter is applied to customer/candidate text; neither it nor prompt
  delimiters defeat all prompt injection. Provider output is schema-validated, citations are checked
  against supplied excerpts using normalized substring matching, and unsupported statements are
  labeled as hypotheses.
- Deterministic zero scores and hard-stop flags cannot be cleared by LLM output, rubric reweighting,
  thresholds, or an `Approve` human-review submission. The review API stores a separate record and
  does not rewrite the machine audit.
- Project/workspace policy scoping limits which policy catalogue is retrieved for new audits. It is
  not an authorization boundary between users; the API has no per-user project ACL.
- CSV formula-injection prefixes, HTML escaping, and omission of raw customer/candidate text from API
  summary exports. JSON export redacts selected common patterns from result strings. Exported
  evidence can still contain sensitive contextual information; review exports before sharing.
- Provider errors returned through API endpoints are sanitized to avoid returning raw SDK request
  metadata. Application and server logs should still be treated as sensitive.
- Audit retention utility is dry-run by default; it deletes only with explicit `--apply`.

## Operational controls and limitations

- `DAILY_TOKEN_BUDGET` and `DAILY_SPEND_LIMIT_USD` use estimated worst-case reservations and optional
  operator-provided rates. Character-based token estimates and prices can differ from actual billing.
  The locking is process-local and does not provide a distributed quota under multiple workers.
- The API has no built-in per-IP rate limiting, multi-tenant isolation, audit encryption, malware
  scanning, or distributed job queue.
- SQLite is the local default. Protect database files and backups with OS permissions and encrypted
  storage. PostgreSQL is optional but was not tested here.
- Policy uploads are parsed as text/PDF/JSON and stored locally. Validate provenance and effective
  dates; do not upload secrets or uncontrolled documents. PDF limits reduce but do not eliminate
  parser/resource risks.
- Non-English evaluations have limited rule coverage and are routed to human review when detected;
  this is not a validated multilingual safety mechanism.
- Local model output is non-deterministic and may be internally inconsistent. Model fallback is
  labeled, but a successful fallback-free run is still not an accuracy guarantee.
- Never rely on this tool alone to make legal, financial, identity, fraud, security, or other
  high-impact customer decisions. It does not perform real business actions.

## Reporting vulnerabilities

Do not open a public issue containing customer data, API keys, or exploit details. Contact the
repository owner through a private channel and include a minimal reproducible description with
secrets removed. No public security-response SLA is currently defined.
