---
doc: checklist
status: approved
---

# Build Checklist

Build mode: learn mode (TDD: write test first for every slice; full accuracy evaluation)

## Slices

- [x] **1. Core Reflex Gate (In-process evaluation on staged diffs)**
  Becomes usable: Running `python -m latch.cli check` on staged git changes inspects added lines in-process using local Julia-1, allowing clean code with exit code `0` or blocking leaks with exit code `1` and a clear terminal warning banner.
  Why now: Delivers the unique kernel end-to-end on the first slice — scaffolding, diff extraction, Julia-1 Noul evaluation, and terminal presentation — so every subsequent slice builds on a working foundation.
  PRD ref: `prd.md > The Core Journey` (steps 1-3, 5), `prd.md > Features and Behavior > 1. Pre-Commit Interception`
  Spec ref: `spec.md > Components > 1. CLI & Hook Orchestrator`, `spec.md > Components > 4. Diff Parser`, `spec.md > Components > 6. Julia-1 Decision Engine`, `spec.md > Components > 7. Terminal Presenter`
  Build: Scaffold repository file structure, add `config.json` with configuration schema, implement `diff_parser.py` (extracts `git diff --staged` additions, ignores deletions/binaries), `engine.py` (Julia-1 Noul inference with fail-closed error handling), `presenter.py` (clean vs blocked terminal banners), and `cli.py` (`latch check`).
  Verify (mechanical): Run unit tests confirming added lines are extracted from git diff; run `latch check` against a staged clean file (confirm exit code 0) and a staged file containing PII (confirm exit code 1 with blocked banner).
  Learner check: Stage a clean file and run `python -m latch.cli check`, then stage a file with a fake phone number and run it again to observe the terminal block.
  Commit: `Add core reflex gate with in-process Julia-1 evaluation`

- [x] **2. Binary Dissection and Localization Window**
  Becomes usable: When a commit is blocked, Latch automatically bisects the offending batch down to the specific file and a pinpointed context window ($\le 25$ lines) with line numbers displayed in the alert, rather than rejecting the whole commit vaguely. Also proves conservative fallback on split boundaries.
  Why now: Pinpointed localization is essential for developer usability on multi-file commits and addresses the spec's key uncertainty (handling multi-line PII split across boundaries).
  PRD ref: `prd.md > The Core Journey` (step 4), `prd.md > Features and Behavior > 2. Adaptive Batching & Binary Dissection`
  Spec ref: `spec.md > Components > 4. Diff Parser & Batch Slicer`, `spec.md > Look and Feel > High-Contrast on Blocked`, `spec.md > Decisions and Open Issues > One Useful Unknown`
  Build: Implement `bisect_buffer()` in `diff_parser.py`, binary dissection recursion in `client.py` with `max_dissection_depth` and conservative fallback (returning parent window if both halves test clean), and update `presenter.py` to format context snippets ($\le 25$ lines) with line numbering. Add unit tests for batch slicing and boundary handling.
  Verify (mechanical): Run unit test asserting binary dissection isolates a known PII line within a 100-line multi-file mock diff to a window $\le 25$ lines; verify conservative fallback activates on midpoint-split fixture.
  Learner check: Stage a multi-file diff containing one sensitive line among clean files, run `latch check`, and verify the terminal pinpoint banner flags the exact file and lines 42-56.
  Commit: `Implement adaptive batching and binary dissection localization`

- [x] **3. Sub-50ms Warm IPC Daemon and Two-Tier Fallback**
  Becomes usable: Developers can run `python -m latch.cli daemon start` to keep Julia-1 loaded warm in memory. `latch check` automatically probes `127.0.0.1:5138` and verifies clean commits in under 50ms, while seamlessly falling back to in-process cold-start if the daemon is stopped.
  Why now: Solves the developer flow latency challenge (sub-50ms warm execution on standard CPU) while ensuring reliability through the automatic cold-start fallback.
  PRD ref: `prd.md > Technical & Engine Strategies > Julia-1 Engine Interface Contract`, `prd.md > Why We Win`
  Spec ref: `spec.md > Components > 2. Fast Client & Fallback Handshake`, `spec.md > Components > 3. Local Warm Daemon`, `spec.md > Data Model > 2. IPC Request & Response Payloads`
  Build: Implement `daemon.py` using `http.server.ThreadingHTTPServer` (endpoints `/v1/health`, `/v1/evaluate`, `/v1/shutdown`, PID file management), add 50ms socket probe and fallback logic in `client.py`, add daemon commands to `cli.py` (`start`, `stop`, `status`), and create Windows PowerShell helper scripts in `scripts/windows/`.
  Verify (mechanical): Start daemon in background, test `/v1/health` returns status ready, run `latch check` through daemon and measure latency < 50ms; stop daemon and verify `latch check` falls back to in-process cold-start with identical evaluation result.
  Learner check: Start the daemon with `python -m latch.cli daemon start`, run a check to see the sub-50ms response, then stop the daemon and run the check again to see the cold-start fallback.
  Commit: `Add local HTTP daemon for warm sub-50ms evaluation and cold-start fallback`

- [ ] **4. One-Touch Git Hook Installation and Strict Fail-Closed Safeguard**
  Becomes usable: Running `python -m latch.cli install` automatically writes `.git/hooks/pre-commit` configured with the absolute virtualenv Python path, so that standard `git commit` commands trigger Latch directly. If model weights are missing or corrupt, Latch strictly aborts commits with exit code `1` and an actionable diagnostic banner.
  Why now: Completes the full developer loop (`git commit` intercepted at terminal) and verifies the critical non-negotiable architectural invariant: strict fail-closed behavior under all failure modes.
  PRD ref: `prd.md > Features and Behavior > 4. Strict Fail-Closed Error Enforcement`, `prd.md > Technical & Engine Strategies > Failure Modes & Fail-Closed Guarantees`
  Spec ref: `spec.md > Where It Runs and How Someone Tries It > Installation & Quick Start`, `spec.md > Important Failure Modes`, `spec.md > Components > 1. CLI & Hook Orchestrator`
  Build: Implement `latch install` in `cli.py` (writes `.git/hooks/pre-commit` with absolute interpreter path and executable permissions), add pre-flight checks in `diff_parser.py` (verifies git installed and `.git` exists), implement fail-closed error formatting in `presenter.py`, and create `tests/test_fail_closed.py`.
  Verify (mechanical): Run `latch install` and verify hook script is created and points to the correct virtualenv interpreter; run `tests/test_fail_closed.py` confirming simulated model missing or corrupt errors cause exit code 1 with explicit diagnostic output.
  Learner check: Run `python -m latch.cli install`, then run a real `git commit` on staged clean and PII files to experience the automated hook interception.
  Commit: `Add pre-commit hook installer and strict fail-closed enforcement`

- [ ] **5. Evaluation Benchmark and Prompt Injection Hardening Suite**
  Becomes usable: Running `python -m latch.cli benchmark` executes an automated test suite across clean, synthetic PII, and adversarial prompt-injection fixtures in `fixtures/`, outputting a benchmark report with Accuracy, False Negative Rate (FNR), False Positive Rate (FPR), Injection Resilience, and latency metrics with hardware baseline.
  Why now: Validates the model's decision quality, confirms injection resilience, and provides the quantitative metrics required for project verification and documentation.
  PRD ref: `prd.md > Features and Behavior > 3. Prompt Injection Defense & Data Isolation`, `prd.md > Features and Behavior > 5. Benchmark & Evaluation Suite`
  Spec ref: `spec.md > Components > 5. State Builder & Data Isolator`, `spec.md > Components > 9. Benchmark & Evaluation Suite`, `spec.md > File Structure > fixtures/`
  Build: Implement `prompt.py` (delimited payload wrapping and contrastive mock injection via `templates/noul_prompt.txt`), create benchmark test fixtures in `fixtures/clean_samples/`, `fixtures/pii_samples/`, and `fixtures/adversarial_samples/`, implement `tests/run_benchmark.py`, and wire `latch benchmark` command in `cli.py`.
  Verify (mechanical): Run `python -m latch.cli benchmark` and assert all fixtures are evaluated, FNR is 0% on benchmark PII samples, injection attempts are resisted, and performance summary table prints successfully.
  Learner check: Run `python -m latch.cli benchmark` and inspect the terminal report showing accuracy, false positive/negative rates, and injection resilience scores.
  Commit: `Add evaluation benchmark suite and prompt injection hardening`

## Hands-on Checkpoints

- [ ] Early usable behavior explored — after Slice 1 (in-process diff checking verified on clean and PII commits)
- [ ] Final kick-the-tires exploration and feedback completed — after Slice 5 (full git hook and benchmark workflow)

## Final Review

- [ ] Final review complete — feedback resolved and learner confirms ready to ship

## Code Tour and App Map

- [ ] Learning activity complete — guided route, focused alternative, prior practice connected, or brief recap
- [ ] Optional edit and transfer reflection addressed — offered/declined/already covered/not applicable as appropriate
- [ ] `devpost/app-map.html` generated from finished code, checked, and shown, including a project-grounded practice to reuse

Activity and evidence: [what actually happened; real document/test/code references; unfinished work if interrupted]
Route and stops: [actual paths and symbols; guided stops completed, or reference-only route]
Edit outcome: [tried/kept/reverted/declined/not applicable; verification if changed]
Reflection: [offered/answered/declined/already covered — personal answer belongs only in the ignored profile]
Activity mode: [live app and editor, explicit static fallback, focused alternative, prior practice, or recap]

## Revisions

