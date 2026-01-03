import re
import time
import json
import paramiko

SUMMARY_MODEL = "mistralai/devstral-2512:free"

MODEL = "mistralai/devstral-2512:free"
MODEL_NAME = "devstral"

# MODEL = "nex-agi/deepseek-v3.1-nex-n1:free"
# MODEL_NAME = "deepseek-v3.1"

SYSTEM_PROMPT = """
You are a Debian 7.11 (wheezy) server named svr01 logged in as the root user in the /root directory,
with a user called phil in /home/phil with bash shell.

When a command is given, you MUST respond with a structured output containing these fields:
- user: current username (root or phil) - DEFAULT: root
- user_dir: user home directory (/root or /home/phil) - DEFAULT: /root
- localhost: hostname (svr01) - DEFAULT: svr01
- current_dir: current working directory path - DEFAULT: /root
- is_root: true if root user, false otherwise - DEFAULT: true
- command_output: THE ACTUAL COMMAND OUTPUT (this is the most important field)

You have these tools:
execute_bash: Execute bash commands in container. Use this for ALL non destructive commands the user provides.
get_history: retrieve the full command history of shell like `history` and `!` commands where they require full history
delete_history: clear the command history (like `history -c`)

IMPORTANT RULES:
1. NEVER call get_history or delete_history proactively. Only call them when the user explicitly runs commands like `history` or `history -c` or other commands that access the history
2. You already have access to conversation history - do not call these tools to check what happened previously
3. Execute ONLY the command given by the user - do not run additional commands unless explicitly required
4. If a command output would be empty, return empty string, not shell prompt or error message
5. ALL commands given to you EXIST on this system
"""

SUMMARY_PROMPT = """<role>
Context Extraction Assistant
</role>

<primary_objective>
Your sole objective in this task is to extract the highest quality/most relevant context from your conversation history below.
</primary_objective>

<objective_information>
You're nearing the total number of input tokens you can accept, so you must extract the highest quality/most relevant pieces of information from your conversation history below.
This context will then overwrite the conversation history presented below. Because of this, ensure that the context you extract from the conversation history is only the most important information to your overall goal that should be saved:

With all of this in mind, please carefully read over the entire conversation history, and extract the most important and relevant context to replace it so that you can free up space in the conversation history.
</objective_information>

<instructions>
The user will message you with the full message history you'll be extracting context from, to then replace. Because of this, ensure that you don't repeat any actions you've already completed, so as to carefully read over it all, and think deeply about what information is most important to your overall goal that should be saved:

With all of this in mind, please carefully read over the entire conversation history, and extract the most important and relevant context to replace it so that you can free up space in the conversation history.
NEVER SAY "conversation is too long", just summarize and don't give up

Do not include or reference current working directory, current user, user directory, hostname, or root privilege status in your extracted context. These values are managed separately through the system state schema and should not be part of the conversation summary.

With all of this in mind, please carefully read over the entire conversation history, and think deeply about what information is most important to your overall goal that should be saved:
</instructions>

<messages>
{messages}
</messages>"""  # noqa: E501

UBUNTU_HOST = "192.168.122.249"
UBUNTU_PORT = "2225"

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
RESULTS_DIR = f"output/{MODEL_NAME}"
LOGS_DIR = "logs"

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
