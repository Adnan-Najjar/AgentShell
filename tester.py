#!/usr/bin/env python3

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import json
from Levenshtein import ratio
from utils import *
from main import *


def generate_llm_commands(output_filename: str):
    agent = Agent("commands")
    output = {}
    tokens = 0

    commands = json.load(open(f"{COMMANDS}.json", "r"))
    for i, command in enumerate(commands):
        response, tokens = agent.chat(command)
        output[command] = response
        print(f"Command number: {i}, Command output: {response:.30}, Tokens {tokens}")
    output["tokens_used"] = tokens

    with open(output_filename, "w") as f:
        json.dump(output, f, indent=2)


def generate_llm_scenarios(output_filename: str):
    output = {}
    tokens = 0

    attack_scenarios: dict = json.load(open("datasets/attack_scenarios.json", "r"))
    for tactic in TACTICS:
        agent = Agent(tactic)
        tactic_commands = {}
        tactic_tokens = {}
        for step, command in attack_scenarios[tactic].items():
            result, tokens = agent.chat(command)
            tactic_commands[step] = result
            tactic_tokens[step] = tokens
            print(
                f"Attack scenario {tactic} at step: {step}, Output: {result:.30}, Tokens: {tokens}"
            )
        output[tactic] = tactic_commands
        output[tactic + "_tokens"] = tactic_tokens

    with open(output_filename, "w") as f:
        json.dump(output, f, indent=2)


def create_scenarios_bar_chart(completed_steps):
    """Create bar chart for MITRE ATT&CK scenarios"""
    # Setup plot
    _, ax = plt.subplots(figsize=(6, 10))
    x = list(range(len(TACTICS)))
    width = 0.25  # width of each bar

    colors = ["yellow", "green", "purple"]

    # Create bars for each method
    for i, method in enumerate(METHODS):
        x_positions = [xi + i * width - width / 2 for xi in x]
        values = [completed_steps[method][tactic] for tactic in TACTICS]
        ax.bar(x_positions, values, width, label=method, color=colors[i])

    # Formatting
    ax.set_ylabel("Attack Steps Completed")
    ax.set_xticks([xi + width / 2 for xi in x])  # Center ticks between bars
    ax.set_yticks(range(1, 10))
    ax.set_xticklabels(TACTICS, rotation=90, fontsize=10)
    ax.legend()

    plt.tight_layout()
    plt.savefig(f"{RESULTS_DIR}/bar_chart.png", dpi=300, bbox_inches="tight")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Honeypot Data Collection and Analysis Tool"
    )

    parser.add_argument("--analyze", action="store_true", help="Run analysis")

    parser.add_argument(
        "--cowrie",
        action="store_true",
        help="Collect all Cowrie data (commands + attack scenarios)",
    )
    parser.add_argument(
        "--cowrie-commands", action="store_true", help="Collect Cowrie commands data"
    )
    parser.add_argument(
        "--cowrie-scenarios",
        action="store_true",
        help="Collect Cowrie attack scenarios data",
    )

    parser.add_argument(
        "--control",
        action="store_true",
        help="Collect all control data (commands + attack scenarios)",
    )
    parser.add_argument(
        "--control-commands", action="store_true", help="Collect control commands data"
    )
    parser.add_argument(
        "--control-scenarios",
        action="store_true",
        help="Collect control attack scenarios data",
    )

    parser.add_argument(
        "--ubuntu",
        action="store_true",
        help="Collect all ubuntu data (commands + attack scenarios)",
    )
    parser.add_argument(
        "--ubuntu-commands", action="store_true", help="Collect ubuntu commands data"
    )
    parser.add_argument(
        "--ubuntu-scenarios",
        action="store_true",
        help="Collect ubuntu attack scenarios data",
    )

    parser.add_argument(
        "--llm",
        action="store_true",
        help="Generate all LLM data (commands + attack scenarios)",
    )
    parser.add_argument(
        "--llm-commands", action="store_true", help="Generate LLM commands data"
    )
    parser.add_argument(
        "--llm-scenarios",
        action="store_true",
        help="Generate LLM attack scenarios data",
    )

    args = parser.parse_args()

    # Handle specific data collection options
    if args.cowrie_commands or args.cowrie:
        print("Collecting Cowrie commands data...")
        collect_commands(f"{COMMANDS}/cowrie.json", COWRIE_PORT)
        print("Cowrie commands data collection completed.")

    if args.cowrie_scenarios or args.cowrie:
        print("Collecting Cowrie attack scenarios data...")
        collect_attack_scenarios(f"{SCENARIOS}/cowrie.json", COWRIE_PORT)
        print("Cowrie attack scenarios data collection completed.")

    if args.control_commands or args.control:
        print("Collecting control commands data...")
        collect_commands(f"{COMMANDS}/control.json", UBUNTU_PORT, UBUNTU_HOST)
        print("control commands data collection completed.")

    if args.control_scenarios or args.control:
        print("Collecting control attack scenarios data...")
        collect_attack_scenarios(f"{SCENARIOS}/control.json", UBUNTU_PORT, UBUNTU_HOST)
        print("control attack scenarios data collection completed.")

    if args.llm_commands or args.llm:
        print("=== GENERATING LLM COMMANDS DATA ===")
        generate_llm_commands(LLM_COMMANDS)

    if args.llm_scenarios or args.llm:
        print("=== GENERATING LLM MITRE ATTACK SCENARIOS ===")
        generate_llm_scenarios(LLM_SCENARIOS)

    if args.analyze:
        print("=== RUNNING ANALYSIS ===")

        # Create results directory if it doesn't exist
        import os

        os.makedirs(RESULTS_DIR, exist_ok=True)

        # Load commands output data
        commands = json.load(open(f"{COMMANDS}.json", "r"))
        llm = json.load(open(LLM_COMMANDS, "r"))
        control = json.load(open(f"{COMMANDS}/control.json", "r"))
        cowrie = json.load(open(f"{COMMANDS}/cowrie.json", "r"))

        # Calculate Levenshtein Ratio
        cowrie_system = []
        cowrie_filesystem = []
        cowrie_connectivity = []

        llm_system = []
        llm_filesystem = []
        llm_connectivity = []

        # Analyze commands
        for command, command_type in commands.items():
            if not llm[command]:
                continue

            cowrie_lev = ratio(cowrie[command], control[command])
            llm_lev = ratio(llm[command], control[command])

            if command_type == "filesystem":
                cowrie_filesystem.append(cowrie_lev)
                llm_filesystem.append(llm_lev)
            elif command_type == "system":
                cowrie_system.append(cowrie_lev)
                llm_system.append(llm_lev)
            elif command_type == "connectivity":
                cowrie_connectivity.append(cowrie_lev)
                llm_connectivity.append(llm_lev)

        plt.figure(figsize=(10, 8))
        plt.scatter(
            cowrie_filesystem, llm_filesystem, c="purple", label="Filesystem", alpha=0.7
        )
        plt.scatter(cowrie_system, llm_system, c="orange", label="System", alpha=0.7)
        plt.scatter(
            cowrie_connectivity,
            llm_connectivity,
            c="green",
            label="Connectivity",
            alpha=0.7,
        )

        plt.xlabel("Cowrie L-Ratio")
        plt.ylabel("LLM L-Ratio")
        plt.title("Command Similarity: Cowrie vs LLM")
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.plot(
            [0, 1], [0, 1], "k--", alpha=0.5
        )  # Diagonal line for perfect correlation
        plt.tight_layout()

        # Save the plot
        plt.savefig(f"{RESULTS_DIR}/similarity_plot.png", dpi=300, bbox_inches="tight")

        def average(lst):
            return sum(lst) / len(lst) if lst else 0

        cowrie_avg = average(cowrie_system + cowrie_filesystem + cowrie_connectivity)
        llm_avg = average(llm_system + llm_filesystem + llm_connectivity)

        # Create scenario bar chart
        steps_data = {method: {tactic: 0 for tactic in TACTICS} for method in METHODS}

        for i, method in enumerate(METHODS):
            attack_scenarios = json.load(open(f"{SCENARIOS}/{method}.json", "r"))
            for tactic in TACTICS:
                completed_steps = 0
                for step in range(1, 10):
                    command_output = attack_scenarios[tactic][f"step {step}"]
                    for bad in BAD_OUTPUTS:
                        if command_output:
                            if bad in command_output:
                                break
                    else:
                        completed_steps += 1
                steps_data[method][tactic] = completed_steps
        create_scenarios_bar_chart(steps_data)

        markdown_content = f"""# Command Similarity Analysis
## Scatter Plot

![Command Similarity Scatter Plot](similarity_plot.png)

## Results Table

| L-ratio | Cowrie | LLM |
|---------|--------|-----|
| Average | {cowrie_avg:.3f} | {llm_avg:.3f} |
| System Average | {average(cowrie_system):.3f} | {average(llm_system):.3f} |
| Filesystem Average | {average(cowrie_filesystem):.3f} | {average(llm_filesystem):.3f} |
| Connectivity Average | {average(cowrie_connectivity):.3f} | {average(llm_connectivity):.3f} |

## Bar Chart

![MITRE ATTACK Bar Chart](bar_chart.png)
        """

        # Save to results.md
        with open(f"{RESULTS_DIR}/results.md", "w") as f:
            f.write(markdown_content)

        print("Analysis completed. Results saved in output directory.")
