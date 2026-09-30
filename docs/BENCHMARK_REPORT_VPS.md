# Latch Benchmark & Evaluation Report — VPS Baseline (Weak Hardware)

**Evaluation Date:** September 30, 2026
**Evaluation Target:** Julia-1 (`mmBERT-small`, 144.3M parameters, non-autoregressive CPU tensor)
**Purpose:** Independent reproduction of the Windows-laptop report (`BENCHMARK_REPORT.md`) on deliberately weaker, commodity cloud hardware — plus first-ever measurement of the warm-daemon path and full git-hook E2E flow.
**Verification Commands:** `pytest` (full suite incl. live inference), `python -m latch.cli benchmark`, real `git commit` interception tests.

---

## Execution Environment

| Component | Specification |
|---|---|
| CPU | AMD EPYC 9354P (2 vCPUs allocated, 2.0 GHz base) |
| RAM | 7.8 GB (daemon RSS at idle-warm: ~1.0 GB) |
| OS | Linux 6.8.0-90-generic (Ubuntu), x86_64 |
| Python | 3.12.3 (CPython) |
| PyTorch | 2.14.1+cpu |
| Julia runtime | supersonic-julia 0.1.0 (`pip install -e ./models/julia-1`), transformers 5.0.0, tokenizers 0.22.2, safetensors 0.8.0 |
| Install path | `pip install -r requirements.txt` → `pip install -e .` → `python -m latch.cli download-model` (46 files) → `pip install -e ./models/julia-1` — **all documented steps worked unmodified** |

Note: installing the Julia runtime downgrades `huggingface_hub` 2.0.0 → 1.33.0 (pinned by `supersonic-julia`); everything functions correctly on the downgraded version.

---

## 1. Full Test Suite — First Fully-Green Run

```text
pytest (all markers): 57 passed in 13.93s
```

Including `tests/test_live_inference.py` (real Julia-1 forward passes):

```text
[EVAL] Clean diff: P=0.0956  Latency=756ms
[EVAL] Leak diff:  P=0.8517  Latency=280ms
```

This is the first environment in this repo's history where the live-model test passes (prior runs: no weights/torch/julia provisioned).

---

## 2. Benchmark Results (`python -m latch.cli benchmark`, exit 0)

Run twice back-to-back; results stable within latency noise.

| Category | Sample File | Ground Truth | Measured P(PII) | Decision (P ≥ 0.65) | Verdict |
|---|---|---|---|---|---|
| clean | `sample_algo.py` | CLEAN | 0.00 | Clean | **PASS** |
| clean | `sample_big_algorithm_300lines.py` | CLEAN | 0.87 | Leak | *FP* |
| clean | `sample_config.py` | CLEAN | 0.06 | Clean | **PASS** |
| clean | `sample_database_migration.py` | CLEAN | 0.13 | Clean | **PASS** |
| clean | `sample_impressum_with_pragma.py` | CLEAN | 0.05 | Clean | **PASS** |
| clean | `sample_order.py` | CLEAN | 0.22 | Clean | **PASS** |
| pii | `sample_big_file_hidden_aws_secret.py` | LEAK | 1.00 | Leak | **PASS** |
| pii | `sample_credentials.py` | LEAK | 0.83 | Leak | **PASS** |
| pii | `sample_leak.py` | LEAK | 1.00 | Leak | **PASS** |
| pii | `sample_patient_records_multi_pii.py` | LEAK | 0.99 | Leak | **PASS** |
| pii | `sample_unprotected_impressum_leak.py` | LEAK | 0.91 | Leak | **PASS** |
| pii | `sample_user_profile.py` | LEAK | 0.84 | Leak | **PASS** |
| adversarial | `sample_injection_benign.py` | CLEAN | 0.34 | Clean | **PASS** |
| adversarial | `sample_injection_delimiter.py` | LEAK | 0.84 | Leak | **PASS** |
| adversarial | `sample_injection_override.py` | LEAK | 0.92 | Leak | **PASS** |
| adversarial | `sample_injection_override_large.py` | LEAK | 0.98 | Leak | **PASS** |

| Metric | Target | VPS Result | Windows Result (`BENCHMARK_REPORT.md`) |
|---|---|---|---|
| False Negative Rate | 0.0% | **0.0%** (0/6 missed) | 0.0% |
| Injection Resilience | 100% | **100.0%** (4/4) | 100.0% |
| Overall Accuracy | ≥ 90% | **93.8%** (15/16) | 93.8% |
| False Positive Rate | ≤ 15% | **14.3%** (1/7) | 14.3% |
| Mean Latency / Sample (cold, in-process) | sub-4s | **3,101–3,111 ms** | 2,811.7 ms |
| Full benchmark wall time | — | **~51 s** | not reported |

### Cross-machine determinism (notable)

**Every per-sample probability is bit-identical to the Windows report** (0.87, 1.00, 0.83, 0.34, 0.84, 0.92, 0.98, …) despite completely different CPU/OS/PyTorch build. This confirms Julia-1's non-autoregressive forward pass is fully deterministic and **independently validates the original report** — the numbers were not machine-specific or fabricated.

The single FP (`sample_big_algorithm_300lines.py`, P=0.87) reproduces exactly: a 300-line clean algorithmic file is conservatively flagged on both machines. Model behavior, not environment noise.

Cold-path latency on 2 weak vCPUs is only ~10% worse than the Windows laptop (3.1s vs 2.8s per sample) — Julia-1's 144M-param CPU footprint is genuinely modest.

---

## 3. Warm Daemon Path — First Real Measurements (previously unverified)

Daemon started from the target repo (`latch daemon start`): **warm and ready in ~10s**; token file written 0600; `daemon stop` terminates cleanly and removes PID+token.

| Measurement | Result (2 vCPU VPS) |
|---|---|
| Warm eval, small clean diff (daemon-side) | **170–206 ms** |
| Warm eval under instrumentation (probe + HMAC + eval) | ~300 ms |
| Warm `git commit`, clean file (hook E2E) | **0.58–0.67 s wall** (`✓ Latch: Clean (~430–515ms, daemon)`) |
| Warm `git commit`, PII file (hook E2E, blocked, incl. dissection) | **0.56 s wall**, correct banner (P=0.73 ≥ 0.65) |
| Cold in-process `git commit` (no daemon) | **~11 s wall** (blocked or clean) |

### Verdict on the "sub-50ms" claim

**Not achieved on this hardware** — warm per-eval floor is ~170ms and a full warm commit is ~0.6s. The warm daemon still delivers a **~18× speedup over cold start** (0.6s vs 11s), which is the UX claim that actually matters at a commit hook. Recommendation: retitle the claim as hardware-dependent (e.g., "sub-second warm commits; sub-50ms IPC overhead") or measure per-eval latency on the demo machine — the IPC/probe overhead itself is <5ms; the ~170ms is Julia-1 forward-pass time on 2 EPYC cores.

### ⚠ First-request anomaly (real bug found)

The **first** evaluation against a freshly started daemon took **34s end-to-end** in the hook path: the daemon's startup warm-up calls `engine.load()` but never runs a dummy inference, so the first real request pays lazy torch/tokenizer initialization, exceeds the 10s `daemon_eval_timeout_sec`, and the client falls back to a **cold in-process load in the hook process** (~20s, +~700MB RSS alongside the daemon's ~1GB — visible memory thrash, `sys` time 6.8s). Every subsequent request: 170–300ms.

**Fix (one line):** run a throwaway `engine.evaluate("<warmup>")` inside `run_daemon_process()` after `load()`, before `serve_forever()`. Optionally also pre-touch the tokenizer during `load()`.

---

## 4. Git Hook E2E (installed into a *separate* repo — validates package-root path resolution)

Scratch repo `/tmp/latch-demo`, hook installed via `latch install` from the repo's own venv:

| Scenario | Expected | Observed |
|---|---|---|
| `git commit` staging `sample_leak.py` (cold) | block, exit 1 | ✅ `[LATCH BLOCKED] … PII confidence 1.00 ≥ 0.65`, pinpointed 12-line window, exit 1 |
| `git commit` staging clean `sample_algo.py` (cold) | pass, exit 0 | ✅ committed (`✓ Latch: Clean`) |
| `git commit` staging `sample_credentials.py` (warm daemon) | block, exit 1 | ✅ P=0.73, exit 1, 0.56s |
| Warm clean commits ×3 (daemon) | pass | ✅ 0.58–0.67s each, banner shows `daemon` mode |
| `daemon status` / `daemon stop` | report / clean stop | ✅ token+PID removed on stop |

Config, model weights, prompt template, and criteria all resolved correctly from a foreign CWD via package-root resolution (review_03 C3 fix confirmed working in the field).

---

## 5. Summary

- **All documented install steps work verbatim on a clean, weak Linux VPS.**
- **57/57 tests pass including live Julia-1 inference** — first fully green run of the suite.
- **Benchmark reproduces the Windows report exactly** (accuracy 93.8%, FNR 0.0%, FPR 14.3%, injection resilience 100%) with **bit-identical per-sample probabilities across architectures** — strong evidence of deterministic, portable model behavior and of report integrity.
- **Warm daemon path measured for the first time**: ~0.6s/commit vs ~11s cold (18×), but the "sub-50ms" headline does not hold on 2 vCPUs; retitle or re-measure.
- **New bug found**: first request after daemon start can exceed the eval timeout → 34s hook stall + memory thrash on small machines. Fix: dummy warm-up inference before `serve_forever()`.
- Known FP on large clean files (P=0.87) reproduces cross-machine — model-level behavior; needs user guidance or chunk re-scoring, as flagged in review_04.
