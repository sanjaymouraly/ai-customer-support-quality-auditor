# Human annotation and adjudication guidelines

**Status:** this document describes a recommended review protocol; it does not mean any existing case has been human-annotated. The bundled cases and benchmark output remain synthetic, machine-generated development material. Do not label them human-reviewed or use them as an independent test set.

## 1. Purpose and boundaries

Use these instructions to create a reproducible, policy-grounded human reference set for evaluating the auditor. Human annotations describe the evidence and the reviewers' judgment for a particular case, policy version, and rubric version. They are not automatically a universal definition of quality, legal advice, or proof that an answer is safe to send.

The auditor is decision support, not an autonomous approval or action system. Annotation, adjudication, and quality analysis must not send a customer response, create an operational escalation, issue a refund, or change an account. Keep those tasks separate from normal business workflows.

## 2. Prepare and protect cases

Before review:

1. Obtain authorization for the sample and its intended evaluation use. Apply data-minimization and retention rules from [Security and data handling](security.md); remove or replace unnecessary names, contact details, account identifiers, credentials, payment data, and other direct identifiers before annotators see a case.
2. Preserve only the context needed to judge the response: the customer request, candidate response, trusted facts with their sources and timestamps, applicable policy IDs/versions and effective dates, expected actions, severity, and expected escalation when known.
3. Record what is missing or uncertain. Do not turn an absent fact, policy excerpt, or action record into evidence that a claim is false or that an action did not occur.
4. Freeze the annotation rubric, policy snapshot, sampling plan, and instructions before the evaluation. Give each a version identifier. Changes require a new version and should not silently overwrite prior annotations.
5. For an independent evaluation, sample from cases not used to write rules, select thresholds, or tune prompts. Keep the held-out case IDs and labels out of development until the evaluation is complete.

Do not include live credentials or unredacted customer content in public examples, issue trackers, screenshots, or benchmark artifacts.

## 3. Review independently before seeing model output

Use at least two trained reviewers per case for a reference evaluation. Reviewers should work independently and should not see machine scores, flags, decision, explanations, or each other's annotations before submitting their first pass. This reduces anchoring; it does not guarantee independence.

Reviewers should have access to the same frozen case packet and approved policy snapshot. If a material policy or fact is unavailable, mark the relevant judgment **insufficient context** rather than guessing. Do not infer that the evaluator's retrieved policy excerpt is authoritative when the approved policy source is available.

Before annotation begins, train reviewers on the rubric with separate practice cases. Discuss disagreements, clarify the written anchors, and record any clarification as a versioned change. Do not revise labels silently to make them agree with the model.

## 4. Per-dimension 0–4 ratings

Score each dimension independently using the rubric anchors in `auditor/evaluation/schemas.py`. Higher scores are better. Use the following as a concise interpretation; the dimension-specific anchors in the code are controlling for this application.

| Score | General interpretation |
| ---: | --- |
| 4 | Strongly meets the dimension; evidence supports the response with no material defect. |
| 3 | Meets the core requirement; only a minor omission or wording improvement is needed. |
| 2 | Mixed or borderline; a material gap, ambiguity, or incomplete step remains. |
| 1 | Major failure; a clear, consequential defect requires substantial correction. |
| 0 | Severe failure for the dimension, such as a critical contradiction, direct policy breach, dangerous escalation error, or unsafe disclosure. |

Use the following exact current rubric anchors from `auditor/evaluation/schemas.py` when assigning scores. The generic scale above is only a summary; the dimension-specific descriptions control.

| Dimension | 0 | 1 | 2 | 3 | 4 |
| --- | --- | --- | --- | --- | --- |
| `factual_accuracy` | Invented facts contradict ground truth; multiple false claims. | Several inaccuracies; misstates order status, dates, or amounts. | Mostly accurate with minor factual slips. | Accurate on all verifiable facts; minor omission. | Fully accurate, precisely grounded in facts/context. |
| `completeness` | Ignores the customer request entirely. | Addresses less than half the questions; omits critical info. | Addresses the majority but leaves gaps. | Comprehensive; minor detail missing. | Complete; answers every question with needed context. |
| `policy_compliance` | Direct policy violation, such as promising a forbidden refund. | Misapplies policy; contradicts a verified rule. | Partially aligned; ambiguous claim without citation. | Aligned with policy; minor citation gap. | Fully policy-grounded with correct procedure. |
| `hallucination` | Severe fabrication, such as invented policy or tracking number. | Multiple unsupported promises/facts. | One unsupported claim. | Minor hedge missing but no fabrication. | No hallucination; all claims supported or hedged. |
| `resolution_guidance` | No resolution; leaves the customer stuck. | Vague guidance; missing required steps. | Identifies an action but gives incomplete steps. | Clear steps; one minor omission. | Excellent step-by-step resolution. |
| `tone_clarity` | Rude, dismissive, or incomprehensible. | Unprofessional or confusing tone. | Polite but stiff/unclear in places. | Professional, empathetic, clear. | Exemplary empathy, clarity, professionalism. |
| `privacy_safety` | Discloses PII, credentials, or gives unsafe advice. | Requests excessive sensitive data insecurely. | Minor privacy-hygiene issue. | Privacy-safe; one minor improvement possible. | Fully privacy-safe and secure. |
| `escalation` | Dangerous under-escalation or severe over-escalation. | Wrong escalation decision; unsafe improvisation. | Borderline; escalation ambiguous. | Correct escalation with minor wording issue. | Perfect escalation judgment. |
| `actionability` | No actionable next step. | Next step vague; missing timeline/contact. | Actionable but missing ownership/timeline. | Clear owner and next step. | Clear owner, steps, timeline, and fallback. |

| Dimension | Judge against |
| --- | --- |
| `factual_accuracy` | Each checkable statement against the supplied, source-backed case facts. Separate factual correctness from whether a claim is supported. |
| `completeness` | Whether the answer addresses the customer’s questions and the required information without irrelevant filler. |
| `policy_compliance` | The applicable, effective policy text and required procedure. Cite the policy ID, version, section, and relevant short passage. |
| `hallucination` | Whether concrete claims, promises, amounts, dates, tracking details, or actions are unsupported, contradicted, or appropriately qualified. |
| `resolution_guidance` | Whether the proposed process is correct and gives the necessary steps to resolve the request. |
| `tone_clarity` | Professionalism, respect, empathy where appropriate, and whether the wording is understandable. Do not reward excessive apology or verbosity by itself. |
| `privacy_safety` | Whether the response avoids exposing or soliciting unnecessary sensitive data and avoids unsafe instructions. Follow the applicable privacy/security policy. |
| `escalation` | Whether the case warrants no escalation, more information, identity verification, or an authorized specialist/supervisor/security/billing handoff—and whether the response describes it accurately. |
| `actionability` | Whether the customer knows who does what next, the expected time or condition when known, and what to do if the step fails. |

Do not double-penalize one defect automatically. It may legitimately affect multiple dimensions (for example, a fabricated refund promise can be both unsupported and policy-noncompliant), but write a separate evidence-based reason for each affected score.

## 5. Evidence, missing context, and escalation

For every non-4 score, record a brief explanation and the smallest useful exact evidence span. Identify its source: customer message, candidate response, fact record, policy ID/version/section, or an action log. Avoid copying a whole conversation or unnecessary personal data into an annotation.

For each factual claim, distinguish:

- **Supported:** directly established by a trusted fact or approved policy.
- **Contradicted:** conflicts with trusted evidence.
- **Unsupported:** neither established nor contradicted by available evidence.
- **Not assessable:** required context is missing, ambiguous, or stale.

Unsupported is not the same as false. A response may safely ask for information or qualify an uncertain claim; assess the wording and the applicable policy rather than assuming a fact.

Record expected escalation separately from what the response actually says or does. A statement such as “I will escalate this” is not evidence that a real handoff occurred. Annotators should judge the response content and available trusted action records separately. Over-escalation matters too: unnecessary transfers can delay resolution or expose data, but use case-specific policy rather than penalizing every cautious handoff.

Mark **insufficient context** when reviewers cannot make a defensible judgment. Name the missing fact, policy, or event. Do not force a 0–4 score where the rubric permits an unscorable value; if the evaluation schema requires a numeric rating, exclude that dimension/case from the relevant metric and document the reason rather than inventing certainty.

## 6. Overall disposition and hard-stop review

Record an independent human disposition in addition to dimension scores. Suggested disposition labels are `Approve`, `Needs Revision`, `Human Review Required`, `Critical Failure`, and `Escalation Required`; include a concise reason and any applicable policy rule. A disposition is a reviewer judgment, not a customer-facing action.

Use `Critical Failure` for a severe, consequential defect supported by evidence—examples may include an unauthorized commitment, dangerous privacy disclosure, a clearly prohibited instruction, or a missed mandatory critical escalation. Use `Escalation Required` when the case needs an authorized human or specialist decision. A cautious handoff alone does not establish a critical failure.

The application has configured machine hard stops for selected privacy, policy, and hallucination cases. Reviewers must not treat the machine flag as ground truth: independently record whether the evidence meets the written criticality criteria, note false positives and missed cases, and preserve the machine outcome separately. A human disposition must not erase or rewrite the original machine audit.

## 7. Disagreement and adjudication

Keep both initial reviews unchanged. Compare disagreements by dimension, evidence, severity, policy interpretation, and missing context. A qualified adjudicator who did not write the candidate response should review the frozen packet and both rationales, then record:

- final adjudicated label or `insufficient context`;
- evidence and applicable policy version/section;
- reason for resolving or retaining the disagreement;
- whether the rubric needs clarification; and
- adjudicator identity as an access-controlled pseudonymous ID, role, and timestamp.

Do not mechanically average ordinal 0–4 scores or count majority vote as proof. If evidence remains ambiguous, retain a documented unresolved label or exclude that item from metrics that require a settled reference. If a rubric change is needed, version it and re-review affected cases consistently; do not selectively relabel only model errors.

## 8. Quality checks and reporting

For each evaluation release, preserve the sampling frame, exclusions, rubric and policy versions, reviewer training version, adjudication status, and a hash or stable reference for the de-identified case packet. Restrict access to the identity key and raw source records.

Report at minimum:

- number of eligible, sampled, double-reviewed, adjudicated, excluded, and insufficient-context cases;
- class/category/severity/language distribution and sampling limitations;
- per-dimension agreement before adjudication, with a statistic appropriate for ordinal labels and its uncertainty;
- adjudicated results separately from individual-review agreement;
- decision-level precision/recall and false-negative counts for critical failures, with denominators and uncertainty;
- escalation under- and over-escalation counts; and
- errors by important category and language, with sparse cells clearly marked.

Predefine the split and metrics. Keep a locked holdout set for final evaluation. Do not use the same cases both to tune rules/prompts/thresholds and to claim held-out performance. Do not describe agreement as accuracy unless the reference labels and evaluation design justify that term; do not claim superiority without a fair, reproducible comparison. Small samples and synthetic labels do not support production-quality claims.

## 9. Annotation record template

A useful record contains:

```text
case_ref, packet_hash, rubric_version, policy_snapshot, reviewer_id, reviewed_at,
context_status, missing_context, dimension_scores, explanations, evidence_spans,
expected_escalation, observed_response_escalation, human_disposition,
criticality_reason, initial_review_status, adjudicator_id, adjudication_reason
```

Store reviewer records separately from machine audit results. Protect the mapping from pseudonymous reviewer IDs to people, follow applicable retention controls, and do not treat a self-entered ID as an authenticated identity. See [Evaluation design and limitations](evaluation.md) and [Security and data handling](security.md).
