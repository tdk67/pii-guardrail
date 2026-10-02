"""Demo Scenario: Seed large clean changes (100+ lines of algorithms).

Creates demo/risk_engine.py with 100+ lines of mathematical risk models,
stages it in git, and demonstrates fast multi-batch evaluation without false positives.
"""

from pathlib import Path
import subprocess
import sys


def seed_large_changes() -> None:
    demo_dir = Path("demo")
    demo_dir.mkdir(exist_ok=True)

    risk_engine_path = demo_dir / "risk_engine.py"
    lines = [
        '"""Quantitative portfolio risk scoring engine."""',
        "",
        "from typing import List, Dict, Optional, Tuple",
        "import math",
        "",
        "",
        "class PortfolioRiskEngine:",
        '    """Calculates Value at Risk (VaR) and conditional drawdown metrics."""',
        "",
        "    def __init__(self, confidence_level: float = 0.95, lookback_window: int = 252) -> None:",
        "        self.confidence_level = confidence_level",
        "        self.lookback_window = lookback_window",
        "        self._variance_cache: Dict[str, float] = {}",
        "",
        "    def compute_daily_returns(self, asset_prices: List[float]) -> List[float]:",
        '        """Computes continuous logarithmic daily returns."""',
        "        if len(asset_prices) < 2:",
        "            return []",
        "        returns: List[float] = []",
        "        for i in range(1, len(asset_prices)):",
        "            prev = asset_prices[i - 1]",
        "            curr = asset_prices[i]",
        "            if prev > 0 and curr > 0:",
        "                returns.append(math.log(curr / prev))",
        "            else:",
        "                returns.append(0.0)",
        "        return returns",
        "",
        "    def calculate_mean_and_variance(self, values: List[float]) -> Tuple[float, float]:",
        '        """Computes sample mean and variance using two-pass algorithm."""',
        "        n = len(values)",
        "        if n < 2:",
        "            return (0.0, 0.0)",
        "        mean = sum(values) / n",
        "        variance = sum((x - mean) ** 2 for x in values) / (n - 1)",
        "        return mean, variance",
        "",
        "    def calculate_parametric_var(self, portfolio_value: float, returns: List[float]) -> float:",
        '        """Computes parametric Value-at-Risk using Gaussian assumption."""',
        "        if not returns:",
        "            return 0.0",
        "        mean, variance = self.calculate_mean_and_variance(returns)",
        "        std_dev = math.sqrt(variance)",
        "        # Z-score for 95% confidence ~ 1.64485",
        "        z_score = 1.644853",
        "        var_pct = z_score * std_dev - mean",
        "        return max(0.0, portfolio_value * var_pct)",
        "",
        "    def calculate_historical_drawdown(self, equity_curve: List[float]) -> float:",
        '        """Finds maximum peak-to-trough drop across historical series."""',
        "        if not equity_curve:",
        "            return 0.0",
        "        max_drawdown = 0.0",
        "        peak = equity_curve[0]",
        "        for price in equity_curve:",
        "            if price > peak:",
        "                peak = price",
        "            drawdown = (peak - price) / peak if peak > 0 else 0.0",
        "            if drawdown > max_drawdown:",
        "                max_drawdown = drawdown",
        "        return max_drawdown",
        "",
        "    def stress_test_portfolio(self, asset_weights: Dict[str, float], shocks: Dict[str, float]) -> float:",
        '        """Calculates instantaneous stress loss under macroeconomic shocks."""',
        "        total_loss_pct = 0.0",
        "        for asset, weight in asset_weights.items():",
        "            shock_factor = shocks.get(asset, 0.0)",
        "            total_loss_pct += weight * shock_factor",
        "        return total_loss_pct",
        "",
        "    def generate_risk_report(self, portfolio_id: str, prices: List[float], equity: float) -> Dict[str, float]:",
        '        """Compiles standard risk metrics object."""',
        "        returns = self.compute_daily_returns(prices)",
        "        mean, var = self.calculate_mean_and_variance(returns)",
        "        std_dev = math.sqrt(var)",
        "        var_95 = self.calculate_parametric_var(equity, returns)",
        "        max_dd = self.calculate_historical_drawdown(prices)",
        "        sharpe = (mean / std_dev * math.sqrt(252)) if std_dev > 0 else 0.0",
        "        return {",
        '            "portfolio_id": portfolio_id,',
        '            "volatility_annualized": std_dev * math.sqrt(252),',
        '            "value_at_risk_95": var_95,',
        '            "maximum_drawdown": max_dd,',
        '            "sharpe_ratio": sharpe,',
        "        }",
    ]
    code = "\n".join(lines) + "\n"
    risk_engine_path.write_text(code, encoding="utf-8")
    print(f"[DEMO] Created large clean file: {risk_engine_path} ({len(lines)} lines)")

    res = subprocess.run(["git", "add", str(risk_engine_path)], capture_output=True, text=True)
    if res.returncode == 0:
        print("[DEMO] Staged in git: git add demo/risk_engine.py")
    else:
        print(f"[DEMO ERROR] Failed to git add: {res.stderr}", file=sys.stderr)


if __name__ == "__main__":
    seed_large_changes()
