import re
import os
import time
import json
import paramiko

# ─── API config ───────────────────────────────────────────────────────────────
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
API_KEY = os.environ.get("GROQ_API_KEY", "")

# ─── Model config ───────────────────────────────────────────────────────────────
MODEL = "llama-3.1-8b-instant"
MODEL_NAME = "llama-3.1"
SYSTEM_PROMPT = """
You are a fully configured Debian 7 system named
svr01 logged in as the root user in the /root directory
with all packages installed. When given a command,
respond with the output of that command. Send only
the command output. Do not send any additional notes
or comments under any circumstance.
Send nil if that command has no output."""

RETRY_DELAYS = [3, 5, 10]  # seconds — silent retry on 429
MAX_TOKENS = 256
TEMPERATURE = 0.3

# ─── History Pruning parameters (Algorithm 1) ─────────────────────────────────
WINDOW_SIZE = 3
RELEVANCE_SCORE = 1

# ─── Command dependency graph ─────────────────────────────────────────────────
CMD_DEPS: dict[str, list[str]] = {
    "ls": ["cd", "find", "cat", "grep", "rm", "cp", "mv"],
    "cd": ["ls", "pwd", "cat", "mkdir"],
    "cat": ["grep", "wc", "head", "tail", "sort"],
    "mkdir": ["cd", "ls", "touch", "rm"],
    "useradd": ["passwd", "usermod", "id"],
    "grep": ["cat", "ls", "find"],
    "sudo": ["apt", "systemctl", "chmod", "useradd", "passwd"],
    "ps": ["kill", "grep"],
    "find": ["cat", "grep", "rm", "cp"],
    "ssh": ["scp", "curl"],
    "nmap": ["ping", "netstat", "ss", "curl"],
    "git": ["make", "gcc"],
    "chmod": ["ls", "find"],
    "wget": ["curl", "tar", "unzip"],
    "curl": ["wget", "ssh"],
}

# ─── Shell command whitelist (regex) ─────────────────────────────────────────
_SHELL_PATTERNS = [
    r"^ls(\s|$)",
    r"^pwd$",
    r"^cd(\s|$)",
    r"^cat(\s|$)",
    r"^echo(\s|$)",
    r"^mkdir(\s|$)",
    r"^rm(\s|$)",
    r"^cp(\s|$)",
    r"^mv(\s|$)",
    r"^touch(\s|$)",
    r"^grep(\s|$)",
    r"^find(\s|$)",
    r"^ps(\s|$)",
    r"^top$",
    r"^htop$",
    r"^df(\s|$)",
    r"^du(\s|$)",
    r"^chmod(\s|$)",
    r"^chown(\s|$)",
    r"^whoami$",
    r"^id$",
    r"^uname(\s|$)",
    r"^hostname$",
    r"^ifconfig(\s|$)",
    r"^ip(\s|$)",
    r"^ping(\s|$)",
    r"^netstat(\s|$)",
    r"^ss(\s|$)",
    r"^curl(\s|$)",
    r"^wget(\s|$)",
    r"^tar(\s|$)",
    r"^unzip(\s|$)",
    r"^gzip(\s|$)",
    r"^gunzip(\s|$)",
    r"^ssh(\s|$)",
    r"^scp(\s|$)",
    r"^nmap(\s|$)",
    r"^python(\s|$)",
    r"^python3(\s|$)",
    r"^perl(\s|$)",
    r"^ruby(\s|$)",
    r"^bash(\s|$)",
    r"^sh(\s|$)",
    r"^zsh(\s|$)",
    r"^env$",
    r"^export(\s|$)",
    r"^history$",
    r"^sudo(\s|$)",
    r"^apt(\s|$)",
    r"^apt-get(\s|$)",
    r"^yum(\s|$)",
    r"^dnf(\s|$)",
    r"^useradd(\s|$)",
    r"^usermod(\s|$)",
    r"^userdel(\s|$)",
    r"^passwd(\s|$)",
    r"^crontab(\s|$)",
    r"^systemctl(\s|$)",
    r"^service(\s|$)",
    r"^kill(\s|$)",
    r"^killall(\s|$)",
    r"^pkill(\s|$)",
    r"^which(\s|$)",
    r"^whereis(\s|$)",
    r"^man(\s|$)",
    r"^help$",
    r"^exit$",
    r"^clear$",
    r"^date$",
    r"^cal$",
    r"^wc(\s|$)",
    r"^head(\s|$)",
    r"^tail(\s|$)",
    r"^sort(\s|$)",
    r"^awk(\s|$)",
    r"^sed(\s|$)",
    r"^cut(\s|$)",
    r"^tr(\s|$)",
    r"^nc(\s|$)",
    r"^telnet(\s|$)",
    r"^ftp(\s|$)",
    r"^sftp(\s|$)",
    r"^git(\s|$)",
    r"^make(\s|$)",
    r"^gcc(\s|$)",
    r"^g\+\+(\s|$)",
    r"^vim(\s|$)",
    r"^nano(\s|$)",
    r"^less(\s|$)",
    r"^more(\s|$)",
    r"^mount(\s|$)",
    r"^umount(\s|$)",
    r"^fdisk(\s|$)",
    r"^iptables(\s|$)",
    r"^ufw(\s|$)",
    r"^/bin/",
    r"^/usr/",
    r"^/sbin/",
    r"^\./",
    r"^/",
    r"^[a-z0-9_-]+\.sh(\s|$)",
]
COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _SHELL_PATTERNS]

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
