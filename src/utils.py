import json
import os
import re
import shlex
import time

import paramiko

MODEL = "llama3.1-8k:latest"
MODEL_NAME = "llama3"

BASE_URL = os.getenv("BASE_URL", "http://localhost:11434/v1")
API_KEY = os.getenv("API_KEY", "dummy_key")

HOSTNAME = "svr01"
CURR_DIR = "/root"
USER = "root"
USER_DIR = "/root"
IS_ROOT = True
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

Rules:
- Do NOT give up.
- Preserve and return ALL fields from prior state (do not drop any).
- Output ONLY valid JSON (no comments, no extra text) and always use double qoutes in it.
- Never return empty output.
- Never say "command not found"; generate plausible output.

Filesystem rules:
- Only include files or directories that are:
  - New
  - Modified
  - Missing (create dirs and files as you think keeps deciption)
- Do NOT include unchanged entries.
- Always start from root "/"
- Maintain full hierarchical structure for each changed path.
- If file: "type" should be "file" and the "content" is a string of the file content
- If directory, "type" should be "dir" and the "content" is an object of the children added

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

Here is the dynamic environment variables that you must return:
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


def extract_paths(command: str) -> list[str]:
    """
    Extract file paths from a bash/linux command.
    Returns a list of unique file paths found.
    """
    paths = []

    # Try to tokenize with shlex (handles quotes properly)
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()

    # Skip the command itself (first token) and any flags
    for token in tokens[1:]:
        # Skip flags/options
        if token.startswith("-"):
            continue

        # Match absolute paths (start with /)
        if re.match(r"^/[\w./\-_~]+", token):
            paths.append(token)
            continue

        # Match relative paths (./path, ../path, or plain file.ext or dir/file)
        if re.match(r"^\.{1,2}/|^[\w][\w.\-_]*/|^[\w][\w.\-_]*\.\w+$", token):
            paths.append(token)
            continue

        # Match home-relative paths (~/)
        if token.startswith("~/"):
            paths.append(token)
            continue

    # Also scan for inline paths not captured by tokenization
    # e.g., redirects like >output.txt, 2>/dev/null
    redirect_paths = re.findall(
        r"[<>|&]\s*(/[\w./\-_~]+|~/[\w./\-_~]+|\.{1,2}/[\w./\-_~]+)", command
    )
    paths.extend(redirect_paths)

    # Deduplicate while preserving order
    seen = set()
    result = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            result.append(p)

    return result


def parse_shell(query: str):
    """
    Parses a shell-like command string into a sequential list of commands and operators.
    Each command is a list of tokens; operators (|, ||, &&, ;) are preserved as strings.
    """

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
            result.append(token)  # operator
        else:
            current.append(token)  # command

    if current:
        result.append(current)

    return result


def extract_command_flags(query: str) -> dict:
    """
    Extract the command and its flags from a single command string
    Returns a dict with the command and flags
    """

    if not query.strip():
        return {}

    try:
        tokens = shlex.split(query)
    except ValueError:
        # Handle cases like: unclosed quotes
        # Fallback: take everything before the first unmatched quote
        try:
            partial = query.split('"')[0].split("'")[0]
            tokens = shlex.split(partial)
        except Exception:
            return {}

    if not tokens:
        return {}

    cmd_name = tokens[0]
    flags = []

    for token in tokens[1:]:
        if token.startswith("--"):
            flags.append(token)
        elif token.startswith("-") and len(token) > 1:
            # split combined flags like -la -> -l, -a
            flags.extend([f"-{c}" for c in token[1:]])

    return {
        "command": cmd_name,
        "flags": flags,
    }


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
