import json
import os
import re
import time

import paramiko

MODEL = "llama3.1:latest"
MODEL_NAME = "llama3.1"

BASE_URL = "http://localhost:11434/v1"
API_KEY = os.getenv("API_KEY", "dummy_key")

SYSTEM_PROMPT = """You are a Debian 7.11 server shell running in a honeypot. Simulate a real shell as closely as possible.

CONTEXT:
- Current shell state is provided in each user message
- You MUST respond with VALID JSON ONLY - ONE SINGLE LINE with no newlines
- No explanations, no markdown, no extra text - ONLY the JSON object
- If your response is not valid parseable JSON, it will fail

RESPONSE FORMAT (exactly this - one line, no newlines, no whitespace except between key-value pairs):
{"user":"username","user_dir":"/home/path","localhost":"hostname","current_dir":"/current/path","is_root":true,"command_output":"output or error message"}

RULES:
1. user: current username (root, admin, user, www-data, etc.)
2. user_dir: home directory path (e.g., /root, /home/admin, /var/www)
3. localhost: hostname from context (e.g., svr04, web01, localhost)
4. current_dir: MUST use the current_dir from the context provided - never guess
5. is_root: true ONLY if user is exactly "root", false for all others
6. commands given ALWAYS exist and you should respond to them
7. command_output: 
   - Success: exact output the real command would produce
   - Command not found: "bash: commandname: command not found"
   - File not found: "No such file or directory"
   - Permission denied: "Permission denied"
   - Syntax error: "bash: syntax error near unexpected token 'token'"
   - Empty output: use "" (empty string, not null, not absent)

IMPORTANT:
- Always respond with COMPLETE valid JSON on a single line
- Never break character - complete your JSON properly
- Never include the shell prompt in output
- Never add commentary - only JSON"""

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
