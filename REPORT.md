# 1. Architecture

The system has one core separation: **discovery chooses; replay executes**.

The discovery path is allowed to use an LLM to interpret the current UI and choose the next constrained computer-use action. A recorder converts the successful actions into a clean capability artifact. The replay path accepts that artifact plus invocation parameters and executes it deterministically without asking an LLM what to do next.

This separation is enforced in code. `ReplayRunner` has no planner dependency. It receives a capability artifact, invocation parameters, a `Surface`, a safety policy, and evidence infrastructure. `GeminiPlanner` exists only on the discovery path.

The implementation is intentionally a single-process vertical slice with clear internal boundaries rather than separate production services.

The main responsibilities are:

- `Surface`: perception and actuation against a target UI.
- `GeminiPlanner`: discovery-only model decisions.
- `ArtifactRecorder`: converts successful discovery actions into the capability representation.
- `SafetyPolicy`: validates hosts, action types, input safety, and risky controls.
- `ReplayRunner`: deterministic capability execution and runtime outcome classification.
- `HumanHandoff`: explicit transfer of control between automation and a human.
- `EvidenceLogger`: structured evidence across discovery, replay, failures, and interventions.

For the concrete target I use a small local server-rendered credit-union servicing application. It has multi-page navigation, nested tables, no test IDs, validation/runtime outcomes, a recoverable session-expiration path, and a risky control.

Using a local proxy gives repeatability and lets the implementation demonstrate business outcomes, permission failures, session recovery, and risky controls without automating a third-party system or using real credentials or PII.

Playwright is the first `Surface` implementation because it provides a real browser and a practical way to expose semantic controls, screenshots, accessibility information, and coordinates while still performing genuine UI actions.

The capability artifact does not depend on one raw Playwright selector. It stores abstract ordered locator candidates. This is the seam that allows a later accessibility-tree, screenshot/vision, or desktop automation adapter to satisfy the same capability contract.

I chose a synchronous run model around an asynchronous browser rather than introducing queues and distributed workers. The important problem in this take-home is the discovery/replay contract and control behavior, not distributed scheduling. A production deployment could put run requests behind a queue without replacing the capability schema or deterministic replay semantics.

# 2. Artifact schema

The artifact is a typed, versioned, reviewable capability rather than a model transcript or macro recording.

The top-level contract contains:

- schema version,
- capability ID and version,
- target application,
- entry point,
- allowed hosts,
- typed inputs,
- typed outputs,
- ordered steps,
- success checkpoint,
- business outcome rules,
- recoverable condition rules,
- hard failure rules,
- metadata.

Each step has a typed action such as:

```text
click
type
extract
wait
```

A step can also contain:

- target locator,
- parameter or literal value source,
- output name,
- risk class,
- optional wait information.

A value entered during discovery is parameterized when it originates from an invocation parameter.

For example, discovery used:

```text
member_id=12345
```

but the generated type step stores a reference to:

```text
member_id
```

rather than baking `12345` into the workflow.

The final artifact is therefore reusable even though the discovery run used a concrete member. This was validated by replaying the same artifact with member `67890`, which returned a different savings balance successfully.

Extracted values are declared as typed outputs. The calling agent can therefore know the response shape before invoking the capability.

For this capability the important contract is conceptually:

```text
input:
  member_id: string

output:
  savings_balance: string
```

A target is represented by an ordered set of locator candidates.

For the browser surface I prefer:

```text
label
  -> role/accessibility name
  -> stable name or aria attribute
  -> visible text
  -> coordinates
```

The recorder generates those candidates from the control actually used during successful discovery. Replay tries the candidates deterministically in order and logs which strategy succeeded.

Coordinates are retained as a final fallback rather than the primary replay strategy.

For text extraction, coordinate-only fallback is intentionally rejected. A pixel location by itself is not enough evidence that the expected textual value is still present there. The system prefers a visible failure or human escalation over silently extracting the wrong screen region.

The schema also separates three runtime classes:

```text
business_outcomes
recoverable_conditions
hard_failures
```

In the demo:

- `member_not_found` is a legitimate business result.
- `session_expired` is recoverable through human handoff.
- `permission_denied` is a hard failure.

This classification belongs to the capability/application contract. Replay does not ask an LLM to infer these conditions dynamically.

The raw model conversation is deliberately not the replay artifact. Model reasoning can be useful discovery evidence, but production replay should not depend on model prose, hidden state, or a provider-specific conversation transcript.

# 3. Determinism & error handling

Replay begins from the artifact's declared entry point.

It:

1. validates required inputs,
2. enforces the allowed host,
3. executes the recorded steps in order,
4. resolves each target from ordered locator candidates,
5. evaluates declared runtime conditions,
6. extracts declared outputs,
7. verifies the final success checkpoint.

No model object is created on this execution path.

The locator strategy that successfully resolves each step is written to evidence. This makes degradation observable. For example, a capability that normally resolves a control by label or accessibility name but begins falling back to coordinates can be identified before it becomes a complete failure.

Determinism does not mean assuming runtime errors cannot occur.

Before relevant steps, replay evaluates the capability's declared conditions.

An expected business outcome returns a structured result such as:

```text
status = business_outcome
business_outcome = member_not_found
```

A hard failure returns a structured failure containing an error code and execution context.

A recoverable condition follows its explicit recovery policy.

Transient execution failures receive one bounded wait/retry before escalation. This provides limited resilience to temporarily unavailable controls or slow UI state without introducing an unbounded retry loop.

If a step still cannot execute, replay captures failure evidence and can transfer control to a human. It does not silently guess a new workflow using an LLM.

After all steps, replay verifies the declared success checkpoint.

Completing the click/type sequence alone is not considered success. If the expected final state is not present, replay returns a structured `checkpoint_failed` result containing expected and observed state.

The final evidence set exercises each important runtime class:

- member `67890`: deterministic success, returning `$925.04`,
- member `99999`: expected `member_not_found` business outcome,
- member `40300`: non-recoverable `permission_denied`,
- member `00000`: `session_expired`, human re-authentication, then successful deterministic completion.

This distinction is important for callers. A member that does not exist is a legitimate answer to the requested operation; it should not be confused with a broken automation or authorization failure.

# 4. Heterogeneity & multi-tenant

The artifact describes **what control/action is required**, while a `Surface` describes **how that control is perceived and acted on**.

The current Playwright surface obtains browser-visible semantic information and can retain coordinates as a fallback.

A legacy-web adapter could instead source controls from an accessibility tree, frameset-specific extractor, or another browser integration.

A desktop adapter could source the same abstract control representation from Windows UI Automation, macOS Accessibility, or a screenshot/vision layer.

Replay would continue to consume the same typed actions and target-locator abstraction.

For screenshot-only surfaces, I would extend locator candidates with visual anchors, templates, or regions rather than making raw screen coordinates the primary capability representation. The surface adapter would resolve those abstract visual targets into current screen coordinates at execution time.

For multi-tenant reuse, I would separate a **vendor/base capability** from **tenant or application-version overrides**.

The base artifact would contain:

- parameterized values,
- semantic target intent,
- common workflow structure,
- output contract,
- runtime outcome taxonomy.

A tenant/version override could replace only the locator candidates or entry-point differences that vary for that institution.

Artifact identity could include:

```text
vendor product
capability
semantic version
```

while an application-instance profile could contain:

```text
tenant configuration
detected application version
surface-specific overrides
```

I would detect UI drift through replay telemetry such as:

- locator fallback rate,
- checkpoint failures,
- repeated retries,
- repeated human interventions.

For example, if a target normally resolves through accessibility name but begins consistently reaching coordinate fallback, that is an early warning before complete failure.

Stable variants could be promoted into explicit overrides instead of recording an entirely separate capability for every institution.

I intentionally did not build tenant databases, queues, or desktop adapters in this take-home. The capability models and `Surface` boundary are intended to allow those additions without replacing the core discovery/replay contract.

# 5. Escalation & handoff

The control model has an explicit owner: automation or human.

Discovery can escalate when it:

- becomes stuck in the same state,
- reaches its step limit,
- encounters a risky control,
- cannot determine a safe next action.

Replay can escalate when it:

- encounters a declared recoverable condition,
- encounters a risky step,
- cannot execute a deterministic step after bounded retry.

An intervention contains:

- run ID,
- intervention ID,
- current step,
- reason,
- screenshot,
- compact state summary,
- control owner.

The browser and browser context are not closed during an interactive handoff.

The human uses the exact same live browser session. When the operator completes the required intervention, the terminal records a short note describing the action. Control then returns to automation.

The successful `00000` replay demonstrates this end to end.

Replay detected:

```text
session_expired
```

before `step_04`.

It emitted a recoverable-condition event and a `human_handoff_started` event containing the current browser state and screenshot.

The Playwright browser remained open.

The operator used that same browser session to click:

```text
Re-authenticate Session
```

and then returned control with the note:

```text
Re-authenticated the expired session in the same browser session.
```

Replay recorded `human_handoff_resumed`, continued deterministic execution at `step_04`, opened the savings account, extracted the balance at `step_05`, verified the checkpoint, and completed successfully with:

```text
$1,234.56
```

This demonstrates:

```text
detect
  -> route
  -> preserve live session
  -> human control
  -> record intervention
  -> return control
  -> deterministic resume
```

The implementation also verifies that a recoverable condition has actually cleared after the intervention rather than blindly continuing from an invalid state.

This is intentionally a minimal operator interface.

In production I would expose the same session through a secured remote-browser or co-browsing channel and back control ownership with a lease so automation and a human cannot issue actions concurrently.

The resume operation would include authenticated operator identity and a structured disposition such as:

```text
completed_step
retry
abort
new_business_outcome
```

The take-home keeps the operator UI minimal while making the actual control-transfer mechanism real.

# 6. Safety

Safety is enforced before execution rather than being delegated entirely to the discovery prompt.

The policy has explicit host and action-type allowlists.

Navigation outside the allowed host is treated as a policy failure.

Typing into password fields is blocked.

Controls whose labels indicate destructive or money-moving behavior are classified as risky and are not autonomously executed.

The demo intentionally exposes:

```text
Suspend Account
```

on the savings page.

That control makes the safety boundary visible and testable. It is not part of the generated lookup capability and should never be executed autonomously by this workflow.

The discovery prompt also instructs the model not to select risky actions, but this is defense in depth. The enforcement boundary remains deterministic code.

Secrets remain in environment configuration and are not serialized into capability artifacts.

Evidence logging redacts secret-like fields.

Invocation values are represented in the artifact through parameter references when possible rather than copying the concrete discovery values into the workflow.

A production implementation would extend this with:

- field-level data classification,
- tenant-specific PII policies,
- encrypted evidence storage,
- evidence retention policies,
- screenshot region masking,
- external credential injection,
- signed and approved capabilities,
- stronger authorization around human takeover,
- auditable operator identity.

The allowlist is deliberately narrow in this implementation. This is not intended to be a general-purpose autonomous browser agent.

# 7. Cuts

I prioritized a thin but real path through every major required capability rather than production breadth.

I intentionally did not build:

- a worker queue,
- distributed scheduler,
- tenant-management service,
- durable remote-session broker,
- polished operator console,
- desktop automation adapter,
- visual-model fallback,
- capability approval service.

The current UI observation is browser-based, although the artifact/surface seam is designed to support other perception and actuation mechanisms.

The first production extension I would prioritize is a capability lifecycle such as:

```text
draft -> reviewed -> approved
```

combined with replay stability metrics and version management.

The second would be a real remote human-control channel with authenticated leases and structured intervention dispositions.

The third would be a second surface adapter, likely accessibility-tree or desktop automation, to validate that the artifact contract remains surface-neutral in practice.

The final repository includes evidence for:

- a genuine successful LLM discovery run,
- the generated reusable capability artifact,
- a deterministic replay against a different member,
- an expected business-outcome replay,
- a hard-failure replay,
- a recoverable human-handoff replay that resumes successfully.

Validated evidence includes:

```text
118b9e6f  discovery             12345  -> $4,218.37
52baed23  deterministic replay  67890  -> $925.04
fa6eb14c  business outcome      99999  -> member_not_found
9ed156cc  hard failure          40300  -> permission_denied
ca0f1695  human handoff         00000  -> re-authenticate -> $1,234.56
```

The final local test suite passes:

```text
7 passed
```

The result is intentionally smaller than a production platform, but the full required through-line is real:

```text
LLM discovery
  -> typed/versioned artifact
  -> deterministic replay without an LLM
  -> structured runtime outcomes
  -> safety enforcement
  -> human handoff in the same live session
  -> deterministic resume
  -> evidence
```