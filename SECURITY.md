# Security policy

This is a local-first decision-support prototype, not a security-certified production system. Read the full [security and data-handling guide](docs/security.md) before using real support data or exposing any service beyond a trusted local environment.

Key points:

- An empty `API_ACCESS_TOKEN` means the protected API routes are open. Configure a strong shared token and a TLS/authentication boundary before network exposure; the token is not a multi-user identity system.
- Deterministic/offline mode makes no external model call. LLM/hybrid modes send the submitted support message, response, facts/actions, and retrieved policy excerpts to the selected provider.
- Submitted text and human comments are stored in the configured database. Output redaction is partial; it is not input anonymization or a DLP system.
- Do not enter passwords, CVVs, payment credentials, API keys, or unnecessary personal information. Do not rely on the auditor for autonomous customer-impacting decisions.
- Prompt filters, model evidence matching, token caps, and export sanitizers are useful safeguards but are not complete security boundaries.

For vulnerability reports, do not include secrets or customer data in public issues. Use a private channel to contact the repository owner; no public response SLA is currently defined.
