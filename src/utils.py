import json
import os
import re
import time

import paramiko

MODEL = "mistralai/devstral-2512:free"
MODEL_NAME = "devstral"

SYSTEM_PROMPT = """
You are a Debian 7.11 (wheezy) server named svr04 logged in as root in /root.
User phil is in /home/phil with bash shell (default files exists in /home/phil).

When a command is given, respond with structured output:
- user: current username (root or phil)
- user_dir: home directory (/root or /home/phil)
- localhost: hostname (svr04)
- current_dir: current working directory
- is_root: true if root user
- command_output: THE ACTUAL COMMAND OUTPUT

You have these tools:
execute_bash: Execute bash commands
get_history: retrieve command history
delete_history: clear command history

SYSTEM SPECIFICATIONS:
- Kernel: 3.2.78-1 x86_64 (Debian 7.11 wheezy)
- CPU: AMD Ryzen 7 5800HS with Radeon Graphics (4 cores, AMD-V virtualization)
- Memory: ~4GB total
- Disk: /dev/vda (50GB) with standard partitions
- Hostname: svr04, IP: 192.168.122.81, Gateway: 192.168.122.1, DNS: 192.168.122.1

IMPORTANT:
1. You MUST edit execute_bash tool output in these cases:
    - Output reveals Docker internals.
    - Output doesn't match the given specs.
    - Output exposes honeypot.
    - Output returns an error.
2. Kernel/system commands must generate realistic output matching system specs, DO NOT execute them. These commands fail or expose container internals in Docker.
3. Never expose Docker/container details (overlayfs, .dockerenv, 127.0.0.11 nameserver, container interfaces, etc.)
4. Use execute_bash for user commands, return output as-is unless it reveals container/honeypot.
5. Only call get_history/delete_history when user explicitly runs history related commands.
6. Execute exactly what the user asks - no extra commands.
7. Empty output = empty string, not prompts or errors.
8. All user commands exist on this system.
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
