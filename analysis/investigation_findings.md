# Root-Cause Investigation: Case Law Research Assistant Cost Anomaly

## What was observed
AI cost per request for Case Law Research Assistant rose sharply starting
late November 2025, from a stable baseline of ~$0.0055/request to ~$0.0116/request
— a 111% increase — and remained elevated for the rest of the observed period.

## Investigation
The blended `total_cost_per_request` metric (AI cost + allocated shared
infrastructure cost) did not clearly show this change, since infrastructure
cost dominates the blended total for this product. Isolating AI cost
specifically (`ai_cost_per_request`) revealed a clean, sharp jump.

Two possible explanations were tested:

1. **Usage growth** — average daily requests rose from 841 to 1,022
   (+21%) across the same period. This is real growth, but far too small
   to explain a 111% cost-per-request increase on its own.
2. **Context length** — average tokens_in per request rose from 2,752 to
   5,772 (+110%) over the same period, closely matching the cost increase.

**Conclusion:** the cost increase is driven by context length, not usage
growth. This is consistent with a regression in retrieval/context-filtering
behavior — the system sending more raw document text per request than
necessary, rather than filtering to relevant excerpts before querying the model.

## Recommendation
Restoring context length to pre-regression levels (e.g., via improved
retrieval-based filtering) would:
- Reduce AI cost per request by an estimated **52.3%**
- Save an estimated **$2,263/year** in direct AI inference costs for this
  product alone, at current volume

This is a modest absolute figure for a single product, but the underlying
pattern — unnoticed context-length creep — is exactly the kind of
inefficiency that compounds silently across products if not caught early
via unit-cost monitoring. This is presented as a recommendation for the
owning team to evaluate, consistent with an enablement-focused FinOps model
rather than a mandated change.