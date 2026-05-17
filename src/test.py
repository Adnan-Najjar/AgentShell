#!/usr/bin/env python3

import argparse
import json
import os
import sys

from believability import BelievabilityChecker, CommandsChecker
from main import Agent
from utils import COMMANDS, MODEL_NAME, RESULTS_DIR, SCENARIOS, TACTICS

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def generate_table_markdown(rows, methods, first_col_name="Category"):
    """Generate markdown table from rows."""
    md = f"| {first_col_name}"
    for method in methods:
        md += f" | {method}"
    md += " |\n"

    md += "|"
    for _ in range(len(methods) + 1):
        md += " --- |"
    md += "\n"

    for row in rows:
        md += "| " + " | ".join(row) + " |\n"

    return md


def generate_llm_commands():
    agent = Agent("commands")

    commands = json.load(open(f"{COMMANDS}.json", "r"))
    output_file = f"{RESULTS_DIR}/{MODEL_NAME}/commands.json"
    os.makedirs(f"{RESULTS_DIR}/{MODEL_NAME}", exist_ok=True)
    output = {}

    for i, command in enumerate(commands):
        response = agent.chat(command)
        output[command] = {response: agent.prompt_tokens}
        print(
            f"Command number: {i}, Command output: {response if response else '':.30}, Tokens {agent.prompt_tokens}"
        )

    with open(output_file, "w") as f:
        json.dump(output, f, indent=2)
    print(f"LLM commands saved to: {output_file}")


def generate_llm_scenarios():
    attack_scenarios: dict = json.load(open(f"{SCENARIOS}.json", "r"))
    output_file = f"{RESULTS_DIR}/{MODEL_NAME}/scenarios.json"
    os.makedirs(f"{RESULTS_DIR}/{MODEL_NAME}", exist_ok=True)
    output = {}

    for tactic in TACTICS:
        agent = Agent(tactic)
        tactic_commands = {}
        tactic_tokens = {}
        if tactic not in attack_scenarios:
            continue
        for step, command in attack_scenarios[tactic].items():
            response = agent.chat(command)
            tactic_commands[step] = response
            tactic_tokens[step] = agent.prompt_tokens
            print(
                f"Attack scenario {tactic} at step: {step}, Output: {response if response else '':.30}, Tokens: {agent.prompt_tokens}"
            )
        output[tactic] = tactic_commands
        output[tactic + "_tokens"] = tactic_tokens

    with open(output_file, "w") as f:
        json.dump(output, f, indent=2)
    print(f"LLM scenarios saved to: {output_file}")


def run_analyze(args, methods):
    commands_results = {}
    scenarios_results = {}

    if args.analyze in ("commands", "all"):
        commands_checker = CommandsChecker(output_dir=RESULTS_DIR)
        for method in methods:
            dir_path = f"{RESULTS_DIR}/{method}"
            if os.path.exists(f"{dir_path}/commands.json"):
                commands_results[method] = commands_checker.test_method(
                    method, dir_path
                )

        all_categories = set()
        for method in methods:
            if method in commands_results:
                categories = commands_results[method].get("_categories", {})
                all_categories.update(categories.keys())
        categories = sorted(all_categories)

        cmd_rows = []
        for cat in categories:
            row = [cat]
            for method in methods:
                if method in commands_results:
                    acc = (
                        commands_results[method]
                        .get("_categories", {})
                        .get(cat, {})
                        .get("accuracy", 0)
                    )
                    row.append(f"{acc:.0f}%")
                else:
                    row.append("0%")
            cmd_rows.append(row)

        tokens_row = ["**Tokens**"]
        for method in methods:
            if method in commands_results:
                tokens = commands_results[method].get("_tokens", 0)
                tokens_row.append(f"**{tokens}**")
            else:
                tokens_row.append("**0**")
        cmd_rows.append(tokens_row)

        overall_row = ["**Overall**"]
        for method in methods:
            if method in commands_results:
                overall = (
                    commands_results[method].get("_overall", {}).get("accuracy", 0)
                )
                overall_row.append(f"**{overall:.0f}%**")
            else:
                overall_row.append("**0%**")
        cmd_rows.append(overall_row)

        usage_row = ["**Tokens/1%**"]
        for method in methods:
            if method in commands_results:
                overall = (
                    commands_results[method].get("_overall", {}).get("accuracy", 0)
                )
                tokens = commands_results[method].get("_tokens", 0)
                if overall > 0:
                    ratio = tokens / overall
                    usage_row.append(f"**{ratio:.1f}**")
                else:
                    usage_row.append("**N/A**")
            else:
                usage_row.append("**N/A**")
        cmd_rows.append(usage_row)

        commands_table = generate_table_markdown(cmd_rows, methods)
    else:
        commands_table = ""

    tactics = [
        "system_reconnaissance",
        "scanning_lateral_propagation",
        "persistence",
        "data_reconnaissance_exfiltration",
        "data_obfuscation_ransomware",
    ]

    if args.analyze in ("scenarios", "all"):
        scenarios_checker = BelievabilityChecker(output_dir=RESULTS_DIR)
        for method in methods:
            dir_path = f"{RESULTS_DIR}/{method}"
            if os.path.exists(f"{dir_path}/scenarios.json"):
                scenarios_results[method] = scenarios_checker.test_method(
                    method, dir_path
                )
        del methods[1]
        del methods[0]
        scenarios_checker.create_bar_chart(scenarios_results, methods)
        scenarios_checker.create_line_chart(scenarios_results, methods)

        scn_rows = []
        for tactic in tactics:
            row = [tactic]
            for method in methods:
                if method in scenarios_results:
                    acc = scenarios_results[method].get(tactic, {}).get("accuracy", 0)
                    row.append(f"{acc:.0f}%")
                else:
                    row.append("0%")
            scn_rows.append(row)

        overall_row = ["**Overall**"]
        for method in methods:
            if method in scenarios_results:
                overall = (
                    scenarios_results[method].get("_overall", {}).get("accuracy", 0)
                )
                overall_row.append(f"**{overall:.0f}%**")
            else:
                overall_row.append("**0%**")
        scn_rows.append(overall_row)

        tokens_row = ["**Tokens**"]
        for method in methods:
            if method in scenarios_results:
                total = scenarios_results[method].get("_tokens", {}).get("_total", 0)
                tokens_row.append(f"**{total}**")
            else:
                tokens_row.append("**0**")
        scn_rows.append(tokens_row)

        usage_row = ["**Tokens/1%**"]
        for method in methods:
            if method in scenarios_results:
                overall = (
                    scenarios_results[method].get("_overall", {}).get("accuracy", 0)
                )
                tokens = scenarios_results[method].get("_tokens", {}).get("_total", 0)
                if overall > 0:
                    ratio = tokens / overall
                    usage_row.append(f"**{ratio:.1f}**")
                else:
                    usage_row.append("**N/A**")
            else:
                usage_row.append("**N/A**")
        scn_rows.append(usage_row)

        scenarios_table = generate_table_markdown(scn_rows, methods, "Scenario")
    else:
        scenarios_table = ""

    os.makedirs(RESULTS_DIR, exist_ok=True)
    output_file = f"{RESULTS_DIR}/results.md"

    with open(output_file, "w") as f:
        f.write("# Believability Analysis\n\n")

        if commands_table:
            f.write("## Commands\n\n")
            f.write(commands_table)

        if scenarios_table:
            f.write("\n## Scenarios\n\n")
            f.write(scenarios_table)
            f.write("\n## Bar Chart\n\n")
            f.write("![Believability Bar Chart](result_bar.png)\n\n")
            f.write("\n## Token usage per step line chart\n\n")
            for t in tactics:
                f.write(f"![](result_tokens_{t}.png)\n")

    print(f"Results saved to: {output_file}")


def main():
    parser = argparse.ArgumentParser(description="Believability Analysis Tool")

    parser.add_argument(
        "--methods",
        nargs="+",
        default=None,
        help="Methods to compare (default: all files in scenarios/commands dir)",
    )
    parser.add_argument(
        "--analyze",
        choices=["scenarios", "commands", "all"],
        default=None,
        help="Run believability analysis (scenarios, commands, or all)",
    )
    parser.add_argument(
        "--llm",
        choices=["scenarios", "commands", "all"],
        default=None,
        help="Generate LLM outputs (scenarios, commands, or all)",
    )

    args = parser.parse_args()

    if args.llm:
        if args.llm in ("commands", "all"):
            generate_llm_commands()
        if args.llm in ("scenarios", "all"):
            generate_llm_scenarios()
        return

    if not args.analyze:
        print("No action specified. Use --analyze or --llm.")
        parser.print_help()
        return

    if args.methods:
        methods = args.methods
    else:
        methods = []

    if not methods:
        output_methods = []
        if os.path.exists(RESULTS_DIR):
            for d in os.listdir(RESULTS_DIR):
                dir_path = f"{RESULTS_DIR}/{d}"
                if os.path.isdir(dir_path) and d != "results":
                    if os.path.exists(f"{dir_path}/commands.json") or os.path.exists(
                        f"{dir_path}/scenarios.json"
                    ):
                        output_methods.append(d)
        scenario_methods = [
            m
            for m in output_methods
            if os.path.exists(f"{RESULTS_DIR}/{m}/scenarios.json")
        ]
        command_methods = [
            m
            for m in output_methods
            if os.path.exists(f"{RESULTS_DIR}/{m}/commands.json")
        ]
        if args.analyze == "scenarios":
            methods = scenario_methods
        elif args.analyze == "commands":
            methods = command_methods
        else:
            methods = output_methods

    def sort_methods(methods):
        ordered = []
        if "control" in methods:
            ordered.append("control")
        if "cowrie" in methods:
            ordered.append("cowrie")
        for m in methods:
            if m not in ordered:
                ordered.append(m)
        return ordered

    methods = sort_methods(methods)

    run_analyze(args, methods)


if __name__ == "__main__":
    main()
