#!/usr/bin/env python3

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import SCENARIOS, OUTPUT_DIR
from believability import BelievabilityChecker


def main():
    parser = argparse.ArgumentParser(description="Believability Analysis Tool")

    parser.add_argument(
        "--methods",
        nargs="+",
        default=None,
        help="Methods to compare (default: all files in scenarios dir)",
    )

    parser.add_argument(
        "--scenarios-dir",
        default=SCENARIOS,
        help="Directory containing scenario JSON files",
    )

    parser.add_argument(
        "--output",
        default=None,
        help="Output markdown file (default: output/result.md)",
    )

    args = parser.parse_args()

    scenarios_dir = args.scenarios_dir

    if args.methods:
        methods = args.methods
    else:
        methods = [
            f.replace(".json", "")
            for f in os.listdir(scenarios_dir)
            if f.endswith(".json")
        ]

    checker = BelievabilityChecker(output_dir=args.output or OUTPUT_DIR)

    results = checker.test_methods(methods, args.scenarios_dir)

    checker.create_bar_chart(results, methods)
    checker.create_line_chart(results, methods)

    markdown = checker.generate_markdown(results, "Believability Analysis")

    output_file = args.output or f"{OUTPUT_DIR}/result.md"

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)

    with open(output_file, "w") as f:
        f.write(markdown)

    print(f"Results saved to: {output_file}")


if __name__ == "__main__":
    main()
