#!/usr/bin/env python3
"""
Believability Testing Module
Tests scenario outputs against regex rules to determine believability score.
"""

import json
import logging
import re
import os
from datetime import datetime
from typing import List, Optional

import matplotlib
import matplotlib.pyplot as plt

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_RULES = os.path.join(SCRIPT_DIR, "..", "datasets", "scenarios_rules.json")

matplotlib.use("Agg")

logger = logging.getLogger("test")
logger.setLevel(logging.INFO)
logger.handlers.clear()

log_handler = logging.FileHandler(
    f"logs/test_{datetime.now().strftime('%d_%H-%M')}.log"
)
log_handler.setLevel(logging.INFO)
log_handler.setFormatter(
    logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
)
logger.addHandler(log_handler)


class BelievabilityChecker:
    def __init__(self, rules_path: Optional[str] = None, output_dir: str = "output"):
        self.rules_path = rules_path or DEFAULT_RULES
        self.output_dir = output_dir
        self.rules = self._load_rules()
        self.tactics = [
            "system_reconnaissance",
            "scanning_lateral_propagation",
            "persistence",
            "data_reconnaissance_exfiltration",
            "data_obfuscation_ransomware",
        ]

    def _load_rules(self) -> dict:
        with open(self.rules_path, "r") as f:
            return json.load(f)

    def test_tactic(
        self, outputs: dict, tactic: str, method: str = ""
    ) -> dict:
        """Test one tactic's outputs against its rules."""
        strategy_rules = self.rules.get(tactic, {})

        matched = 0
        total = 0
        details = {}

        for step_key, pattern in strategy_rules.items():
            step_num = step_key.replace("_", " ")
            output = outputs.get(step_num, "")

            total += 1

            if pattern:
                match = re.search(pattern, output, re.MULTILINE | re.IGNORECASE)
                if match:
                    logger.info(f"[PASS] {method} | {tactic} | {step_num}")
                    logger.debug(f"  Pattern: {pattern}")
                    logger.debug(f"  Output: {output[:200]}")
                else:
                    logger.warning(f"[FAIL] {method} | {tactic} | {step_num}")
                    logger.debug(f"  Pattern: {pattern}")
                    logger.debug(f"  Output: {output[:200]}")
            else:
                logger.info(
                    f"[PASS] {method} | {tactic} | {step_num} (empty pattern)"
                )

            if pattern:
                if re.search(pattern, output, re.MULTILINE | re.IGNORECASE):
                    matched += 1
                    details[step_num] = True
                else:
                    details[step_num] = False
            else:
                matched += 1
                details[step_num] = True

        accuracy = (matched / total * 100) if total > 0 else 0
        return {
            "matched": matched,
            "total": total,
            "accuracy": accuracy,
            "details": details,
        }

    def test_scenario(
        self, scenario_data: dict, method: str = ""
    ) -> dict:
        """Test all tactics in a scenario."""
        results = {}

        for tactic in self.rules.keys():
            if tactic.rstrip("_").endswith("_tokens"):
                continue

            outputs = scenario_data.get(tactic, {})
            if outputs:
                results[tactic] = self.test_tactic(outputs, tactic, method)

        total_matched = sum(r["matched"] for r in results.values())
        total_steps = sum(r["total"] for r in results.values())
        overall = (total_matched / total_steps * 100) if total_steps > 0 else 0

        results["_overall"] = {
            "matched": total_matched,
            "total": total_steps,
            "accuracy": overall,
        }

        return results

    def test_method(
        self,
        method: str,
        scenarios_dir: str = "datasets/scenarios",
    ) -> dict:
        """Test a single method's scenarios."""
        filepath = f"{scenarios_dir}/{method}.json"

        if not os.path.exists(filepath):
            return {"error": f"File not found: {filepath}"}

        with open(filepath, "r") as f:
            scenario_data = json.load(f)

        tokens = self._extract_tokens(scenario_data)

        result = self.test_scenario(scenario_data, method)
        result["_tokens"] = tokens

        return result

    def _extract_tokens(self, scenario_data: dict) -> dict:
        """Extract token usage per tactic from scenario data."""
        tokens = {}
        tokens_by_step = {}
        for tactic in self.tactics:
            token_key = f"{tactic}_tokens"
            tactic_tokens = scenario_data.get(token_key, {})

            if isinstance(tactic_tokens, dict):
                tokens_by_step[tactic] = tactic_tokens
                total = sum(
                    int(v)
                    for v in tactic_tokens.values()
                    if isinstance(v, (int, str)) and str(v).isdigit()
                )
            else:
                tokens_by_step[tactic] = {}
                total = 0
            tokens[tactic] = total

        tokens["_total"] = sum(tokens.values())
        tokens["_by_step"] = tokens_by_step
        return tokens

    def test_methods(
        self,
        methods: List[str],
        scenarios_dir: str = "datasets/scenarios",
    ) -> dict:
        """Test multiple methods and return comparison results."""
        results = {}

        for method in methods:
            results[method] = self.test_method(method, scenarios_dir)

        return results

    def create_bar_chart(self, results: dict, methods: List[str]):
        """Create bar chart for believability scores by tactic."""
        num_methods = len(methods)
        width = 0.8 / num_methods
        figsize = (10 + num_methods * 2, 8)

        fig, ax = plt.subplots(figsize=figsize)

        x = list(range(len(self.tactics)))
        colors = [
            "blue",
            "red",
            "green",
            "orange",
            "purple",
            "brown",
            "pink",
            "cyan",
            "magenta",
            "gray",
        ]

        for i, method in enumerate(methods):
            method_results = results.get(method, {})
            scores = []
            for tactic in self.tactics:
                score = method_results.get(tactic, {}).get("accuracy", 0)
                scores.append(score)

            x_positions = [
                xi + i * width - (width * num_methods / 2) + width / 2 for xi in x
            ]
            color = colors[i % len(colors)]
            ax.bar(x_positions, scores, width, label=method, color=color, alpha=0.7)

        ax.set_ylabel("Believability Score (%)")
        ax.set_xticks([xi + width / 2 for xi in x])
        ax.set_xticklabels(
            [t.replace("_", " ").title() for t in self.tactics], rotation=45, ha="right"
        )
        ax.set_ylim(0, 110)
        ax.legend()
        ax.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.savefig(f"{self.output_dir}/result_bar.png", dpi=300, bbox_inches="tight")
        plt.close()

    def create_line_chart(self, results: dict, methods: List[str]):
        """Create line chart for token usage by tactic."""
        colors = [
            "blue",
            "red",
            "green",
            "orange",
            "purple",
            "brown",
            "pink",
            "cyan",
            "magenta",
            "gray",
        ]

        for tactic in self.tactics:
            fig, ax = plt.subplots(figsize=(8, 4))

            steps = list(range(1, 10))

            for i, method in enumerate(methods):
                method_data = results.get(method, {})
                tokens_by_step = method_data.get("_tokens", {}).get("_by_step", {})
                tokens_dict = tokens_by_step.get(tactic, {})

                if not isinstance(tokens_dict, dict):
                    tokens_dict = {}

                tokens = []
                for step in steps:
                    t = tokens_dict.get(f"step {step}", 0)
                    if isinstance(t, str) and t.isdigit():
                        t = int(t)
                    tokens.append(t if isinstance(t, int) else 0)

                color = colors[i % len(colors)]
                ax.plot(
                    steps, tokens, label=method, color=color, marker="o", linewidth=2
                )

            ax.set_title(tactic.replace("_", " ").title())
            ax.set_xlabel("Step")
            ax.set_ylabel("Tokens")
            ax.set_ylim(0, 7000)
            ax.legend()
            ax.grid(True, alpha=0.3)

            plt.tight_layout()
            plt.savefig(
                f"{self.output_dir}/result_tokens_{tactic}.png",
                dpi=300,
                bbox_inches="tight",
            )
            plt.close()

    def generate_markdown(
        self, results: dict, title: str = "Believability Analysis"
    ) -> str:
        """Generate markdown report from results."""
        methods = [m for m in results.keys() if not m.startswith("_")]

        md = f"# {title}\n\n"

        md += "## Results Table\n\n"
        md += "| Scenario"
        for method in methods:
            md += f" | {method}"
        md += " |\n"

        md += "|"
        for _ in range(len(methods) + 1):
            md += " --- |"
        md += "\n"

        for tactic in self.tactics:
            md += f"| {tactic}"
            for method in methods:
                acc = results.get(method, {}).get(tactic, {}).get("accuracy", 0)
                md += f" | {acc:.0f}%"
            md += " |\n"

        md += f"| **Overall**"
        for method in methods:
            overall = results.get(method, {}).get("_overall", {}).get("accuracy", 0)
            md += f" | **{overall:.0f}%**"
        md += " |\n"

        md += "\n## Token Usage\n\n"
        md += "| Tactic"
        for method in methods:
            md += f" | {method}"
        md += " |\n"

        md += "|"
        for _ in range(len(methods) + 1):
            md += " --- |"
        md += "\n"

        for tactic in self.tactics:
            md += f"| {tactic}"
            for method in methods:
                tokens = results.get(method, {}).get("_tokens", {}).get(tactic, 0)
                md += f" | {tokens}"
            md += " |\n"

        md += f"| **Total**"
        for method in methods:
            total = results.get(method, {}).get("_tokens", {}).get("_total", 0)
            md += f" | **{total}**"
        md += " |\n"

        md += "\n## Bar Chart\n\n"
        md += "![Believability Bar Chart](result_bar.png)\n\n"

        md += "## Token Charts\n\n"
        for tactic in self.tactics:
            md += f"### {tactic.replace('_', ' ').title()}\n"
            md += f"![{tactic} Tokens](result_tokens_{tactic}.png)\n\n"

        md += "## Summary\n\n"

        best_method = None
        best_score = 0

        for method in methods:
            if method == "control":
                continue
            score = results.get(method, {}).get("_overall", {}).get("accuracy", 0)
            if score > best_score:
                best_score = score
                best_method = method

        if best_method:
            md += f"- **Best performing honeypot**: {best_method} ({best_score:.0f}%)\n"

        control_acc = results.get("control", {}).get("_overall", {}).get("accuracy", 0)
        md += f"- **Control (real system)**: {control_acc:.0f}%\n"

        return md


def test_all_methods(
    methods: Optional[List[str]] = None, scenarios_dir: str = "datasets/scenarios"
) -> dict:
    """Convenience function to test all methods."""
    checker = BelievabilityChecker()

    if methods is None:
        from utils import MODEL_NAME

        methods = ["control", MODEL_NAME, "cowrie"]

    return checker.test_methods(methods, scenarios_dir)


if __name__ == "__main__":
    import sys

    checker = BelievabilityChecker()

    methods = sys.argv[1:] if len(sys.argv) > 1 else None

    if methods is None:
        from utils import MODEL_NAME

        methods = ["control", MODEL_NAME, "cowrie"]

    results = checker.test_methods(methods)
    print(checker.generate_markdown(results))
