# Latch — Pre-Commit Guardrail

> An ultra-fast, 100% local git pre-commit hook powered by **Julia-1** that blocks leaked PII and credentials before code leaves the developer's laptop.

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12%2B-brightgreen.svg)](https://www.python.org/)
[![Model](https://img.shields.io/badge/Model-Julia--1_(144M)-purple.svg)](https://huggingface.co/SupersonicLabs/Julia-1)
[![Zero-Trust](https://img.shields.io/badge/Zero--Trust-100%25_Local_CPU-orange.svg)]()

---

## Overview

Developers frequently leak sensitive personal data (names with phone numbers, home addresses, government IDs) and credentials (API keys, private tokens, database passwords) into version control. Traditional tools rely on rigid regex rules that miss natural language semantic leaks, or cloud LLMs that violate privacy and introduce unacceptable multi-second commit latency.

**Latch** solves this by running **Julia-1** (an ultra-compact 144.3M parameter non-autoregressive decision model built on `mmBERT-small`) directly on the local CPU:
- **Zero-Trust Privacy**: 100% on-device execution. No cloud API requests, no telemetry, no leaks outside your laptop.
- **CPU Native**: Optimized for standard Intel/AMD/Apple Silicon CPUs without requiring dedicated GPU hardware.
- **Fail-Closed Architecture**: Any system error, missing weights, or invalid environment immediately aborts the commit with an explicit diagnostic banner instead of silently letting unverified code slip through.

---

## Installation & Setup

### Prerequisites
- **Git** 2.25+ on system `PATH`
- **Python** 3.12+ (tested with Python 3.12.x)

### 1. Clone & Set Up Virtual Environment

```bash
git clone <repo-url>
cd <project-directory>

# Create virtual environment with Python 3.12
py -3.12 -m venv .venv

# Activate virtual environment
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate
```

### 2. Install Dependencies

Install PyTorch (CPU build) and Latch package dependencies:

```bash
pip install -r requirements.txt
pip install -e .
```

### 3. Download Julia-1 Model Weights

Download the open weights (~550 MB) directly from Hugging Face into `./models/julia-1`:

```bash
python -m latch.cli download-model
```

Then install the Julia runtime package:

```bash
pip install -e ./models/julia-1
```

---

## How to Use

### Run Pre-Commit Inspection Manually

Inspect any staged code additions currently in your git index:

```bash
python -m latch.cli check
```

- **Clean Diff (`exit 0`)**:
  ```text
  [OK] Latch: Clean (32ms)
  ```
- **Sensitive Leak Detected (`exit 1`)**:
  ```text
  +=======================================================+
  | [LATCH BLOCKED] Sensitive PII or Credentials Detected |
  +=======================================================+
  File:   fixtures/pii_samples/sample_leak.py
  Lines:  1-5 (Pinpointed window: 5 lines)
  Reason: PII confidence 0.81 >= threshold 0.65

  Context Window:
     1 | def get_user_contact():
     2 |     # Direct personal contact details
     3 |     customer_name = "Jane Doe"
     4 |     customer_phone = "+1-555-0199"
     5 |     return {"name": customer_name, "phone": customer_phone}

  Commit aborted. Remove sensitive data or stage clean changes before committing.
  ```

### Run the Test Suite

Latch uses a test-driven development (TDD) workflow with full unit and live inference tests:

```bash
# 1. Fast unit tests (~0.2s - excludes 550MB model cold start)
pytest -m "not slow" -v

# 2. Live model inference test (shows probabilities and latency via -s)
pytest -m slow -s -v

# 3. Run all tests together
pytest -v
```

> **Tip for displaying live test printouts**: Pass `-s` (or `--capture=no`) to `pytest` to prevent output capture and show live `print()` logs, such as model inference probabilities and execution times.

---

## What Was Created in Step 1 (Slice 1)

In **Slice 1 (Core Reflex Gate)**, we established the core end-to-end reflex loop from git diff to model decision:

1. **Diff Parser & Extractor (`src/latch/diff_parser.py`)**:
   - Executes `git diff --staged --no-ext-diff --no-color`.
   - Filters out binary files and deletion-only changes (bypassed instantly in 0ms).
   - Extracts added lines (`+`), tracking exact file names and line numbers.
   - Packs additions into structured file blocks: `=== File: <path> ===`.

2. **Julia-1 Decision Engine (`src/latch/engine.py`)**:
   - Interfaces directly with the native Julia-1 CPU runtime (`from julia import load_model`).
   - Uses the structured `noul` boolean primitive with contrastive criteria to score $P(\text{PII}) \in [0.0, 1.0]$.
   - Verified live on CPU: clean code scored $P = 0.50$ (passed), while real contact records scored $P = 0.81$ (blocked).

3. **Terminal Presenter (`src/latch/presenter.py`)**:
   - Formats clean single-line status messages and high-contrast framed warning banners.
   - Includes automatic console encoding detection with ASCII fallbacks for legacy terminal codepages.

4. **Configuration Manager (`src/latch/config.py`)**:
   - Validates operational settings in `config.json` (thresholds, token budgets, port, template paths).
   - Zero hardcoding: all operational bounds are externalized.

5. **CLI Orchestrator (`src/latch/cli.py`)**:
   - Implements `python -m latch.cli check` and `download-model`.
   - Strictly enforces fail-closed exit code contracts (`0` on clean, `1` on leak or engine error).

6. **Comprehensive Test Suite (`tests/`)**:
   - 18 automated tests passing across config validation, diff extraction, presenter banners, fail-closed handling, and live CPU inference.

---

## Todo List & Roadmap for Upcoming Slices

- [ ] **Slice 2: Adaptive Batching & Binary Dissection Localization**
  - Implement divide-and-conquer binary search across batches to isolate offending files and pinpoint context windows $\le 25$ lines.
  - Implement conservative fallback ensuring split-boundary multi-line PII is never lost.
  
- [ ] **Slice 3: Sub-50ms Warm IPC Daemon & Two-Tier Fallback**
  - Implement `src/latch/daemon.py` using `http.server.ThreadingHTTPServer` bound to `127.0.0.1:5138` with `/v1/health` and `/v1/evaluate`.
  - Implement 50ms socket probe in `client.py` for sub-50ms warm commits, with seamless fallback to in-process cold-start when the daemon is offline.
  - Add Windows background daemon scripts (`scripts/windows/`).

- [ ] **Slice 4: One-Touch Git Hook Integration & Strict Fail-Closed Safeguard**
  - Implement `latch install` in `cli.py` to automatically configure `.git/hooks/pre-commit` using the absolute virtualenv Python path.
  - Add pre-flight checks and fail-closed tests (`tests/test_fail_closed.py`) to verify system behavior when model weights are missing or corrupt.

- [ ] **Slice 5: Evaluation Benchmark & Prompt Injection Hardening Suite**
  - Build `tests/run_benchmark.py` and `latch benchmark` command.
  - Evaluate accuracy, false positive rate (FPR), false negative rate (FNR), and prompt injection resistance across benign, synthetic PII, and adversarial comment fixtures in `fixtures/`.
