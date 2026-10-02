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
  ✓ Latch: Clean (1,840ms, daemon)
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

### Whole-Codebase Scanning (`latch scan`)

Audit an entire project or directory tree rather than just staged git changes:

```bash
# Scan current repository or project directory (automatically respects .gitignore)
python -m latch.cli scan .

# Scan specific directory with custom extensions and threshold
python -m latch.cli scan ./src --ext .py,.ts,.json --threshold 0.70

# Customize batch chunk size (default: 750 tokens)
python -m latch.cli scan ./backend --max-chunk-tokens 1000

# Exempt multiple directories (comma-separated or multiple flags)
python -m latch.cli scan . --ignore-dir fixtures,CoverLetters,tests/reports

# Allowlist specific test fixture paths
python -m latch.cli scan . --allowlist "tests/fixtures/*"

# Disable .gitignore filtering if you want to inspect uncommitted assets:
python -m latch.cli scan . --no-gitignore

# Export report to a custom file
python -m latch.cli scan . --report ./reports/audit.md
```

- **Automatic `.gitignore` Filtering**: Automatically discovers and parses `.gitignore` in the target directory or parent git root, skipping non-version-controlled files, temporary build outputs, and local documents.
- **Automatic Noise Pruning**: Silently skips default build/cache directories (`.git`, `.venv`, `node_modules`, `__pycache__`, `models/julia-1`, etc.) and binary files.
- **Persistent Audit Reports**: Automatically generates `.latch/reports/scan_report.md` (Markdown with clickable file/line links, snippets, Gitignore File Exemptions, and Ignored Directories) and `scan_report.json`.
- **Intelligent Whitelist Suggestions**: When leaks are detected in test fixtures or mock directories, Latch analyzes the paths and displays actionable configuration snippets to add to `config.json`.
- **Adaptive Dissection**: Localizes findings down to the exact file and line range using binary search.
- **Warm Daemon Acceleration**: Keeps model weights resident in RAM, eliminating cold-start initialization overhead on subsequent commits.

### Run Background Daemon for Warm Inference

Start the local background daemon to keep Julia-1 pre-warmed in memory, avoiding model reload overhead on every commit:

```bash
# Start daemon in background (Windows PowerShell)
.\scripts\windows\start-daemon.ps1

# Or start daemon directly
python -m latch.daemon &

# Check daemon health and status
.\scripts\windows\status-daemon.ps1

# Stop daemon cleanly
.\scripts\windows\stop-daemon.ps1
```

---

## Observability, Profiling & Dashboards

The warm background daemon is instrumented with an in-memory, sub-millisecond phase profiler (`src/latch/metrics.py`) that decomposes every request into granular execution phases:
- **`read_ms`**: HTTP request body reading and decoding (< 0.05 ms)
- **`tokenize_ms`**: BPE subword tokenization (~3 ms)
- **`prep_ms`**: Tensor preparation and memory allocation (< 0.01 ms)
- **`forward_ms`**: PyTorch neural network forward pass through Julia-1 (~200–1,500 ms on CPU, 99.7% of total time)
- **`scoring_ms`**: Noul binary logit extraction and softmax (< 0.1 ms)
- **`write_ms`**: JSON response serialization and network transmission (< 0.5 ms)
- **`total_ms`**: End-to-end request duration

### 1. Instant Built-in Web Dashboard (Zero Setup)

To protect local telemetry and daemon control from unauthorized local processes or browser tabs, the daemon enforces mutual authentication via an ephemeral token generated at startup and saved to `.latch/daemon.token`.

#### Getting Your Authenticated Dashboard Link

Run the status command to output the pre-authenticated clickable URL:

```bash
# Windows PowerShell
.\scripts\windows\status-daemon.ps1

# Or via CLI directly (cross-platform)
python -m latch.cli daemon status
```

**Output:**
```text
[OK] Latch daemon: RUNNING on 127.0.0.1:5138 (PID: 29056)
[INFO] Observability Dashboard: http://127.0.0.1:5138/dashboard?token=41c58541262c591f42da469d...
```

Open that URL in your browser:
```
http://127.0.0.1:5138/dashboard?token=<YOUR_DAEMON_TOKEN>
```

> **Note**: Accessing `/dashboard` without the `?token=` parameter will return `401 Unauthorized`. The dashboard automatically passes your token to background telemetry polling and Prometheus export links.

The standalone web interface visualizes:
- **Live throughput**: Requests/sec and Token/sec gauges.
- **Rolling Percentiles**: Cards showing `p50`, `p90`, `p99`, `avg`, `min`, and `max` latency.
- **Stacked Execution Phase Bars**: Color-coded breakdown showing exactly where milliseconds are spent.
- **Recent Requests Table**: Log of recent evaluations with request IDs, token counts, probabilities, and timestamps.
- **Live Auto-Refresh**: Polls `GET /v1/stats` every 2 seconds without external dependencies.

### 2. Telemetry Endpoints

All telemetry endpoints require the daemon authentication token, supplied via query parameter (`?token=...`) or header (`X-Latch-Token: ...`):

- **JSON Telemetry (`/v1/stats`)**:
  ```bash
  # Query parameter
  curl "http://127.0.0.1:5138/v1/stats?token=$(cat .latch/daemon.token)"

  # Or using header
  curl -H "X-Latch-Token: $(cat .latch/daemon.token)" http://127.0.0.1:5138/v1/stats
  ```
- **Prometheus Metrics (`/metrics`)**:
  ```bash
  # Query parameter
  curl "http://127.0.0.1:5138/metrics?token=$(cat .latch/daemon.token)"

  # Or using header
  curl -H "X-Latch-Token: $(cat .latch/daemon.token)" http://127.0.0.1:5138/metrics
  ```
  Exposes gauges and counters for:
  - `latch_daemon_uptime_seconds`
  - `latch_daemon_requests_total`, `latch_daemon_tokens_processed_total`
  - `latch_daemon_throughput_reqs_per_second`, `latch_daemon_throughput_tokens_per_second`
  - `latch_phase_duration_ms{phase="forward",stat="p50|p90|p99|avg"}`

---

## How to Install and Use Grafana to Visualize Metrics

To set up visual monitoring with Prometheus and Grafana:

### Step 1: Run Prometheus

1. Create a minimal `prometheus.yml` configuration (including the `token` parameter from `.latch/daemon.token`):
   ```yaml
   global:
     scrape_interval: 2s
     evaluation_interval: 2s

   scrape_configs:
     - job_name: "latch-daemon"
       metrics_path: "/metrics"
       params:
         token: ["<YOUR_DAEMON_TOKEN>"]
       static_configs:
         - targets: ["127.0.0.1:5138"]
   ```

2. Start Prometheus:
   - **Using Docker (Linux / VPS)**:
     ```bash
     docker run -d --name prometheus --network host -v $(pwd)/prometheus.yml:/etc/prometheus/prometheus.yml prom/prometheus
     ```
   - **Using Docker (WSL2 / Docker Desktop)**:
     Use `host.docker.internal:5138` in your `prometheus.yml` targets, then run:
     ```bash
     docker run -d --name prometheus -p 9090:9090 -v ${PWD}/prometheus.yml:/etc/prometheus/prometheus.yml prom/prometheus
     ```
   - **Standalone Binary (Zero Docker, Windows native)**:
     Download from [prometheus.io/download](https://prometheus.io/download/) and run directly:
     ```bash
     ./prometheus.exe --config.file=prometheus.yml
     ```

3. Open `http://localhost:9090/targets` to verify Prometheus is scraping `http://127.0.0.1:5138/metrics` with status **UP**.

### Step 2: Run Grafana

1. Start Grafana:
   - **Using Docker**:
     ```bash
     docker run -d --name grafana -p 3000:3000 grafana/grafana
     ```
   - **Standalone Binary**:
     Download from [grafana.com/grafana/download](https://grafana.com/grafana/download/) and start the server.

2. Open Grafana in your browser at `http://localhost:3000` (default credentials: `admin` / `admin`).

### Step 3: Add Prometheus Data Source in Grafana

1. In Grafana, navigate to **Connections** > **Data Sources** > **Add data source**.
2. Select **Prometheus**.
3. Set the server URL:
   - Local: `http://127.0.0.1:9090`
   - Docker container to host: `http://host.docker.internal:9090`
4. Click **Save & test** to verify connectivity.

### Step 4: Import the Prebuilt Latch Dashboard

1. In Grafana, navigate to **Dashboards** > **New** > **Import**.
2. Click **Upload dashboard JSON file** and select:
   ```
   dashboards/latch_daemon_grafana.json
   ```
3. Select your Prometheus data source from the dropdown and click **Import**.

### What You Will See in Grafana:
- **Phase Breakdown Heatmap & Stacked Time Series**: Visually verify that the neural network forward pass (`forward_ms`) accounts for >99.5% of total latency while tokenization, IPC, and scoring take < 0.5%.
- **Percentile Latency Tracker**: Live graphs for p50, p90, and p99 request duration.
- **Throughput Metrics**: Live tokens/sec and evaluations/sec gauges.
- **Hardware Bottleneck Verification**: Provides empirical confirmation of whether computation has reached the CPU memory bandwidth threshold.


### Run the Test Suite

Latch separates fast unit tests from live model inference integration tests:

```bash
# 1. Default test run (runs all unit tests in ~5s; skips heavy integration tests)
pytest -v

# 2. Live model inference integration test (requires downloaded Julia-1 model weights)
pytest --run-integration tests/integration/test_live_inference.py -s -v

# 3. Run all tests together (all unit tests + live model inference)
pytest --run-integration -v
```

> **Integration Tests**: Live inference tests require the local Julia-1 model weights (`python -m latch.cli download-model`) and runtime package (`pip install -e ./models/julia-1`). They are separated into `tests/integration/` and skipped by default so that CI environments (e.g. GitHub Actions) run fast, isolated unit test suites without requiring hundreds of megabytes of model weights.
>
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

### Slice 3: Warm IPC Daemon & Two-Tier Fallback
- **Daemon (`src/latch/daemon.py`)**: Background `ThreadingHTTPServer` bound to `127.0.0.1:5138` with `/v1/health`, `/v1/evaluate`, and `/v1/shutdown`. Pre-warms weights and runs a warm-up inference on startup.
- **Client (`src/latch/client.py`)**: 50ms fast HTTP probe; seamlessly routes to warm daemon for accelerated evaluations without model reload overhead (see `docs/BENCHMARK_REPORT.md`), with automatic fallback to in-process cold-start if the daemon is offline or times out.
- **Lifecycle Scripts (`scripts/windows/`)**: `start-daemon.ps1`, `stop-daemon.ps1`, `status-daemon.ps1`.

### Slice 4: One-Touch Git Hook Installation & Strict Fail-Closed Safeguard
- **Hook Installer (`src/latch/hook.py`)**: Automatic discovery of `.git` root and installation of portable shell wrapper script into `.git/hooks/pre-commit` referencing the absolute Python interpreter path.
- **Hook Safety & Backups**: Automatically creates `.git/hooks/pre-commit.latch.bak` when an existing hook is detected.
- **Strict Fail-Closed Invariant (`tests/test_fail_closed.py`)**: Validates that missing weights, corrupt tensors, diff parse failures, or system crashes always abort the commit with exit code `1` and actionable diagnostic guidance.

### Slice 5: Whole-Codebase Scanning Engine
- **Scanner Engine (`src/latch/scanner.py`)**: Traverses directory trees to inspect source files outside git commits.
- **Noise Filtration**: Prunes `.git`, `.venv`, `node_modules`, `__pycache__`, `models/julia-1`, and binary files.
- **Chunk Packing & Dissection**: Groups files into token chunks, evaluates via daemon, and recursively bisects flagged ranges down to the exact file and lines.
- **CLI Subcommand**: Exposes `latch scan [PATH]` with `--ext`, `--threshold`, and `--max-chunk-tokens` options.

---

## Configuration & Customization

All operational settings are loaded strictly from `config.json` with fallback driven by package root resolution:

```json
{
  "config_version": "1.0",
  "model": "SupersonicLabs/Julia-1",
  "model_path": "./models/julia-1",
  "pii_threshold": 0.65,
  "max_chunk_tokens": 750,
  "max_dissection_depth": 15,
  "localization_window_lines": 25,
  "daemon_port": 5138,
  "daemon_probe_timeout_ms": 50,
  "daemon_eval_timeout_sec": 10.0,
  "allowlist_paths": [
    "*impressum*",
    "tests/fixtures/*"
  ]
}
```

### Whitelisting & Exemption Options

Latch provides two flexible mechanisms to handle deliberate public disclosures (e.g., corporate impressum pages, legal notices, or public support contacts):

1. **Path-Level Allowlisting (`allowlist_paths`)**:
   Add glob patterns to `config.json`. Any staged file matching these patterns is completely exempted from pre-commit evaluation:
   ```json
   "allowlist_paths": ["*impressum*", "legal/*", "docs/public_contacts.md"]
   ```

2. **Inline Line Pragma (`# latch:ignore`)**:
   Add `# latch:ignore` to the end of any line containing legitimate public contact info:
   ```python
   SUPPORT_EMAIL = "contact@acme.example.org"  # latch:ignore
   OFFICE_PHONE = "+49-30-12345678"  # latch:ignore
   ```
   Lines with `# latch:ignore` are stripped before batching and never evaluated by the model.

---

## Known Limitations

- **Binary File Scanning (Out of Scope)**:
  Latch is designed exclusively for textual source code diffs. Binary files (e.g., compiled executables, `.png`, `.jpg`, `.pdf`, `.zip`, `.safetensors`, `.pyc`) are detected via git diff binary markers (`Binary files ... differ`) and bypassed (0ms bypass). Binary artifact scanning requires dedicated forensic analysis tools and is not evaluated by Julia-1.
- **Single-Line Minified Assets**:
  Extremely long single lines (e.g., minified JavaScript bundles or lockfiles) are automatically split into chunked lines to prevent context overflow.
- **Dense Algorithmic & Hex Tables (Conservative Sensitivity)**:
  Files consisting of large dense mathematical constants, cryptographic lookup arrays, or hex tables (e.g. >300 lines of unbroken entropy) can trigger conservative sensitivity scores. Use `allowlist_paths` in `config.json` (e.g. `"src/crypto/tables/*"`) or mark specific table declarations with `# latch:ignore` to exempt known non-sensitive constants.

---

## Security Architecture

1. **Mutual Authenticated Daemon IPC (Anti-Impersonation)**:
   The background daemon generates an ephemeral 32-byte cryptographically secure token on startup, stored in `.latch/daemon.token` with restrictive file permissions (`0o600`). The client validates the daemon via an HMAC-SHA256 challenge response during health checks (`GET /v1/health`), and all evaluation (`POST /v1/evaluate`) and shutdown (`POST /v1/shutdown`) requests require the `X-Latch-Token` header. Rogue daemons or unauthenticated processes on port 5138 are automatically rejected and fail-closed.
2. **Repository-Scoped Daemon Isolation (`.latch/`)**:
   The daemon state, PID file (`.latch/daemon.pid`), execution logs (`.latch/daemon.log`), and authentication tokens reside exclusively within the repository-local `.latch/` directory (git-ignored). This guarantees that daemon lifecycle and mutual-auth credentials remain isolated to their respective project workspace on multi-repo developer machines.
3. **DNS Rebinding & CSRF Protection**:
   The daemon rejects any HTTP request whose `Host` header does not match `127.0.0.1` or `localhost`, blocking browser-based cross-origin attacks.
4. **Prompt Injection Hardening (Production & Benchmark)**:
   Staged diff additions are wrapped within explicit `<code_diff_payload>` delimiters by `StateBuilder`. Delimiter escape attempts are sanitized and adversarial directives (`system override`, `return false`, `ignore all instructions`) within comments are neutralized before inference.
5. **Transparent Exemptions**:
   When lines or files are skipped due to allowlist path matching or `# latch:ignore` inline pragmas, Latch surfaces the exact count in the pre-commit output banner (e.g., `[OK] Latch: Clean (32ms, daemon, 2 pragma exempted)`), preventing silent bypasses.
6. **Hook Safety & Clean Uninstall**:
   Running `python -m latch.cli uninstall` removes the installed pre-commit hook and cleanly restores any preexisting backup (`pre-commit.latch.bak`).

---

## All Build Slices Completed & Verified

All 5 core architectural slices defined in the technical specification and PRD are implemented, covered by 91 automated unit tests (91 passed, 1 integration suite), and verified end-to-end with the live Julia-1 model:
- **FNR (False Negative Rate)**: **0.0%** (zero missed leaks across benchmark credentials and personal records)
- **Prompt Injection Resilience**: **100.0%** (all adversarial injection attempts successfully blocked)
- **Accuracy**: **93.8%** across 16 adversarial, PII, and clean algorithm fixtures
- **Empirical Report**: See [BENCHMARK_REPORT.md](docs/BENCHMARK_REPORT.md) for full reproducible baseline metrics, per-fixture probabilities, and hardware specs.
- **Clean Code Architecture**: 100% standard library IPC, zero silent fallback heuristics, strict fail-closed enforcement.

---

## Interactive Demonstration Suite

Latch includes reproducible simulation scripts under `scripts/demo/` for testing and live demonstrations:

1. **Realistic Git PR Simulation** (`scripts/demo/run_git_simulation_demo.ps1`):
   - Sets up a multi-branch development scenario (`demo-test-base` and `demo-test-feature`).
   - Introduces a realistic 9-file, 227-line enterprise microservices PR (billing engine, notification queue, token-bucket rate limiter, markdown report generator, unit tests, and documentation).
   - Stages customer synchronization code containing sensitive customer PII and live API credentials.
   - Executes `git commit` to demonstrate the active pre-commit hook intercepting and blocking the commit with dissection pinpointing (lines 1–14).
   - Remediates to `os.environ.get(...)` and verifies clean commit acceptance (`[OK] Latch: Clean`).
   - Automatically prunes temporary branches and residual git objects, restoring `main` cleanly.

2. **Interactive Live CLI Walkthrough** (`scripts/demo/run_live_cli_demo.ps1`):
   - Step-by-step walkthrough covering daemon health probing, PII injection, pre-commit hook interception, safe remediation, and whole-codebase repository scanning.
   - Includes fail-fast guardrail self-checks and guaranteed SHA rollback to prevent lingering commits.

---

## Limitations & Threat Model

1. **Client-Side Hook Boundaries**:
   Like all Git client-side hooks, local pre-commit hooks can be bypassed using `git commit --no-verify`. For comprehensive enterprise enforcement, Latch is designed to be paired with server-side CI/CD scanning and remote branch protection rules (defense-in-depth).
2. **Model Semantic Context & Known Trade-offs**:
   Julia-1 is a compact 144.3M parameter SLM fine-tuned specifically on NOUL criteria. While highly effective at detecting unstructured credentials and PII on standard developer workstations without GPU hardware, empirical testing reveals two known small-model trade-offs:
   - **Path-Token Sensitivity**: Model weights exhibit learned sensitivity to path tokens in diff headers. Path prefixes such as `tests/`, `fixtures/`, `mock/`, or `test/` can bias the model's classification toward synthetic test fixtures, reducing sensitivity scores (measured drops of 0.40–0.80 probability compared to production paths like `src/` or `app/`).
   - **Intra-File Structural Dilution**: When sensitive data is deeply embedded within extensive structural scaffolding (e.g. large functions, numerous imports, nested wrapper dictionaries), the token density of the secret relative to surrounding boilerplate drops significantly, reducing model detection confidence. While Latch partitions multi-file diffs to respect file boundaries, intra-file boilerplate dilution remains an inherent trade-off of compact context representations.
3. **Allowlist & Scoping Hygiene**:
   Legitimate test fixtures and mock records should be explicitly declared in `allowlist_paths` inside `config.json` or marked with `# latch:ignore` to prevent test suites from triggering pre-commit blocks. Starter configurations created via `latch install` ship with an empty allowlist (`[]`) by default to prevent accidental exemption leakage in new repositories.


