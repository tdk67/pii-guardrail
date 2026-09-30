---
doc: scope
status: approved
---

# Latch — Pre-Commit Guardrail

An ultra-fast, 100% local git pre-commit hook powered by Julia-1 that blocks leaked PII and credentials before code leaves the developer's laptop.

## The Unique Kernel
Zero-trust privacy combined with sub-second execution on standard CPUs. By evaluating staged diffs locally using Julia-1 (a lightweight 144M-parameter non-autoregressive decision model) instead of a cloud LLM or heavy GPU model, private source code and PII never leave the local environment, and commits are validated in milliseconds without perceptible latency or dedicated GPU hardware.

## Who It's For
A developer working on private or proprietary code who wants an automated safety net against accidentally committing credentials or PII, but refuses to send proprietary diffs to third-party cloud APIs and won't tolerate slow, multi-second git commit hooks.

## The Core Loop
1. Developer stages changes and runs `git commit`.
2. The pre-commit hook intercepts the commit and extracts staged additions via `git diff --staged`.
3. The hook passes the diff to a local Julia-1 instance to evaluate whether sensitive PII or credentials are present.
4. If clean: exit code `0` (commit proceeds instantly).
5. If flagged: exit code `1` (commit blocked, terminal displays a clear, readable explanation of why the commit was refused).
6. If an engine error occurs: fail-closed with exit code `1` and print an explicit diagnostic message (no silent bypass, no masked errors).

## Inspiration & Identity
- **Tone**: Fast, quiet, and uncompromising.
- **Terminal Feel**: Seamless and invisible during normal commits; crisp, human-readable terminal alerts when blocking commits or reporting engine errors.
- **Reference**: High-performance developer tooling (e.g. Husky / lint-staged) married to local AI decision engines.

## Why This Matters to the Learner
To gain practical experience integrating Julia-1, while practicing strict engineering rigor during the planning phase. Specifically, designing explicit fail-closed boundaries upfront so that runtime failures surface readable error messages and block commits, rather than relying on silent fallbacks or faked outputs that conceal bugs.

## What "Working" Looks Like
A crisp 60-second terminal demonstration:
1. **Clean Commit**: Staging a clean source file and running `git commit` succeeds instantaneously without friction.
2. **Blocked Commit**: Staging a file containing PII (e.g. names, phone numbers) or credentials and running `git commit` is immediately blocked with a readable terminal error explaining the refusal.
3. **Fail-Closed Verification**: Demonstrating that engine/runtime failures produce an explicit diagnostic error message and block the commit instead of silently letting it through.

## The POC Boundary
- **In Scope (Now)**:
  - Git pre-commit hook script intercepting staged code.
  - Diff extraction focusing on added lines (`git diff --staged`).
  - 100% local Julia-1 evaluation for PII and sensitive credentials.
  - Terminal output formatting with clear human-readable error messages.
  - Strict fail-closed error handling (engine failures abort the commit with readable diagnostics).
  - Test fixtures with sample clean and PII-laden files.

## Later
- Customizable PII category tagging (e.g. phone vs. secret vs. network IP).
- Configurable rules file (e.g., repository-level severity thresholds).
- Interactive CLI bypass mechanism (`git commit --no-verify` or explicit override prompts).
- Retrospective whole-repo history scanning.

## Explicitly Cut
- **Jev / Cloud LLM APIs**: Cut entirely. Cloud services violate the core zero-trust privacy requirement and introduce unacceptable network latency.
- **GUI / Desktop Dashboard**: Cut. This is a headless developer CLI/hook tool.
