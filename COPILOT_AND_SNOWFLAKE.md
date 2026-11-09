# Integration contract — future Siemens environment

## Copilot Studio

- The **Copilot Studio coordinator** should call the protected API for supplier context, specialist evaluations and four-gate decisions.
- Specialist A: demand, capacity, ramp-up and localization (A1–A5)
- Specialist B: production-system quality, flow, routines and skill building (B1–B7)
- Specialist C: dependencies, disruptions, volatility and structural flexibility (C1–C4)
- `GET /openapi.json` exposes the backend operations. For a production custom connector, configure Entra ID OAuth, tenant-approved authentication, secrets management and scopes. Demo Basic Auth is not suitable for production.
- Suggested tool flow: get supplier; get assessment and evaluations; use matching intervention names and source limits; run economic feasibility; present evidence gaps; request human approval. Do not let generative text override the numeric API decision or automatically approve.
- `POST /api/assistant` is **only a deterministic simulator**. Microsoft Copilot is **not connected** to the delivered app.
- Current API sessions are per-browser demo sessions. Production Copilot use requires user identity/tenant scoping or a durable shared case ID and service-principal authorization. That is not yet implemented.

## Snowflake

Four recommended read-only subject areas for future approved views:

| Proposed view domain | Fields relevant to a supplier assessment | Caution |
|---|---|---|
| Supplier risk | `supplier_id`, `critical_dependency`, `continuity_flag`, `risk_summary` | Normalize supplier IDs and protect risk data |
| Performance | `supplier_id`, on-time delivery, yield, proven monthly capacity, required monthly capacity, lead time | Different time periods and sources require reconciliation |
| Evaluation | `supplier_id`, assessment status, priority gaps, review note, evidence timestamp | Survey and team 16-criterion mapping need human validation |
| Relationship management | `supplier_id`, account owner, forecast status, willingness | Do not confuse tentative interest with contractual agreement |

The website currently shows a snapshot of **synthetic** records held in `data/demo_catalog.json`. There are no real Snowflake credentials, schemas or queries in this repository. A real connector must use Siemens-approved read-only roles and views; connect only after defining source contracts, access control and freshness. The code does not claim that those views already exist.

## Backend decision rules

- Scores are interpreted only when evidence exists. Unknown is not zero.
- 3.1/5 is a reference benchmark, **not** automatic GO/NO-GO.
- Probability of success = technical closure × on-time completion × sustained improvement.
- Siemens expected net = potential gain × probability of success − Siemens intervention costs.
- Supplier net = supplier contribution + retained savings + productivity relief + third-party upside − supplier CapEx − supplier OpEx.
- Technical, timing, positive Siemens net, and supplier willingness **Yes** are the four feasibility gates.
- An approval requires all gates plus diagnosis/solution validation and an explicit reviewer note. Edits to ratings, shortlist, questionnaire or financials reopen the decision.
