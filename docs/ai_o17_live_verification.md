# AI-O17 Live End-to-End Verification

## Status

Local verification complete on 2026-08-13. The hosted/public half remains
blocked on its separately documented operator prerequisites.

## Objective

Prove, by running the merged repositories rather than test doubles, that one
real scientific question can travel through Knowledge Engine Web, the
Knowledge Engine AI orchestrator, and Knowledge Engine Core and produce a
durable, source-linked Research Session with honest failure behavior.

This milestone verifies integration. It does not promote AI narration to
scientific evidence, certify broad retrieval quality, or enable Research
Copilot on the hosted Render alpha.

## Repositories And Inputs

- `knowledge-engine-core`: current `main`, its local corpus database, the GLP-1
  `sources.csv`, and the GLP-1 Evidence Record JSONL file.
- `knowledge-engine-ai`: current source tree, including the AI-O16 shared
  execution budget.
- `knowledge-engine-web`: current source tree, including AI-O15 durable-session
  requirements and AI-O16 admission controls.
- Ollama: a model already installed on the operator's machine and reachable
  only through the configured localhost endpoint.
- Research Session storage: a dedicated local SQLite database created for this
  rehearsal, never the committed corpus database.

Private absolute paths, database contents, model prompts, and extracted paper
text must not be committed in the report.

## Canonical Question

> Does semaglutide reduce body weight in adults with overweight or obesity?

The question is fixed before execution because the GLP-1 corpus has reviewed,
source-linked evidence and known qualification boundaries. A favorable-looking
answer is not a completion criterion.

## Execution Sequence

1. Verify repository revisions, the Core CLI, corpus inputs, and Ollama.
2. Start the actual Web application with explicit local configuration.
3. Submit the canonical question through `/ask` with Research Copilot enabled.
4. Preserve the resulting Research Session in the dedicated session database.
5. Read the rendered result, durable session, workflow events, citations, and
   trace in full.
6. Confirm that deterministic Web retrieval remains independently visible.
7. Exercise bounded failure cases for unavailable Ollama, execution timeout,
   concurrency rejection, and rate limiting.
8. Reopen the session database and prove the successful or honestly incomplete
   session survives process-local object disposal.
9. Record measured results and a launch decision here.

## Success Criteria

- The real Web route invokes the real AI orchestrator and current Core CLI.
- The result has a durable session ID and can be reopened from SQLite.
- Both retrieval branches and contradiction-recall work are represented in the
  session workflow or are explicitly recorded as failed.
- Every displayed citation resolves to a retrieved Evidence Record and source.
- Skeptic verification and the close gate are visible and not conflated with
  scientific peer review.
- The narrative does not claim certainty beyond the retrieved records and
  carries the existing AI-generated/not-reviewed boundary.
- Deterministic retrieval remains visible if optional AI work fails.
- Timeout and admission failures are bounded, sanitized, and honest.
- No request downloads sources, changes Core evidence, or writes to the Core
  corpus database.

## Failure Criteria

- A traceback, private path, prompt, or extracted full text reaches visitor
  output.
- The UI presents an incomplete workflow as a complete scientific answer.
- A missing citation or qualifier is silently invented.
- A timeout returns while unbounded subprocess or model work continues without
  being represented as a limitation.
- A failed AI request hides deterministic retrieval.
- Session persistence or reopening fails.

Any failure is investigated as an integration defect. Only defects within the
AI-O17 path are fixed in this milestone.

## Launch Decision Contract

AI-O17 may establish local integration readiness. It cannot establish hosted
Research Copilot readiness because the Render deployment still lacks an
operator-provisioned persistent disk, a reachable Core runtime with corpus
inputs, and secured hosted inference.

The final result will therefore make two separate decisions:

1. whether the composed workflow is verified locally; and
2. whether the public deployment remains retrieval-only.

## Non-Goals

- Persistent Core HTTP hosting.
- Hosted inference provisioning.
- Render disk purchasing or configuration.
- New retrieval, graph, evidence, scoring, or synthesis algorithms.
- New agents, autonomous research behavior, or scientific conclusions.
- Broad cross-domain retrieval certification.

## Handoff

After a passing local rehearsal, the next scientific quality milestone is a
cross-domain golden-question benchmark covering GLP-1, oncology, and mental
health. Public Research Copilot remains a separate operator decision governed
by the deployment prerequisites above.

## Measured Rehearsal

The rehearsal used current source checkouts, the verified reassembly of Core's
committed 1,357-paper corpus database, the GLP-1 source and Evidence Record
files, the real Core `ke` executable, Web's actual HTTP `/ask` route, a dedicated
local Research Session database, and Ollama `llama3.1:8b`. The canonical
question was not changed between runs.

The successful final request completed in **84.140 seconds** and created
Research Session `4852169a-b21e-45eb-87c8-0a5c8dbfd644`.

Durable read-back showed:

- primary retrieval and Evidence Intelligence: succeeded, 10.125 seconds;
- contradiction-oriented retrieval: succeeded in the same parallel window;
- synthesis: succeeded, 71.250 seconds;
- Research ISA close gate: passed;
- citation-integrity criterion: passed;
- contradiction-review criterion: passed;
- workflow-integrity criterion: passed;
- final durable session status: `completed`.

The primary branch retrieved and the narrative cited five GLP-1 Evidence
Records: Gao body-weight efficacy, Gao safety/discontinuation, SELECT long-term
weight loss, STEP 5 week-104 weight loss, and the PMOS single-arm study. The
narrative reported efficacy while also stating adverse-event/discontinuation,
population, comparator, and study-design qualifications. Web independently
rendered five deterministic paper matches below the optional narrative.

This verification is structural and source-linked, not semantic peer review.
The deterministic verifier confirms citation identities, numeric grounding,
qualifying-record inclusion, and workflow completion. It does not prove that
every sentence has ideal emphasis or clinical interpretation. A person read
the complete final output against the five stored Evidence Records as part of
this rehearsal; no unsupported number, citation, or unlabelled certainty claim
was found.

## Defects Found And Corrected

### Qualifier context was absent from the synthesis prompt

The first run completed in 69.813 seconds but the close gate blocked because
the model omitted two qualifying records. `synthesis.py` had not supplied each
record's `evidence_direction` or `limitations`, even though the independent
verifier required qualifying or limited records to be cited. The prompt now
contains those existing fields and explicitly requires qualification
boundaries before an overall conclusion.

### Blocked drafts were still rendered

The first blocked narrative was still visible in Web. AI now exposes a
`narrative_releaseable` contract, and both the AI CLI and Web withhold a draft
unless deterministic verification is clean and the Research ISA close gate is
complete. The draft remains in durable session state for audit.

### Verifier and workflow-completion contracts were inconsistent

The second run completed in 97.912 seconds and was correctly withheld. It
showed that the prompt permitted Evidence Quality and Claim Confidence values
that numeric verification did not recognize, and its 400-token output ended
before every required record was addressed. Verification now accepts only the
exact deterministic score fields supplied by the prompt, including their fixed
`/100` scale, while unrelated numbers still fail. The bounded synthesis output
budget is 600 tokens.

A forced 0.1-second execution budget then exposed a separate lifecycle defect:
both retrieval branches failed but the no-narrative close path marked the
session complete. Every Research ISA now includes a fixed
`workflow_integrity` criterion. Repeating the drill returned in 4.712 seconds,
persisted session `1833531d-6288-46dc-9586-5c1f7c37bcfd`, reported both failed
steps, left deterministic Web retrieval visible, and correctly kept the close
gate `blocked`.

## Failure Drills

- **Ollama unavailable:** returned in 15.125 seconds with a durable session,
  sanitized no-narrative message, and all five deterministic Web retrieval
  results. No traceback or private path appeared. Retrieval itself succeeded,
  so the existing contract records model unavailability as a failed synthesis
  event rather than a failed deterministic workflow.
- **Execution timeout:** returned in 4.712 seconds with an explicit execution
  limit notice, two failed retrieval steps, a blocked close gate, a durable
  session ID, and deterministic Web retrieval still visible.
- **Concurrency and rate limits:** exercised by deterministic Web tests rather
  than spending additional real model runs. They cover concurrent rejection,
  per-client rate exhaustion and expiry, independent clients, and slot release
  after failure.
- **Persistence:** the successful session and each failure session were reopened
  from a new SQLite connection. Event ordering, criteria, source IDs, durations,
  and final status matched the rendered result.

## Integrity Checks

- The reassembled Core database matched the committed manifest SHA-256 before
  the rehearsal and remained unchanged afterward.
- No PDF was opened by Web or AI, and no source was downloaded.
- Core corpus, Evidence Record, relationship, and source files were not changed.
- Research Session writes went only to dedicated, untracked rehearsal databases.
- Visitor output contained no private absolute paths, prompts, tracebacks, or
  extracted full paper text.

## Launch Decision

**Local composed-workflow readiness: verified.** One real question successfully
crossed Web, AI, Core, Ollama, deterministic verification, the Research ISA
close gate, durable persistence, and rendered citations.

**Hosted Research Copilot readiness: not verified and not enabled.** The Render
alpha must remain retrieval-only until an operator provisions and verifies a
persistent session disk, a reachable Core runtime and corpus inputs, and a
secured hosted inference service. A laptop Ollama endpoint is not a durable
public deployment dependency.
