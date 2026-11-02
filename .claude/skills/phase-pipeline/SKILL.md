---
name: phase-pipeline
description: Run one phase of the cli_interface improvement plan through the user's multi-agent pipeline (plan → execute → review → test → integrate → document). Use when the user says "run phase N", "start phase N", "next phase", or asks to implement a phase from the action plan.
---

# Phase pipeline

## The user's process (verbatim; this is the spec)

> How I want this to progress. For each phase:
> 1) Allocate agent to decide on code implementation.
> 2) This agent is to send structure to agents for execution.
> 3) These agents will report back their changes to a reviewer agent, collating the changes as a whole. With a holistic view of the phase this agent should strictly review, and send back any identified issues/changes to their initial agent to fix.
> 4) Once the review agent is satisfied, they will forward it to an agent to design and develop a suite of tests. Failing tests should be sent back to the reviewer agent to allocate back
> 5) Once all tests are passing the next step will be a final integration agent, dedicated to a final review of the code into the whole codebase. If there are missing functions or additional improvements, repeat from step 1 with a new review plan until satisfied.
> 6) Final step is to provide adequate documentation. Comments and docs should be minimal to this point, so that the entire final scope is captured here.

Everything below is how the orchestrator (the main session) carries that out.

## Inputs

- [phases.md](phases.md): the review findings (W*, F*) and the phase tables. This defines each phase's scope.
- [probes/](probes/): reproduction scripts from the review. Turn them into regression tests, especially in Phase 0.
- Ledger at `.claude/pipeline/phase-<N>.md`. Create it at the start of the phase and update it after every handoff. Resume from it after compaction or in a new session.

## Before starting a phase

1. Confirm the following with the user:
   - The phase number.
   - Whether `whiteboard.py` is in scope. It is the user's untracked file, so never edit it without a yes for this phase. If it is in scope, first copy it to `.claude/pipeline/whiteboard.py.bak`.
   - Which branch to start from: the previous phase's branch, or `main` after merging.
2. Record a baseline: create the branch `phase-<N>` and record the baseline SHA in the ledger. The reviewer and the integrator diff against this SHA.
   - The user gave standing approval for a local checkpoint commit at the end of each phase on 2026-10-31.
   - Never push.
   - Leave unrelated edits by the user unstaged. For example, their `.gitignore` change was left out of the Phase 0 commit.
3. Load `SendMessage` with ToolSearch (`select:SendMessage`). It is deferred.

## Roles

| Step | Role | subagent_type | model | May edit |
|---|---|---|---|---|
| 1 | Planner | Plan | sonnet | nothing |
| 2 | Executor (one per work package) | general-purpose | sonnet | only its owned files |
| 3 | Reviewer | Plan | sonnet | nothing |
| 4 | Tester | general-purpose | sonnet | `tests/` and test config in `pyproject.toml` |
| 5 | Integrator | Plan | sonnet | nothing |
| 6 | Documenter | general-purpose | sonnet | docstrings, comments, README, docs, CHANGELOG |

- Always pass `model` explicitly, because subagent cost matters to this user. To move a role to opus, edit this table.
- `Plan` agents have no Edit or Write tools, which enforces read-only review mechanically.

## Message flow

Subagents cannot spawn agents or message each other, so the orchestrator is the message bus:
- Forward each agent's output verbatim to the next role.
- Return issues with `SendMessage` to the agent that wrote the code, so it keeps its context.
- Record every agent ID in the ledger.
- **Save every handback to a file** and pass the file path on, rather than pasting the report into the next prompt. Run:

  ```
  python3 .claude/skills/phase-pipeline/extract_handback.py <agent output_file> .claude/pipeline/phase-<N>-<step>.md
  ```

  The report arrives as a SubagentHandback tool call, so the script pulls it from the agent's transcript. Never read that transcript directly; it is large.
- **Reuse agents in fix and gap rounds.** Send the work by `SendMessage` to the agent that owns the files, whether executor, tester or integrator, because it already has the context. Spawn a new agent only for new files or a new role.
- **Resume after a rate limit.** If an agent stops on a rate limit, resume it with `SendMessage` after the reset. Don't respawn it.

### Step 1: Plan

**Spawn the Planner with:**
- this phase's section of phases.md and the findings it cites;
- the relevant source files;
- on a re-plan, only the integrator's gap list.

**It must return:**
- Design decisions, briefly, including the signatures of any interfaces that cross work packages.
- Work packages WP-1…n. Each package lists:
  - its goal;
  - the files it owns (no file may appear in two packages);
  - the contracts it provides and consumes;
  - its acceptance criteria;
  - the finding IDs it covers.
- Test notes for step 4: what must be proven, and which probes apply.

Check that file ownership is disjoint before step 2. If it isn't, send the plan back.

### Step 2: Execute

**Spawn executors in waves.**
- **First wave:** every package that consumes no other package's new code. Spawn them all in one message.
- **Later waves:** packages that depend on an earlier wave.

Parallel executors that code against contracts which aren't in the tree yet hit transient import failures (Phase 0 risk R3). Each prompt points to the plan file and names the executor's own work package.

**Rules for executors:**
- Edit owned files only. If a change is needed elsewhere, stop and report it.
- Keep comments and docstrings minimal; step 6 writes the docs.
- Don't commit.
- Smoke-check the work: import the package and run the relevant probe.

**Each executor reports:**
- the files it changed;
- each change, mapped to a finding ID;
- any deviations from the plan;
- any requests for changes in other packages' files;
- anything it couldn't verify.

### Step 3: Review (loop)

**Spawn the Reviewer with:**
- the plan;
- all executor reports;
- an instruction to read the real diff (`git diff <baseline>` plus new files from `git status --porcelain`), not just the reports.

**The review is strict and covers:**
- correctness and thread safety;
- conformance to the plan and to the contracts between packages;
- regressions;
- scope creep;
- the cross-package requests from step 2. The reviewer assigns each one to an owner.

**Output:** `APPROVED`, or `CHANGES_REQUESTED` with issues. Each issue is tagged `[WP-k]` and gives a severity, `file:line` and the fix required.

**Then:**
1. Send each work package's issues to its executor via SendMessage.
2. Forward the executors' fix reports to the same reviewer via SendMessage.
3. Repeat until the reviewer returns `APPROVED`.

### Step 4: Test (loop)

**On APPROVED, spawn the Tester with:**
- the plan's acceptance criteria and test notes;
- the reviewer's final summary;
- the relevant `probes/` paths.

**The Tester:**
- Builds a pytest suite under `tests/`. UI tests use Textual's `run_test()` with Pilot.
- Adds a dev dependency group with pytest and pytest-asyncio if it's missing.
- Runs `uv run pytest`.
- Writes tests that assert the behaviour in the acceptance criteria, not the implementation.
- Keeps comments minimal.

**On failures:**
1. Send the failures to the Reviewer via SendMessage. The Reviewer classifies each one as a code bug `[WP-k]` or a test bug.
2. Route code bugs to the original executor and test bugs to the Tester.
3. The Reviewer checks the fix diff, then the Tester reruns the full suite.
4. Repeat until all tests pass.

### Step 5: Integrate

**Spawn a fresh Integrator,** not the Reviewer. Give it the phase scope, the plan and the final test report.

**It reviews the whole codebase, not only the diff:**
- coherence of the public API;
- dead or duplicated code;
- every finding ID in scope is actually addressed;
- the full suite passes;
- `import cli_interface` works;
- the demo runs under `run_test()`;
- `uv build` works, if packaging changed.

**Output:** `INTEGRATED`, or `GAPS`: a list of missing functions or improvements, each with its rationale.

**On GAPS:** spawn a new Planner scoped to the gap list only, then rerun steps 2–5. The original executors, tester, reviewer and integrator take the work via `SendMessage`, as described under Message flow.

### Step 6: Document

**Spawn the Documenter with** the final diff against the baseline, the plan and the integrator's verdict.

**It writes:**
- docstrings for the public API the phase touched;
- README and docs updates;
- a `CHANGELOG.md` entry under the phase heading;
- comments, only where the logic isn't obvious.

It must not change behaviour, and must rerun the tests when finished.

### Close

1. Run the full suite once more.
2. Update the ledger.
3. Make the local checkpoint commit (standing approval). Stage only the phase's files, and end the message with the attribution trailer.
4. Add the integrator's carry-forward items to `phases.md` under the phases they target.
5. Report to the user:
   - the changes, by finding ID;
   - test counts;
   - deviations;
   - open items;
   - what comes next.

Do not start the next phase until the user says so.

## Limits (orchestrator's addition; the user may change these)

| Loop | Limit |
|---|---|
| Review (step 3) | 3 rounds |
| Test and fix (step 4) | 3 rounds |
| Integration re-plans (step 5) | 2 extra rounds |

When a limit is reached, stop and escalate to the user with the outstanding items. Also escalate when:
- an executor needs a change of scope, or
- the reviewer and an executor still disagree after 2 exchanges.

## Ledger template

```markdown
# Phase N ledger
baseline: <sha or patch path>   branch: phase-N   whiteboard in scope: yes/no
round: plan#1 / review#0 / test#0

| role | agent id | owns | status |
|---|---|---|---|

## Log
- step → verdict / one-line summary
```
