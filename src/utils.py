import json
import os
import re
import time

import paramiko

MODEL = "llama3.1:latest"
MODEL_NAME = "llama3_1"

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

Filesystem rules:
- Track only relevant files/directories.
- ALWAYS store in "filesystem" using full `ls -l` metadata (permissions, links, owner, group, size, date, name) so it can be updated and modified by future commands.
- If `ls` is used without `-l`, output simple names, but still store in "filesystem" as `ls -l` format.
- If listing a directory (e.g., `ls /bin`), include only that directory.
- If accessing/creating a file (e.g., `cat /root/test.txt`), include only that file.

Examples:
> ls /bin
{{
  ...,
  "command_output": "ls...",
  "filesystem": {{
    "/": {{ 
      "bin": {{ 
        "-rwxr-xr-x 1 root root 142312 Jan 23 13:30 ls": "",
      }}
    }}
  }}
}}
> chown -x /bin/ls && ls -l /bin
{{
  ...,
  "command_output": "-rw-r--r-- 1 root root 142312 Jan 23 13:30 ls\n...",
  "filesystem": {{
    "/": {{ 
      "bin": {{ 
        "-rw-r--r-- 1 root root 142312 Jan 23 13:30 ls": "" 
      }}
    }}
  }}
}}

> cat /root/test.txt
{{
  ...,
  "command_output": "Hello, World?",
  "filesystem": {{
    "/": {{ 
      "bin": {{ 
        "-rw-r--r-- 1 root root 142312 Jan 23 13:30 ls": "" 
      }}
      "root": {{
        "-rw-r--r-- 1 root root 14 Apr 20 06:15 test.txt": "Hello, World?"
      }}
    }}
  }}
}}

Rules:
- You will start with {{..., "filesystem": {{}}}}
- Preserve and return ALL fields from prior state (do not drop any).
- Output ONLY valid JSON (no comments, no extra text).
- Never return empty output.
- Never say "command not found"; generate plausible output.

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
