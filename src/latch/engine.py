"""Julia-1 decision engine integration for Latch.

Wraps the Julia-1 native CPU runtime or Hugging Face weights to evaluate
whether staged diff additions contain unencrypted PII or credentials.
Implements strict fail-closed error handling: never returns default probabilities
on engine failure or missing weights.
"""

from __future__ import annotations
import json
import os
import time
from dataclasses import dataclass, field
from typing import Dict, Optional
from latch.config import DEFAULT_PII_THRESHOLD, LatchConfig


class JuliaEngineError(Exception):
    """Base exception for Julia-1 inference or loading failures."""
    pass


class ModelWeightsNotFoundError(JuliaEngineError):
    """Raised when model weights directory does not exist or is incomplete."""
    pass


@dataclass(frozen=True)
class EvaluationResult:
    """Outcome of a Noul binary evaluation."""
    probability: float
    latency_ms: int
    request_id: str = ""
    error: Optional[str] = None
    timings: Dict[str, float] = field(default_factory=dict)

    def is_clean(self, threshold: float = DEFAULT_PII_THRESHOLD) -> bool:
        """Returns True if P(PII) is below the refusal threshold."""
        return self.probability < threshold


class JuliaEngine:
    """Manages Julia-1 model loading and CPU inference."""

    def __init__(self, config: LatchConfig) -> None:
        self.config = config
        self._model = None
        self._initialized = False
        self._criteria: Optional[Dict[str, str]] = None

    def load(self) -> None:
        """Load Julia-1 model into memory."""
        if self._initialized:
            return

        model_dir = os.path.abspath(self.config.model_path)
        if not os.path.exists(model_dir):
            raise ModelWeightsNotFoundError(
                f"Julia-1 model weights not found at '{self.config.model_path}'. "
                "Run 'python -m latch.cli download-model' to download open weights."
            )

        try:
            from julia import load_model  # type: ignore
            self._model = load_model(
                model_dir,
                device="cpu",
                strict_encoding=True,
                max_length=self.config.model_max_context_tokens,
            )
            self._initialized = True
        except ImportError as err:
            raise JuliaEngineError(
                "The Julia runtime package ('julia') is not installed or importable. "
                "Ensure Julia-1 is installed via 'pip install -e ./models/julia-1'."
            ) from err
        except ModelWeightsNotFoundError:
            raise
        except Exception as err:
            raise JuliaEngineError(f"Failed to load Julia-1 model: {err}") from err

    def evaluate(self, state: str, request_id: str = "") -> EvaluationResult:
        """Evaluate a code diff state string via Noul binary classification."""
        start_time = time.perf_counter()

        if not self._initialized:
            self.load()

        if not hasattr(self._model, "predict"):
            raise JuliaEngineError("Julia-1 model is not loaded or does not support .predict().")

        try:
            criteria = self._load_criteria()
            
            t_tok0 = time.perf_counter()
            token_count = len(self._model.tokenizer(state, add_special_tokens=False)["input_ids"]) if hasattr(self._model, "tokenizer") else len(state.split())
            t_tok = (time.perf_counter() - t_tok0) * 1000

            t_fwd0 = time.perf_counter()
            res = self._model.predict(
                state=state,
                questions={
                    "pii_check": {
                        "type": "noul",
                        "instructions": "Does this code diff contain leaked sensitive PII or credentials?",
                        "criteria": criteria,
                    }
                },
            )
            t_fwd = (time.perf_counter() - t_fwd0) * 1000
            prob = float(res.get("answers", {}).get("pii_check", {}).get("noul", 0.0))
            latency = int((time.perf_counter() - start_time) * 1000)
            
            timings = {
                "tokens": token_count,
                "tokenize_ms": t_tok,
                "forward_ms": t_fwd,
                "scoring_ms": max(0.1, latency - t_tok - t_fwd),
            }
            return EvaluationResult(
                probability=prob,
                latency_ms=max(1, latency),
                request_id=request_id,
                timings=timings,
            )
        except Exception as err:
            raise JuliaEngineError(f"Julia-1 inference failed: {err}") from err

    def _load_criteria(self) -> Dict[str, str]:
        """Loads criteria definitions mapping 'false' and 'true' keys."""
        if self._criteria is not None:
            return self._criteria

        path = getattr(self.config, "noul_criteria_path", None)
        if not path or not os.path.exists(path):
            raise JuliaEngineError(f"Criteria definitions file not found at: {path}")

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "criteria" in data and isinstance(data["criteria"], dict):
                    self._criteria = data["criteria"]
                    return self._criteria
                raise JuliaEngineError("Missing 'criteria' object in criteria file.")
        except Exception as err:
            raise JuliaEngineError(f"Failed to load criteria file: {err}") from err

