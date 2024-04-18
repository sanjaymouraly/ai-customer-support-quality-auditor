# Evaluation design and limitations

## Purpose

The auditor provides review support for a candidate customer-service response. It is not an autonomous agent, an approval oracle, or an action-taking system. It does not issue refunds, change accounts, send messages, or trigger real escalations.

Use verified facts and approved policy documents. An omitted fact/policy excerpt is not evidence that a claim is false, and a rule not firing is not evidence that a response is safe.

## 0–4 dimensions and default weights

The rubric and anchors live in `auditor/evaluation/schemas.py`.

| Dimension | Default weight | What it checks |
| --- | ---: | --- |
| Factual & contextual accuracy | 0.15 | Candidate statements against supplied facts. |
| Completeness & relevance | 0.12 | Coverage of expected actions/customer questions. |
| Policy grounding & compliance | 0.18 | Known rule conflicts and retrieved policy evidence. |
| Hallucination & unsupported claims | 0.15 | Certain unsupported refund, delivery, tracking, and amount claims. |
| Required actions & resolution | 0.10 | Steps and practical resolution guidance. |
| Tone, empathy & clarity | 0.06 | Some lexical tone and politeness cues. |
| Privacy & safety | 0.10 | Selected unsafe disclosure/request patterns. |
| Escalation correctness | 0.08 | Expected versus apparent response escalation. |
| Actionability & next steps | 0.06 | Ownership, next step, timeline, or concrete resolution. |

Each dimension has anchor descriptions for scores 0 through 4. A score is a rule/judge conclusion, not a measured probability. Default weights sum to 1; configured weights are validated and normalized before scoring.

The composite is:

```text
overall = round(100 × Σ(normalized_weight[d] × score[d] / 4))
```

Weights and thresholds can be edited in Settings and are snapshotted with each audit. Setting a dimension weight to zero removes its contribution to the composite but does **not** disable hard-stop rules.

## Decisions and thresholds

Defaults are in `auditor/evaluation/rubric.py` and can be changed only while preserving order:

- `Approve`: score at or above 85, absent a hard stop or critical under-escalation.
- `Needs Revision`: score at or above 65 and below the approval threshold.
- `Human Review Required`: score at or above 40 and below the revision threshold.
- `Critical Failure`: below the human-review threshold, or a hard stop/zero in a critical policy or privacy dimension.
- `Escalation Required`: an under-escalation can produce this disposition; high/critical urgency overrides an otherwise approving result.

The exact outcome also depends on configured thresholds and escalation rules. The API records a reason and separate escalation verdict; consumers should not infer an automatic customer-facing action.

## Hard-stop boundary

The deterministic baseline can mark a hard stop for a zero score in privacy, policy compliance, or hallucination, or for a detected unauthorized-refund violation. Hard stops cannot be lifted by a model response, reweighting, threshold changes, or the human-review API. The review endpoint rejects an `Approve` disposition for a hard-stop audit. A non-approval human review may still be saved for discussion/adjudication.

These checks are incomplete by nature. A hard stop is a conservative safeguard when detected, not a guarantee that every unsafe response is caught.

## Evaluation modes

- **Deterministic/offline:** local rules only; no provider call. This is the recommended mode for restricted text and smoke testing.
- **Hybrid:** deterministic scores are the baseline. A model can lower, but not raise, the deterministic score for factual/policy/safety-oriented dimensions. For completeness, tone, resolution guidance, and actionability, the deterministic and model scores are averaged (rounded). A deterministic zero remains zero. The deterministic hard-stop flag and decision are retained.
- **LLM-assisted:** the model judges completeness, tone, resolution guidance, and actionability; the other dimensions remain deterministic. Any deterministic zero stays zero, and hard-stop results remain unchanged. This is deliberately not a fully model-controlled decision.

For model-assisted modes, inputs are sent to the configured provider. The prompt treats customer text, candidate responses, facts, and imported policy excerpts as untrusted data. Compatible OpenAI-style providers and the local Ollama adapter are asked for a structured JSON object (`response_format={"type":"json_object"}`); the application validates the schema, attempts a bounded repair, and otherwise falls back to deterministic evaluation. Unsupported explanations are labeled as hypotheses. Evidence is surfaced as matched only when it appears as an exact normalized substring of supplied text; this is a basic provenance check, not semantic proof. Some common PII patterns are redacted from model-generated result text, but submitted text is not anonymized before provider transmission.

Provider failures, timeouts, and malformed output fall back to deterministic evaluation and are labeled in the result. A fallback is not a successful model audit. A successful judge call is also not proof of correctness.

### Local model smoke-test evidence

[`docs/examples/ollama_hybrid_audit.json`](examples/ollama_hybrid_audit.json) preserves one real
hybrid audit against local Ollama `qwen2.5:3b` with a fictional shipping case. It completed HTTP 200
in 165.5 s with no fallback, scored 42 / `Human Review Required`, and correctly retained the
deterministic non-approval route. One or more judge citations could not be verified as exact
substrings and were labeled as hypotheses. The model's reasoning was not consistently aligned with
its scores. This is a single non-deterministic smoke test, not a benchmark, accuracy estimate, or
model comparison. A separate `gemma:2b` attempt timed out / returned malformed JSON and fell back to
deterministic evaluation, demonstrating the intended failure path rather than a successful audit.

## Policy evidence

Policy retrieval in `auditor/policies/retrieval.py` uses lexical token overlap plus policy-keyword and category hints. It filters out inactive, not-yet-effective, and expired documents. Explicit policy IDs and workspace policy scope restrict retrieval; absent IDs use the category-to-policy map. The UI/API expose the actual excerpts and versions used.

Limitations:

- It is not a vector search, entailment checker, or complete policy reasoning engine.
- Paraphrases, non-English messages, contradictory documents, or poorly structured uploads may retrieve weak or misleading evidence.
- Policy content and metadata are administrator-supplied; the seven bundled examples are fictional and must be replaced with approved documents.
- A missing retrieved section must be reviewed; it is not proof the policy has no relevant rule.

## Escalation

`auditor/escalation/rules.py` compares an expected escalation (if supplied; otherwise inferred from categories, facts, severity, and trigger phrases) with the response's apparent escalation. It checks clear language such as security/billing/supervisor handoffs, identity verification, and requests for more information. A mention of a team alone should not count as an executed handoff; the rules look for action language and handle optional consent wording.

This is still a lexical heuristic. It cannot verify that a real ticket, transfer, manager review, account lock, or security incident exists. The app never executes one. Use an approved escalation runbook and a human for sensitive cases.

## Confidence and evidence

The `confidence` field is an **uncalibrated heuristic**, not a probability and not a validated confidence interval. Deterministic confidence is derived from fixed dimension heuristics and reduced by uncertainty flags. Model-assisted confidence is bounded by that heuristic and the provider's self-reported confidence; neither is calibrated. Interpret evidence/uncertainty fields directly rather than relying on this number.

The rules are primarily English-oriented. When a language is explicitly supplied in facts or common Spanish markers are detected, the engine adds an uncertainty flag and changes an otherwise approving disposition to `Human Review Required`. This is a conservative indicator only; language detection and multilingual coverage have not been validated. A bilingual reviewer should assess non-English cases.

## Calibration and benchmark provenance

`data/synthetic/cases.json` contains 170 fictional cases across 18 categories: 63 positive, 96 negative, and 11 borderline synthetic reference dispositions. No case is human-reviewed. The dataset was inspected and used while implementing rules, so it is development data—not a holdout, not an unbiased sample, and not evidence of production accuracy.

`python scripts/run_benchmark.py` reproduces a deterministic comparison with those synthetic reference dispositions and writes `data/annotations/benchmark_results.json`. The report is labeled exploratory; do not call its agreement figure validated accuracy or use it to claim model superiority. The repository contains one local Ollama smoke-test artifact, not a live-provider benchmark or external validation set.

For real calibration, collect a stratified, authorized, anonymized sample; obtain two or more independent reviews per case; adjudicate disagreements; freeze a separate holdout set; preregister thresholds; and report category/severity-stratified error, false-negative rates for critical failures, confidence calibration, and drift. Reviewer identities in this version are self-entered and not authenticated; distinct IDs do not establish independent people. See [Annotation guidelines](annotation_guidelines.md).
