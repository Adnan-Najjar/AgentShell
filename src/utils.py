import json
import os
import re
import shlex
import time

import paramiko

MODEL = os.getenv("MODEL", "llama3.1:latest")
BASE_URL = os.getenv("BASE_URL", "http://localhost:11434/v1")
API_KEY = os.getenv("API_KEY", "dummy_key")

TIMEOUT = 240  # 4 minutes
MAX_VALIDATION_RETRIES = 3
MAX_SCHEMA_RETRIES = 0

MODEL_NAME = MODEL.replace(".", "-").split(":")[0]
if "/" in MODEL_NAME:
    MODEL_NAME = MODEL_NAME.split("/")[1]

HOSTNAME = "svr01"
CURR_DIR = "/root"
USER = "root"
USER_DIR = "/root"
IS_ROOT = True
IP = "172.18.0.20"
ENV_VARS = {
    "TERM": "linux",
    "HUSHLOGIN": "FALSE",
    "SHELL": "/bin/sh",
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "en_us.UTF-8",
    "SHLVL": "1",
    "0": "/bin/sh",
    "#": "0",
    "-": "himBH",
}

SYSTEM_PROMPT = f"""
You are a fully configured Debian 7 system. For each command, return the output of that command with the given state/environment.
these are the static environment variables:
{ENV_VARS}
Your IP is: {IP}

Rules:
- Do NOT give up.
- Preserve and return ALL fields from prior state (do not drop any).
- Output ONLY valid JSON (no comments, no extra text) and always use double qoutes in it.
- Never return empty output.
- Never say "command not found"; generate plausible output.

Filesystem rules:
- If no files are new, modified, or missing, return EMPTY "filesystem": {{}}.
- ONLY include NEW, MODIFIED, or MISSING entries, return empty "filesystem" otherwise.
- Maintain full hierarchical structure for each changed path.
- If file: "type" should be "file" and the "content" is a string of the file content.
- If directory, "type" should be "dir" and the "content" is an object of the children added.
- The command_output must be a string

Structure:
"filesystem": {{
    "<full_path>": {{
      "type": "<type>",
      "permissions": "<unix_permission_string>",
      "owner": "<owner>",
      "group": "<group>",
      "modified": "",
      "size": "<expected_size_in_MB>",
      "content": "<file content>"
    }}
}}
"""

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

UBUNTU_HOST = "172.18.0.20"
UBUNTU_PORT = "2220"
COWRIE_PORT = "2221"

TACTICS = [
    "system_reconnaissance",
    "scanning_lateral_propagation",
    "persistence",
    "data_reconnaissance_exfiltration",
    "data_obfuscation_ransomware",
]

METHODS = ["control", MODEL_NAME, "cowrie"]
COLORS = ["blue", "red", "green", "orange"]

OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

COMMANDS = "data/commands"
SCENARIOS = "data/scenarios"

LLM_COMMANDS = f"{OUTPUT_DIR}/{MODEL_NAME}/commands.json"
LLM_SCENARIOS = f"{OUTPUT_DIR}/{MODEL_NAME}/scenarios.json"

BAD_OUTPUTS = ["bad", "command not found", "No such file"]


def run_cmd_ssh(cmd: str, port: str, hostname="localhost") -> str:
    """
    Run a given command in SSH shell on the given port using Paramiko.
    Uses invoke_shell instead of exec_command to handle interactive commands
    Times out after 10 mins (to make sure it doesnt cut off any commands)
    """
    username = "user"
    password = "user"
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


def parse_shell(query: str) -> list[list[str]]:
    """
    Parses a shell-like command string into a sequential list of commands and operators.
    Each command is a list of tokens; operators (|, ||, &&, ;) are preserved as strings.
    """

    try:
        # Pre-process: add spaces around operators if missing
        for op in ["||", "&&", "|", ";"]:
            query = query.replace(op, f" {op} ")

        lexer = shlex.shlex(query, posix=True)
        lexer.whitespace_split = True
        lexer.commenters = ""

        result = []
        current = []

        for token in lexer:
            if token in {"|", "||", "&&", ";"}:
                if current:
                    result.append(current)
                    current = []
            else:
                current.append(token)  # command

        if current:
            result.append(current)
    except:
        return [[]]

    return result


def extract_command_flags(args: list) -> dict:
    """
    Extract flags from a list of args
    Returns a dict with empty command (to be set by caller) and flags split
    """

    if not args:
        return {"command": "", "flags": []}

    flags = []

    for token in args:
        if token.startswith("--"):
            flags.append(token)
        elif token.startswith("-") and len(token) > 1:
            flags.extend([f"-{c}" for c in token[1:]])

    return {
        "command": "",
        "flags": flags,
    }


def fix_json(text: str) -> str:
    """Try to fix malformed JSON with unescaped newlines in strings."""
    result = []
    in_string = False
    i = 0
    while i < len(text):
        char = text[i]
        if char == '"' and (i == 0 or text[i - 1] != "\\"):
            in_string = not in_string
            result.append(char)
        elif char == "\n" and in_string:
            result.append("\\n")
        elif char == "\\" and i + 1 < len(text):
            result.append(char)
            result.append(text[i + 1])
            i += 1
        else:
            result.append(char)
        i += 1
    fixed = "".join(result)

    # Extract JSON by brace matching
    first_brace = -1
    brace_count = 0
    for i, char in enumerate(fixed):
        if char == "{":
            if first_brace == -1:
                first_brace = i
            brace_count += 1
        elif char == "}":
            brace_count -= 1
            if brace_count == 0 and first_brace != -1:
                return fixed[first_brace : i + 1]

    return fixed


def extract_json(text: str) -> str:
    """Extract and repair JSON from LLM response using multiple strategies."""
    # Try brace matching first
    result = fix_json(text)
    try:
        json.loads(result)
        return result
    except json.JSONDecodeError:
        pass

    # Try just finding first { and last }
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        result = text[first_brace : last_brace + 1]
        try:
            json.loads(result)
            return result
        except json.JSONDecodeError:
            pass

    # Last resort: try to fix common issues and return what we have
    return text


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

    attack_scenarios: dict = json.load(open(f"{SCENARIOS}.json", "r"))
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
