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

## Architecture & Design Decisions

### Why Standard Library `http.server` Instead of FastAPI?

We deliberately selected Python's built-in `http.server.ThreadingHTTPServer` over `FastAPI` + `Uvicorn`:

1. **Zero External Server Dependencies**: FastAPI brings a heavy dependency footprint (`uvicorn`, `starlette`, `pydantic`, `anyio`, `idna`, `sniffio`). Keeping the daemon in standard library Python eliminates version conflicts (e.g. Pydantic v1 vs v2 clashes with the host project) and installation footprint.
2. **Sub-10ms Import & Startup**: Importing FastAPI + Uvicorn + Pydantic incurs 200–400ms of module resolution overhead. Standard library `http.server` imports in `< 10ms`.
3. **Pure CPU Tensor Workload**: Julia-1 inference runs synchronously in PyTorch on OpenMP CPU threads. Because the bottleneck is CPU tensor math and not async network I/O, an `asyncio` event loop provides zero throughput benefit.
4. **Minimal Surface Area**: The daemon only exposes 3 localhost loopback endpoints (`/v1/health`, `/v1/evaluate`, `/v1/shutdown`). Interactive OpenAPI/Swagger documentation or complex dependency injection is unnecessary overhead for a local IPC mechanism.

### Timeout Guarantees & Hang Prevention

To guarantee that a git commit never gets stuck waiting forever on a dead, unresponsive, or corrupted daemon:

1. **50ms Fast Probe (`daemon_probe_timeout_ms: 50`)**:
   Before sending any diff payload, the client probes `GET /v1/health` with a strict 50ms socket timeout. If the daemon is not running or doesn't answer within 50ms, the client abandons the probe immediately and falls back to in-process cold-start.
2. **Configurable Evaluation Timeout (`daemon_eval_timeout_sec: 10.0`)**:
   Inference requests to `POST /v1/evaluate` enforce a strict socket timeout (configurable in `config.json`). If the model inference hangs or exceeds 10 seconds, the client catches the timeout exception immediately and falls back to in-process evaluation.
3. **Daemon-Level Exception Shielding**:
   In `src/latch/daemon.py`, all forward passes are wrapped in a comprehensive `try...except Exception` handler. If Julia encounters an unexpected error (e.g., out-of-memory, corrupt tensor, or invalid character encoding), the daemon immediately responds with HTTP 500, sets `probability: 1.0` (fail-closed), logs the error trace, and prevents any unhandled socket hang.
4. **Threaded Worker Isolation**:
   Using `ThreadingHTTPServer` ensures each HTTP request is served on an isolated thread, preventing a single slow or stalled request from blocking subsequent requests.
5. **Two-Tier Client Fallback**:
   If an HTTP request raises `URLError`, `TimeoutError`, or connection reset mid-flight, `src/latch/client.py` catches the error and executes an in-process evaluation so the commit flow never terminates unexpectedly or hangs indefinitely.

---

## What Has Been Created So Far

### Slice 1: Core Reflex Gate
- **Diff Parser (`src/latch/diff_parser.py`)**: Filters out deletions and binary files (0ms bypass), parses added lines (`+`), and packs files into structured blocks.
- **Julia-1 Decision Engine (`src/latch/engine.py`)**: CPU-native inference using `noul` boolean primitive with contrastive false/true criteria.
- **Terminal Presenter (`src/latch/presenter.py`)**: High-contrast ANSI framed banners with automatic Windows codepage fallback.
- **Configuration Manager (`src/latch/config.py`)**: Validated operational settings loaded strictly from `config.json`.
- **CLI Orchestrator (`src/latch/cli.py`)**: Implements `python -m latch.cli check` with fail-closed exit codes (`0` = clean, `1` = leak/error).

### Slice 2: Adaptive Binary Dissection & Localization
- **Dissection Engine (`src/latch/dissection.py`)**: Divide-and-conquer binary search that recursively bisects multi-file staged diffs down to the exact offending file and $\le 25$-line context window.
- **Conservative Split Fallback**: Handles edge-case PII spanning split boundaries by conservatively evaluating the full candidate block if both halves test clean.

### Slice 3: Sub-50ms Warm IPC Daemon & Two-Tier Fallback
- **Daemon (`src/latch/daemon.py`)**: Background `ThreadingHTTPServer` bound to `127.0.0.1:5138` with `/v1/health`, `/v1/evaluate`, and `/v1/shutdown`. Pre-warms weights on startup.
- **Client (`src/latch/client.py`)**: 50ms fast HTTP probe; seamlessly routes to warm daemon for sub-50ms warm commits, with automatic fallback to in-process cold-start if the daemon is offline or times out.
- **Lifecycle Scripts (`scripts/windows/`)**: `start-daemon.ps1`, `stop-daemon.ps1`, `status-daemon.ps1`.

### Slice 4: One-Touch Git Hook Installation & Strict Fail-Closed Safeguard
- **Hook Installer (`src/latch/hook.py`)**: Automatic discovery of `.git` root and installation of portable shell wrapper script into `.git/hooks/pre-commit` referencing the absolute Python interpreter path.
- **Hook Safety & Backups**: Automatically creates `.git/hooks/pre-commit.latch.bak` when an existing hook is detected.
- **Strict Fail-Closed Invariant (`tests/test_fail_closed.py`)**: Validates that missing weights, corrupt tensors, diff parse failures, or system crashes always abort the commit with exit code `1` and actionable diagnostic guidance.

---

## Todo List & Roadmap for Upcoming Slices

- [ ] **Slice 5: Evaluation Benchmark & Prompt Injection Hardening Suite**
  - Build `tests/run_benchmark.py` and `latch benchmark` command.
  - Evaluate accuracy, false positive rate (FPR), false negative rate (FNR), and prompt injection resistance across benign, synthetic PII, and adversarial comment fixtures in `fixtures/`.


