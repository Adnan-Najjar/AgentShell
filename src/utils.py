import json
import os
import re
import time

import paramiko

MODEL = "llama3.1:latest"
MODEL_NAME = "llama3.1"

SYSTEM_PROMPT = """You are a Debian 7.11 server shell running in a honeypot. Simulate a real shell as closely as possible.

CONTEXT:
- Current shell state is provided in each user message
- You must respond ONLY with JSON, no other text

RESPONSE FORMAT:
{
  "user": "current username",
  "user_dir": "home directory path",
  "localhost": "hostname",
  "current_dir": "current working directory",
  "is_root": true/false,
  "command_output": "exact command output"
}

SHELL BEHAVIOR RULES:
1. current_dir is tracked by the system - use the provided current_dir in your response
2. Track is_root based on username (root = true, others = false)
3. Simulate realistic Debian 7 output - no markdown, no explanations
4. Empty output = empty string
5. Errors = realistic error messages (e.g., "Permission denied", "No such file or directory")
6. If output reveals honeypot indicators, modify to look like genuine Debian 7.11
7. NEVER output the shell prompt (e.g., "root@svr04:~#" or "user@host:~$")
8. NEVER break character - always respond with valid JSON only
"""

DEBIAN_HOST = "192.168.122.81"
DEBIAN_PORT = "2220"

COWRIE_PORT = "2222"

TACTICS = [
    "system_reconnaissance",
    "scanning_lateral_propagation",
    "persistence",
    "data_reconnaissance_exfiltration",
    "data_obfuscation_ransomware",
]

METHODS = ["cowrie", f"{MODEL_NAME}"]
COLORS = ["yellow", "green", "purple"]

COMMANDS = "datasets/commands"
SCENARIOS = "datasets/scenarios"

LLM_COMMANDS = f"{COMMANDS}/{MODEL_NAME}.json"
LLM_SCENARIOS = f"{SCENARIOS}/{MODEL_NAME}.json"

OUTPUT_DIR = f"output/{MODEL_NAME}"
os.makedirs(OUTPUT_DIR, exist_ok=True)

BAD_OUTPUTS = ["bad", "command not found", "No such file"]


def run_cmd_ssh(cmd: str, port: str, hostname="localhost") -> str:
    """
    Run a given command in SSH shell on the given port using Paramiko.
    Uses invoke_shell instead of exec_command to handle interactive commands
    Times out after 10 mins (to make sure it doesnt cut off any commands)
    """
    username = "root"
    password = "password"
    ansi_escape = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

    try:
        # Create SSH client
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname,
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


def collect_commands(output_filename: str, port: str, hostname="localhost"):
    """
    Runs all commands in commands.json on the ssh server of the given port
    """
    commands = list(json.load(open(f"{COMMANDS}.json", "r")).keys())
    output = {}

    for command_count, command in enumerate(commands):
        result = run_cmd_ssh(command, port, hostname)
        output[command] = result
        print(
            f"Port: {port}, Command number: {command_count}, Command output: {output[command]:.30}"
        )

    with open(output_filename, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Commands output is in {output_filename}")


def collect_attack_scenarios(output_filename: str, port: str, hostname="localhost"):
    """
    Runs all commands in attack_scenarios.json on the ssh server of the given port
    """
    output = {}

    attack_scenarios: dict = json.load(open("datasets/attack_scenarios.json", "r"))
    for tactic in TACTICS:
        tactic_commands = {}
        for step, command in attack_scenarios[tactic].items():
            result = run_cmd_ssh(command, port, hostname).strip().strip("\n")
            tactic_commands[step] = result
            print(
                f"Attack scenario {tactic} at {step}, Output: {result:.30}, Port: {port}"
            )
        output[tactic] = tactic_commands

    with open(output_filename, "w") as f:
        json.dump(output, f, indent=2)
    print(f"Attack scenarios output is in {output_filename}")
