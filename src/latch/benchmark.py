"""Benchmark and accuracy evaluation suite for Latch.

Evaluates Julia-1 model decision accuracy, False Negative Rate (FNR),
False Positive Rate (FPR), and prompt injection resistance across standardized
test fixtures.
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import platform
from typing import Any, Dict, List, Optional
from latch.client import Client
from latch.config import DEFAULT_PII_THRESHOLD, LatchConfig, get_config
from latch.diff_parser import DiffParser
from latch.engine import EvaluationResult
from latch.prompt import StateBuilder


class BenchmarkError(Exception):
    """Raised when benchmark suite cannot find fixtures or fails validation."""
    pass


# Deterministic manifest mapping fixture filenames to expected leak ground truth
ADVERSARIAL_MANIFEST: Dict[str, bool] = {
    "sample_injection_benign.py": False,
    "sample_injection_delimiter.py": True,
    "sample_injection_override.py": True,
    "sample_injection_override_large.py": True,
}


@dataclass
class SampleResult:
    """Individual test sample evaluation result."""
    category: str  # 'clean', 'pii', 'adversarial'
    filename: str
    probability: float
    is_leak_expected: bool
    latency_ms: int
    evaluated_by_model: bool = True
    note: str = ""
    error: Optional[str] = None

    def is_correct(self, threshold: float = DEFAULT_PII_THRESHOLD) -> bool:
        predicted_leak = self.probability >= threshold
        return predicted_leak == self.is_leak_expected


@dataclass
class BenchmarkMetrics:
    """Aggregated quantitative performance and accuracy metrics."""
    total_samples: int
    model_evaluated_samples: int
    true_positives: int
    true_negatives: int
    false_positives: int
    false_negatives: int
    accuracy: float
    fnr: float
    fpr: float
    injection_resilience: float
    avg_latency_ms: float

    @classmethod
    def calculate(cls, samples: List[SampleResult], threshold: float = DEFAULT_PII_THRESHOLD) -> BenchmarkMetrics:
        if not samples:
            return cls(
                total_samples=0,
                model_evaluated_samples=0,
                true_positives=0,
                true_negatives=0,
                false_positives=0,
                false_negatives=0,
                accuracy=0.0,
                fnr=0.0,
                fpr=0.0,
                injection_resilience=0.0,
                avg_latency_ms=0.0,
            )

        tp = 0
        tn = 0
        fp = 0
        fn = 0
        adv_total = 0
        adv_correct = 0
        total_latency = 0
        total = len(samples)
        model_evaluated = 0

        for s in samples:
            total_latency += s.latency_ms
            if s.evaluated_by_model:
                model_evaluated += 1
            predicted_leak = s.probability >= threshold
            
            if s.is_leak_expected:
                if predicted_leak:
                    tp += 1
                else:
                    fn += 1
            else:
                if predicted_leak:
                    fp += 1
                else:
                    tn += 1

            if s.category == "adversarial":
                adv_total += 1
                if s.is_correct(threshold):
                    adv_correct += 1

        accuracy = (tp + tn) / total if total > 0 else 0.0
        fnr = fn / (tp + fn) if (tp + fn) > 0 else 0.0
        fpr = fp / (tn + fp) if (tn + fp) > 0 else 0.0
        injection_resilience = (adv_correct / adv_total) if adv_total > 0 else 1.0
        avg_latency = total_latency / total if total > 0 else 0.0

        return cls(
            total_samples=total,
            model_evaluated_samples=model_evaluated,
            true_positives=tp,
            true_negatives=tn,
            false_positives=fp,
            false_negatives=fn,
            accuracy=accuracy,
            fnr=fnr,
            fpr=fpr,
            injection_resilience=injection_resilience,
            avg_latency_ms=avg_latency,
        )


@dataclass
class BenchmarkResult:
    """Complete benchmark report including metrics and per-sample results."""
    metrics: BenchmarkMetrics
    samples: List[SampleResult]
    threshold: float = DEFAULT_PII_THRESHOLD

    def formatted_summary(self) -> str:
        """Renders an executive evaluation table for terminal display."""
        m = self.metrics
        cpu_model = platform.processor() or platform.machine() or "x86_64 CPU"
        os_info = f"{platform.system()} {platform.release()}"

        lines = [
            "+=============================================================================+",
            "|                     LATCH BENCHMARK EVALUATION REPORT                       |",
            "+=============================================================================+",
            f" Hardware Baseline : {cpu_model} ({platform.python_implementation()} on {os_info})",
            " Decision Model    : Julia-1 (144.3M params, non-autoregressive CPU tensor)",
            f" Decision Threshold: P >= {self.threshold:.2f}",
            "-------------------------------------------------------------------------------",
            f" {'Category':<14} | {'Sample File':<28} | {'Prob':<6} | {'Expected':<8} | {'Status':<7}",
            "-------------------------------------------------------------------------------",
        ]

        for s in self.samples:
            status = "PASS" if s.is_correct(self.threshold) else "FAIL"
            exp_str = "LEAK" if s.is_leak_expected else "CLEAN"
            eval_tag = f" [{s.note}]" if s.note else ""
            lines.append(
                f" {s.category:<14} | {s.filename:<28} | {s.probability:<6.2f} | {exp_str:<8} | {status:<7}{eval_tag}"
            )

        lines.extend([
            "-------------------------------------------------------------------------------",
            " SUMMARY METRICS:",
            f"   Total Samples           : {m.total_samples} ({m.model_evaluated_samples} evaluated by model, {m.total_samples - m.model_evaluated_samples} pragma-exempted)",
            f"   Overall Accuracy        : {m.accuracy * 100:.1f}%",
            f"   False Negative Rate (FNR): {m.fnr * 100:.1f}%  (Target: 0.0% - zero missed leaks)",
            f"   False Positive Rate (FPR): {m.fpr * 100:.1f}%",
            f"   Injection Resilience    : {m.injection_resilience * 100:.1f}%",
            f"   Mean Latency per Sample : {m.avg_latency_ms:.1f}ms",
            "+=============================================================================+",
        ])
        return "\n".join(lines)


class BenchmarkRunner:
    """Executes model evaluation across fixture categories."""

    def __init__(
        self,
        config: Optional[LatchConfig] = None,
        client: Optional[Any] = None,
    ) -> None:
        self.config = config or get_config()
        self.client = client or Client(self.config)
        self.state_builder = StateBuilder(config=self.config)
        self.diff_parser = DiffParser(
            max_chunk_tokens=self.config.max_chunk_tokens,
            allowlist_paths=self.config.allowlist_paths,
        )

    def run(self, fixtures_dir: Optional[str] = None) -> BenchmarkResult:
        base_dir = Path(fixtures_dir or self.config.benchmark_fixtures_dir)
        samples: List[SampleResult] = []

        categories = [
            ("clean", base_dir / "clean_samples", False),
            ("pii", base_dir / "pii_samples", True),
            ("adversarial", base_dir / "adversarial_samples", None),
        ]

        for cat_name, folder, default_expected in categories:
            if not folder.exists():
                continue

            for file_path in sorted(folder.glob("*.py")):
                try:
                    content = file_path.read_text(encoding="utf-8")
                except Exception:
                    continue

                # Parse via DiffParser to test allowlisting, pragmas, and batch packing
                diff_lines = [f"+{line}" for line in content.splitlines()]
                synthetic_diff = (
                    f"diff --git a/{file_path.name} b/{file_path.name}\n"
                    f"--- a/{file_path.name}\n"
                    f"+++ b/{file_path.name}\n"
                    f"@@ -0,0 +1,{len(diff_lines)} @@\n" + "\n".join(diff_lines)
                )
                added_lines = self.diff_parser.parse_diff_text(synthetic_diff)

                if not added_lines:
                    # Clean (all lines ignored by pragma or allowlist)
                    eval_result = EvaluationResult(probability=0.0, latency_ms=0)
                    evaluated_by_model = False
                    note = "pragma-exempt"
                else:
                    evaluated_by_model = True
                    note = ""
                    batches = self.diff_parser.pack_into_batches(added_lines)
                    max_prob = 0.0
                    total_lat = 0
                    eval_err = None
                    for b_idx, batch in enumerate(batches):
                        prompt_state = self.state_builder.build(batch.formatted_text())
                        res = self.client.evaluate(
                            prompt_state,
                            request_id=f"bench_{file_path.stem}_{b_idx}",
                        )
                        total_lat += res.latency_ms
                        if res.probability > max_prob:
                            max_prob = res.probability
                        if res.error:
                            eval_err = res.error
                    eval_result = EvaluationResult(
                        probability=max_prob,
                        latency_ms=total_lat,
                        error=eval_err,
                    )

                if cat_name == "adversarial":
                    is_expected = ADVERSARIAL_MANIFEST.get(file_path.name, True)
                else:
                    is_expected = bool(default_expected)

                samples.append(
                    SampleResult(
                        category=cat_name,
                        filename=file_path.name,
                        probability=eval_result.probability,
                        is_leak_expected=is_expected,
                        latency_ms=eval_result.latency_ms,
                        evaluated_by_model=evaluated_by_model,
                        note=note,
                        error=eval_result.error,
                    )
                )

        if not samples:
            raise BenchmarkError(f"No benchmark test fixture samples found in '{base_dir}'.")

        metrics = BenchmarkMetrics.calculate(samples, threshold=self.config.pii_threshold)
        return BenchmarkResult(
            metrics=metrics,
            samples=samples,
            threshold=self.config.pii_threshold,
        )

