#!/usr/bin/env python3

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import json
import time
import paramiko
import re
from main import *
from Levenshtein import ratio

DEBIAN_PORT = "2220"
COWRIE_PORT = "2222"

TACTICS = [
    "system_reconnaissance",
    "scanning_lateral_propagation",
    "persistence",
    "data_reconnaissance_exfiltration",
    "data_obfuscation_ransomware",
]

COMMANDS = "datasets/commands"
SCENARIOS = "datasets/scenarios"
RESULTS_DIR = f"output/{MODEL_NAME}"

BAD_OUTPUTS = ["bad", "command not found", "No such file"]
# ============================================================================
# DATA COLLECTION
# ============================================================================


def run_cmd_ssh(cmd: str, port: str) -> str:
    """
    Run a given command in SSH shell on the given port using Paramiko.
    Uses invoke_shell instead of exec_command to handle interactive commands
    Times out after 10 mins (to make sure it doesnt cut off any commands)
    """
    host = "localhost"
    username = "root"
    password = "password"
    ansi_escape = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    print(f"Running: {cmd}")

    try:
        # Create SSH client
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            host,
            port=int(port),
            username=username,
            password=password,
            look_for_keys=False,
            allow_agent=False,
        )

        # Open an interactive shell
        channel = client.invoke_shell()

        # Send the command
        channel.send(cmd.encode())
        channel.send(b"\n")

        output = ""
        time.sleep(0.5)
        start_time = time.time()

        while True:
            if channel.recv_ready():
                chunk = channel.recv(65535).decode("utf-8", errors="ignore")
                output += ansi_escape.sub("", chunk)
                if re.search(r"[$#]", output.strip().splitlines()[-1]):
                    break
            if time.time() - start_time > 600:
                break
            time.sleep(0.1)

        output = output.split(cmd)
        if len(output) == 1:
          output = ""
        else:
          output = output[-1]
        output = re.sub(r".*[#$]", "", output)

        # Close channel and client explicitly
        channel.close()
        client.close()

        return output.strip()
    except Exception as e:
        print(f"SSH connection error: {e}")
        return "error"


def collect_commands(output_filename: str, port: str):
    """
    Runs all commands in commands.json on the ssh server of the given port
    """
    commands = list(json.load(open("datasets/commands.json", "r")).keys())
    output = {}

    for command_count, command in enumerate(commands):
        result = run_cmd_ssh(command, port)
        output[command] = result
        print(
            f"Port: {port}, Command number: {command_count}, Command output: {output[command]}"
        )

    with open(output_filename, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Commands output is in {output_filename}")


def collect_attack_scenarios(output_filename: str, port: str):
    """
    Runs all commands in attack_scenarios.json on the ssh server of the given port
    """
    output = {}

    attack_scenarios: dict = json.load(open("datasets/attack_scenarios.json", "r"))
    for tactic in TACTICS:
        tactic_commands = {}
        for step, command in attack_scenarios[tactic].items():
            result = run_cmd_ssh(command, port).strip().strip("\n")
            tactic_commands[step] = result
            print(
                f"Attack scenario {tactic} at {step}, Output: {result[:30]}, Port: {port}"
            )
        output[tactic] = tactic_commands

    with open(output_filename, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Attack scenarios output is in {output_filename}")


# ============================================================================
# LLM DATA GENERATION
# ============================================================================


def generate_llm_commands(output_filename: str, useFEI=True):
    reset_histories()  # Reset history for each generation run
    output = {}
    tokens = 0

    commands = json.load(open("datasets/commands.json", "r"))
    total_tokens = 0
    for i, command in enumerate(commands):
        response, tokens = get_llm_response(command, useFEI)
        total_tokens += tokens
        output[command] = response
        print(f"Command number: {i}, Command output: {response}, Tokens {tokens}")
    output["last_tokens_used"] = tokens
    output["total_tokens_used"] = total_tokens

    with open(output_filename, "w") as f:
        json.dump(output, f, indent=2)


def generate_llm_scenarios(output_filename: str, useFEI=True):
    reset_histories()  # Reset history for each generation run
    output = {}
    tokens = 0

    attack_scenarios: dict = json.load(open("datasets/attack_scenarios.json", "r"))
    for tactic in TACTICS:
        tactic_commands = {}
        tactic_tokens = {}
        for step, command in attack_scenarios[tactic].items():
            result, tokens = get_llm_response(command, useFEI)
            tactic_commands[step] = result
            tactic_tokens[step] = tokens
            print(
                f"Attack scenario {tactic} at step: {step}, Output: {result}, Tokens: {tokens}"
            )
        output[tactic] = tactic_commands
        output[tactic + "_tokens"] = tactic_tokens

    with open(output_filename, "w") as f:
        json.dump(output, f, indent=2)


# ============================================================================
# ANALYSIS FUNCTIONS
# ============================================================================


def create_similarity_plot(commands, llm, cowrie, control):
    """Create scatter plot comparing command similarities"""
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

    # Create scatter plot
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
    plt.plot([0, 1], [0, 1], "k--", alpha=0.5)  # Diagonal line for perfect correlation
    plt.tight_layout()

    # Save the plot
    plt.savefig(f"{RESULTS_DIR}/similarity_plot.png", dpi=300, bbox_inches="tight")

    return {
        "cowrie_system": cowrie_system,
        "cowrie_filesystem": cowrie_filesystem,
        "cowrie_connectivity": cowrie_connectivity,
        "llm_system": llm_system,
        "llm_filesystem": llm_filesystem,
        "llm_connectivity": llm_connectivity,
    }


def create_scenarios_bar_chart():
    """Create bar chart for MITRE ATT&CK scenarios"""
    # Setup plot
    _, ax = plt.subplots(figsize=(6, 10))
    x = list(range(len(TACTICS)))
    width = 0.25  # width of each bar

    methods = ["cowrie", f"fei+{MODEL_NAME}", f"{MODEL_NAME}"]
    colors = ["yellow", "green", "purple"]

    # Calculate all data first
    steps_data = {method: {tactic: 0 for tactic in TACTICS} for method in methods}

    for i, method in enumerate(methods):
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

    # Create bars for each method
    for i, method in enumerate(methods):
        x_positions = [xi + i * width - width / 2 for xi in x]
        values = [steps_data[method][tactic] for tactic in TACTICS]
        ax.bar(x_positions, values, width, label=method, color=colors[i])

    # Formatting
    ax.set_ylabel("Attack Steps Completed")
    ax.set_xticks([xi + width / 2 for xi in x])  # Center ticks between bars
    ax.set_yticks(range(1, 10))
    ax.set_xticklabels(TACTICS, rotation=90, fontsize=10)
    ax.legend()

    plt.tight_layout()
    plt.savefig(f"{RESULTS_DIR}/bar_chart.png", dpi=300, bbox_inches="tight")


def create_scenarios_token_line_chart():
    steps = range(1, 10)

    attack_scenarios = json.load(open(f"{SCENARIOS}/{MODEL_NAME}.json", "r"))
    attack_scenarios_fei = json.load(open(f"{SCENARIOS}/fei+{MODEL_NAME}.json", "r"))
    for tactic in TACTICS:
        _, ax = plt.subplots(figsize=(6, 3))
        tokens_fei = []
        tokens = []
        for step in steps:
            step_token = attack_scenarios[tactic + "_tokens"][f"step {step}"]
            step_token_fei = attack_scenarios_fei[tactic + "_tokens"][f"step {step}"]
            tokens_fei.append(step_token_fei)
            tokens.append(step_token)

        ax.plot(steps, tokens, label="LLM")
        ax.plot(steps, tokens_fei, label="LLM+FEI")
        ax.set_ylim(0, 7000)
        ax.set_title(tactic)
        ax.set_xlabel("Step")
        ax.set_ylabel("Tokens")
        ax.legend()

        plt.tight_layout()
        plt.savefig(
            f"{RESULTS_DIR}/line_chart_{tactic}.png", dpi=300, bbox_inches="tight"
        )


def calculate_averages(data_dict):
    """Calculate averages for different command categories"""

    def average(lst):
        return sum(lst) / len(lst) if lst else 0

    cowrie_avg = average(
        data_dict["cowrie_system"]
        + data_dict["cowrie_filesystem"]
        + data_dict["cowrie_connectivity"]
    )
    llm_avg = average(
        data_dict["llm_system"]
        + data_dict["llm_filesystem"]
        + data_dict["llm_connectivity"]
    )

    return {
        "cowrie_avg": cowrie_avg,
        "llm_avg": llm_avg,
        "cowrie_system_avg": average(data_dict["cowrie_system"]),
        "llm_system_avg": average(data_dict["llm_system"]),
        "cowrie_filesystem_avg": average(data_dict["cowrie_filesystem"]),
        "llm_filesystem_avg": average(data_dict["llm_filesystem"]),
        "cowrie_connectivity_avg": average(data_dict["cowrie_connectivity"]),
        "llm_connectivity_avg": average(data_dict["llm_connectivity"]),
    }


def generate_markdown_report(commands, averages):
    """Generate markdown report with all results"""
    markdown_content = f"""# Command Similarity Analysis

## Scatter Plot

![Command Similarity Scatter Plot](similarity_plot.png)

## Results Table

| L-ratio | Cowrie | LLM |
|---------|--------|-----|
| Average | {averages['cowrie_avg']:.3f} | {averages['llm_avg']:.3f} |
| System Average | {averages['cowrie_system_avg']:.3f} | {averages['llm_system_avg']:.3f} |
| Filesystem Average | {averages['cowrie_filesystem_avg']:.3f} | {averages['llm_filesystem_avg']:.3f} |
| Connectivity Average | {averages['cowrie_connectivity_avg']:.3f} | {averages['llm_connectivity_avg']:.3f} |

## Summary

- Total commands analyzed: {len(commands)}
- System commands: {len(averages.get('cowrie_system', []))}
- Filesystem commands: {len(averages.get('cowrie_filesystem', []))}
- Connectivity commands: {len(averages.get('cowrie_connectivity', []))}

## Bar Chart

![MITRE ATTACK Bar Chart](bar_chart.png)

## Line Chart

"""

    for tactic in TACTICS:
        markdown_content += f"\n### {tactic.capitalize().replace("_"," ")}\n![{tactic} Line Chart](line_chart_{tactic}.png)\n\n"

    # Save to results.md
    with open(f"{RESULTS_DIR}/results.md", "w") as f:
        f.write(markdown_content)


# ============================================================================
# MAIN EXECUTION
# ============================================================================

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
        collect_commands(f"{COMMANDS}/control.json", DEBIAN_PORT)
        print("Control commands data collection completed.")

    if args.control_scenarios or args.control:
        print("Collecting Control attack scenarios data...")
        collect_attack_scenarios(f"{SCENARIOS}/control.json", DEBIAN_PORT)
        print("Control attack scenarios data collection completed.")

    if args.llm_commands or args.llm:
        print("=== GENERATING LLM COMMANDS DATA ===")
        generate_llm_commands(f"{COMMANDS}/fei+{MODEL_NAME}.json", True)
        generate_llm_commands(f"{COMMANDS}/{MODEL_NAME}.json", False)

    if args.llm_scenarios or args.llm:
        print("=== GENERATING LLM MITRE ATTACK SCENARIOS ===")
        generate_llm_scenarios(f"{SCENARIOS}/fei+{MODEL_NAME}.json", True)
        generate_llm_scenarios(f"{SCENARIOS}/{MODEL_NAME}.json", False)

    if args.analyze:
        print("=== RUNNING ANALYSIS ===")

        # Create results directory if it doesn't exist
        import os
        os.makedirs(RESULTS_DIR, exist_ok=True)

        # Load data
        commands = json.load(open("datasets/commands.json", "r"))
        llm_filename = f"datasets/commands/fei+{MODEL_NAME}.json"
        llm = json.load(open(llm_filename, "r"))
        control = json.load(open("datasets/commands/control.json", "r"))
        cowrie = json.load(open("datasets/commands/cowrie.json", "r"))

        # Create similarity plot
        similarity_data = create_similarity_plot(commands, llm, cowrie, control)

        # Calculate averages
        averages = calculate_averages(similarity_data)

        # Create scenario bar chart
        create_scenarios_bar_chart()

        # Create scenario token usage line chart
        create_scenarios_token_line_chart()

        # Generate report
        generate_markdown_report(commands, averages)

        print("Analysis completed. Results saved in output directory.")
