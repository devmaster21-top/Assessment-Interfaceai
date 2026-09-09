# Computer-Use Automation System

A focused end-to-end implementation for the interface.ai take-home assignment.

An LLM discovers a workflow against a real UI once. The successful discovery run is materialized as a typed, versioned capability artifact. Subsequent invocations replay that artifact deterministically with no model in the decision loop.

## What is implemented

- LLM-driven **observe -> decide -> act** discovery loop.
- Real browser interaction through a Playwright surface adapter.
- Typed Pydantic capability artifact with:
  - typed inputs and outputs,
  - ordered actions,
  - robust locator fallbacks,
  - success checkpoint,
  - runtime outcome rules,
  - schema and capability versioning.
- Deterministic replay that does **not** call an LLM.
- Locator fallback order based on user-facing semantics before coordinates.
- Explicit host and action allowlists.
- Risk classification and human escalation for unsafe actions.
- Structured JSONL evidence logs plus step, recovery, and failure screenshots.
- Bounded retry for transient replay failures.
- Explicit distinction between:
  - expected business outcome: `member_not_found`,
  - recoverable condition: `session_expired`,
  - hard failure: `permission_denied`.
- Minimal but real human handoff: automation pauses while the same headed browser context remains open, a human takes control, records a short intervention note, and automation resumes in that same session.
- A local server-rendered "legacy credit union" proxy application with:
  - multi-page navigation,
  - nested tables,
  - no test IDs,
  - runtime error states,
  - a recoverable session-expiration scenario,
  - and a risky `Suspend Account` control that policy will not execute autonomously.

## Repository layout

```text
.
|-- README.md
|-- REPORT.md
|-- pyproject.toml
|-- demo_app/
|   `-- app.py
|-- src/cuagent/
|   |-- __init__.py
|   |-- cli.py
|   |-- discovery.py
|   |-- evidence.py
|   |-- handoff.py
|   |-- models.py
|   |-- policy.py
|   |-- recorder.py
|   |-- redaction.py
|   |-- replay.py
|   |-- target_profile.py
|   |-- llm/
|   |   `-- gemini_planner.py
|   `-- surface/
|       |-- base.py
|       `-- playwright_surface.py
|-- tests/
`-- evidence/
    |-- artifacts/
    |-- interventions/
    |-- logs/
    `-- screenshots/
```

## Setup

Python 3.11+ is recommended.

Create a virtual environment:

```bash
python -m venv .venv
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Install the project and development dependencies:

```bash
pip install -e ".[dev]"
```

Install the Playwright Chromium runtime:

```bash
playwright install chromium
```

Create local environment configuration.

macOS/Linux:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Configure Gemini in `.env`:

```text
GEMINI_API_KEY=your_api_key_here
GEMINI_MODEL=gemini-3.5-flash-lite
```

`GEMINI_MODEL` is configurable. Model access is used only during discovery. Deterministic replay does not instantiate or call an LLM.

The `.env` file is ignored by Git and must not be committed.

## Run the target application

Start the local legacy-app proxy in Terminal 1:

```bash
uvicorn demo_app.app:app --host 127.0.0.1 --port 8000
```

The application is available at:

```text
http://127.0.0.1:8000/
```

The target is intentionally small and deterministic so the important computer-use behavior can be demonstrated without real credentials or PII.

### Known demo members

| Member ID | Behavior |
|---|---|
| `12345` | success, savings balance `$4,218.37` |
| `67890` | success, savings balance `$925.04` |
| any unknown ID | expected `member_not_found` business outcome |
| `40300` | hard `permission_denied` condition |
| `00000` | one-time `session_expired`, human re-authentication, then savings balance `$1,234.56` |

No real credentials or PII are used.

# Demo

## 1. Genuine LLM discovery

In Terminal 2:

```bash
cuagent discover \
  --goal "Look up member 12345 and read their current savings balance" \
  --target http://127.0.0.1:8000/ \
  --param member_id=12345 \
  --artifact evidence/artifacts/lookup_member_savings.v1.json \
  --headed
```

During discovery, Gemini receives a compact observation of the current UI and chooses one constrained action at a time.

The browser adapter performs the selected action, while the recorder converts successful actions into the reusable capability representation.

The successful discovery path is:

```text
Home
  -> Member Servicing
  -> type member_id
  -> Search Member
  -> Member Detail
  -> Open Savings Account
  -> extract Savings Balance
  -> verify success checkpoint
```

The successful discovery used member `12345` and extracted:

```text
$4,218.37
```

The generated artifact is parameterized by `member_id`; the literal discovery value is not baked into the type action.

Discovery produces:

```text
evidence/artifacts/lookup_member_savings.v1.json
evidence/logs/discovery-<run_id>.jsonl
evidence/screenshots/<run_id>/...
```

The raw model conversation is not the replay artifact. Replay operates only from the clean capability representation.

## 2. Deterministic replay with no LLM

Replay the discovered capability against a different member:

```bash
cuagent replay \
  --artifact evidence/artifacts/lookup_member_savings.v1.json \
  --param member_id=67890 \
  --headed
```

Expected output:

```json
{
  "status": "success",
  "outputs": {
    "savings_balance": "$925.04"
  },
  "business_outcome": null,
  "error": null
}
```

The replay runner does not instantiate or call the Gemini planner.

Using a different member from the discovery run demonstrates that the capability is parameterized and reusable rather than tied to member `12345`.

## 3. Expected business outcome

Run:

```bash
cuagent replay \
  --artifact evidence/artifacts/lookup_member_savings.v1.json \
  --param member_id=99999 \
  --headed
```

Expected result:

```json
{
  "status": "business_outcome",
  "outputs": {},
  "business_outcome": "member_not_found",
  "error": null
}
```

`member_not_found` is deliberately modeled as an expected caller-visible business result rather than an automation crash.

## 4. Hard failure

Run:

```bash
cuagent replay \
  --artifact evidence/artifacts/lookup_member_savings.v1.json \
  --param member_id=40300 \
  --headed
```

The application displays a permission-denied state.

Replay classifies this as a non-recoverable hard failure:

```text
permission_denied
```

The result contains structured error information including the current step and `recoverable: false`.

## 5. Recoverable condition and human handoff

Run in headed mode:

```bash
cuagent replay \
  --artifact evidence/artifacts/lookup_member_savings.v1.json \
  --param member_id=00000 \
  --headed
```

Member `00000` simulates an application session that expires during execution.

Replay detects the declared `session_expired` condition before continuing the next deterministic step and transfers control to a human:

```text
=== HUMAN CONTROL REQUESTED ===
The application session expired; a human may re-authenticate in the same session.
```

The Playwright browser and context remain open.

The operator clicks `Re-authenticate Session` in that same live browser. After re-authentication, the operator records a short intervention note and returns control to automation.

Replay then resumes the stored deterministic capability:

```text
human re-authentication
  -> step_04: Open Savings Account
  -> step_05: extract Savings Balance
  -> success checkpoint
```

The validated recovery run completed with:

```json
{
  "status": "success",
  "outputs": {
    "savings_balance": "$1,234.56"
  },
  "business_outcome": null,
  "error": null
}
```

For noninteractive execution, pass:

```text
--noninteractive
```

A condition requiring human intervention then produces an escalation rather than waiting for terminal input.

# Artifact contract

A capability artifact is intentionally separate from the LLM transcript.

Its important fields are:

```text
schema_version
capability_id
capability_version
target_app
entry_point
allowed_hosts

typed inputs
typed outputs

ordered steps
  action kind
  target
  ordered locator candidates
  parameter/literal value source
  output name
  risk class

business outcome rules
recoverable condition rules
hard failure rules

success checkpoint
metadata
```

The generated savings capability accepts:

```text
member_id: string
```

and returns:

```text
savings_balance: string
```

The final capability is generic even though discovery used member `12345`.

The recorded type action references:

```text
member_id
```

rather than storing `12345` as a literal.

## Locator strategy

Targets contain ordered locator candidates rather than one brittle selector.

The preferred order is:

```text
label
  -> role + accessible name
  -> stable name/aria CSS attribute
  -> visible text
  -> coordinates
```

Coordinates are retained only as a last-resort locator.

Replay records which strategy actually resolved each step.

For text extraction, coordinate-only fallback is intentionally rejected. A pixel location alone is not sufficient evidence that the expected textual value is still present at that location. The system prefers an explicit failure or human escalation over silently extracting the wrong screen region.

# Determinism

The discovery and replay paths are deliberately separated.

Discovery:

```text
UI observation
  -> Gemini decision
  -> constrained action
  -> recorder
  -> capability artifact
```

Replay:

```text
capability artifact + invocation parameters
  -> deterministic ReplayRunner
  -> Surface
  -> structured result
```

There is no planner dependency in `ReplayRunner`.

Replay therefore does not ask an LLM what to do next, reinterpret the goal, or regenerate the workflow.

Runtime variability is handled through explicit capability rules, bounded retry, checkpoints, and human escalation rather than by placing the model back into the replay loop.

# Runtime outcome model

The capability explicitly separates three important runtime classes.

### Business outcome

```text
member_not_found
```

This is a legitimate result of the requested operation.

### Recoverable condition

```text
session_expired
```

This can transfer control to a human and continue in the same browser session after recovery.

### Hard failure

```text
permission_denied
```

This is non-recoverable for the current invocation and produces a structured failure.

# Safety model

Safety is enforced in code rather than relying only on the discovery prompt.

The vertical slice includes:

- explicit host allowlist,
- explicit action-type allowlist,
- password-field typing block,
- risky-control classification,
- human execution/approval for risky steps,
- no autonomous destructive or money-moving actions,
- API secrets kept outside capability artifacts,
- structured redaction of secret-like evidence fields.

The savings page deliberately exposes:

```text
Suspend Account
```

The control is present so the safety boundary is visible and testable. It is not part of the generated lookup capability and should never be autonomously executed by the automation.

# Evidence and observability

Each run produces structured JSONL evidence.

Events can include:

```text
observation
llm_decision
action_start
action_end
output_extracted
artifact_saved
replay_started
step_start
step_success
business_outcome
hard_failure_condition
recoverable_condition
human_handoff_started
human_handoff_resumed
replay_success
step_failure
```

Screenshots are stored for discovery observations, replay steps, recoverable states, and failures.

Human intervention evidence records:

- run ID,
- intervention ID,
- current step,
- reason,
- screenshot,
- state summary,
- control owner,
- operator action note.

## Validated evidence

The repository includes evidence from these completed runs:

| Run ID | Type | Input | Result |
|---|---|---|---|
| `118b9e6f` | LLM discovery | `12345` | `savings_balance = $4,218.37` |
| `52baed23` | deterministic replay | `67890` | `savings_balance = $925.04` |
| `fa6eb14c` | deterministic replay | `99999` | `member_not_found` |
| `9ed156cc` | deterministic replay | `40300` | hard `permission_denied` |
| `ca0f1695` | deterministic replay + human handoff | `00000` | re-authenticated in same browser session, then `savings_balance = $1,234.56` |

The discovery log demonstrates the LLM-driven observe/decide/act path.

The replay evidence demonstrates that the resulting artifact executes without an LLM in the decision loop.

# Tests

Run:

```bash
pytest
```

The current suite contains seven passing tests covering:

- artifact serialization,
- safety-policy behavior,
- host/action enforcement,
- risky-action classification,
- password-field protection,
- replay/error behavior,
- target profile behavior.

Validated locally:

```text
7 passed
```

# Current deliberate cuts

This repository is a vertical slice, not a production computer-use platform.

It intentionally does not implement:

- distributed worker queues,
- tenant-management infrastructure,
- durable remote session brokering,
- a polished operator dashboard,
- desktop automation,
- screenshot/vision-only perception,
- capability approval infrastructure.

The implementation instead focuses on the core through-line:

```text
LLM discovery
  -> typed reusable artifact
  -> deterministic replay
  -> structured outcomes
  -> safety enforcement
  -> real human handoff
  -> evidence
```

The extension seams for heterogeneous surfaces, multi-tenant operation, capability lifecycle, and production human control are described in `REPORT.md`.