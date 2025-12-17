from openai import OpenAI
import os
import re
from typing import List, Tuple, Optional

MODEL = "openai/gpt-4o-mini"
MODEL_NAME = "gpt-4o-mini"

SYSTEM_PROMPT = """
You are a fully configured Debian 7 system named
svr01 logged in as the root user in the /root directory
with all packages installed. When given a command,
respond with the output of that command. Send only
the command output. Do not send any additional notes
or comments under any circumstance.
Send nil if that command has no output."""

# Context management sets - Commands that affect future outputs
C0 = {
    "cd",
    "mkdir",
    "rmdir",
    "rm",
    "touch",
    "cp",
    "mv",
    "chmod",
    "chown",
    "ln",
    "mount",
    "umount",
    "echo",
    "tar",
    "gzip",
    "gpg",
    "dd",
    "useradd",
    "service",
    "nc",
    "ncat",
    "curl",
    "wget",
    "scp",
    "apt-get",
    "iptables",
    "sysctl",
    "ulimit",
    "fdisk",
    "usermod",
}
H0 = {"history", "!!", "!-1", "!-2"}  # Commands that require full input history
KILL_CMDS = {"exit", "shutdown", "reboot", "logout"}  # Commands that end session

# Initialize histories
C1 = []  # Session context history (QA pairs as dicts)
H1 = []  # Session global history (all inputs as dicts)
MAX_TOKENS = 4000  # 4k context limit (like the paper)

def reset_histories():
    """Reset session histories for testing or new sessions"""
    global C1, H1
    C1 = []
    H1 = []

def count_tokens(text: str) -> int:
    """Approximate token count: ~4 characters per token"""
    return len(text) // 4


def get_llm_response(question: str, useFEI=True) -> Tuple[Optional[str], int]:
    """FEI-enhanced LLM response with context management"""
    global C1, H1

    if len(question.strip()) < 1:
        return None, 0

    # Build messages
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if useFEI:
        # Check for kill commands
        if question.strip().split()[0] in KILL_CMDS:
            return None, 0

    # Choose appropriate context
    context = choose_context(C1, H1, question, useFEI)
    messages.extend(context)

    messages.append({"role": "user", "content": question})

    try:
        client = OpenAI(
            base_url="https://models.github.ai/inference",
            api_key=os.environ["OPENAI_API_KEY"],
            # base_url="https://api.routeway.ai/v1",
            # api_key=os.environ["ROUTEWAY_API_KEY"],
            # base_url="https://openrouter.ai/api/v1",
            # api_key=os.environ["OPENROUTER_API_KEY"],
        )
        response = client.chat.completions.create(messages=messages, seed=67, temperature=0, model=MODEL)  # type: ignore
        output = response.choices[0].message.content
        total_tokens = response.usage.total_tokens if response.usage else 0
        if output == "nil":
            return None, total_tokens
        if useFEI:
            # Sanitize output
            sanitized_output = sanitize(output) if output else output

            # Update context
            C1, H1 = update_context(C1, H1, question, sanitized_output)
            return sanitized_output, total_tokens
        else:
            # Update history (no sanitization)
            C1, H1 = update_context(C1, H1, question, output)
            return output, total_tokens

    except Exception as e:
        print(f"Error getting LLM response: {e}")
        return None, 0


# Algorithm 3: Choose Context
def choose_context(C1: List[dict], H1: List[dict], input: str, useFEI: bool = True) -> List[dict]:
    """Select context history or global history based on question type and token limits"""
    if not useFEI:
        # FEI=False: Always use full global history (H1), trimmed
        context = []
        tokens_used = count_tokens(SYSTEM_PROMPT) + count_tokens(input)
        token_limit = MAX_TOKENS * 0.8
        for msg in reversed(H1):
            msg_tokens = count_tokens(msg['content'])
            if tokens_used + msg_tokens > token_limit:
                break
            context.insert(0, msg)
            tokens_used += msg_tokens
        return context
    else:
        # FEI=True: Smart selection
        c1_str = str(C1)
        current_tokens = count_tokens(SYSTEM_PROMPT) + count_tokens(c1_str) + count_tokens(input)
        token_limit = MAX_TOKENS * 0.8
        # If question requires full history or context is too large, use global history
        if input in H0 or (current_tokens > token_limit):
            # Use last commands until token limit
            context = []
            tokens_used = count_tokens(SYSTEM_PROMPT) + count_tokens(input)
            for msg in reversed(H1):
                msg_tokens = count_tokens(msg['content'])
                if tokens_used + msg_tokens > token_limit:
                    break
                context.insert(0, msg)
                tokens_used += msg_tokens
            return context
        else:
            # Use context history
            context = []
            tokens_used = count_tokens(SYSTEM_PROMPT) + count_tokens(input)
            for msg in reversed(C1):
                msg_tokens = count_tokens(msg['content'])
                if tokens_used + msg_tokens > token_limit:
                    break
                context.insert(0, msg)
                tokens_used += msg_tokens
            return context


# Algorithm 4: Update Context
def update_context(
    C1: List[dict], H1: List[dict], question: str, answer: Optional[str]
) -> Tuple[List[dict], List[dict]]:
    """Update session context history and global history"""
    # Update global history
    H1.append({"role": "user", "content": question})
    if answer is not None:
        H1.append({"role": "assistant", "content": answer})
    # Trim H1 to fit within token limit
    while count_tokens(" ".join([msg['content'] for msg in H1])) > MAX_TOKENS:
        H1.pop(0)

    # Update context history if question affects future outputs
    cmd = question.split()[0] if question.split() else ""
    in_c0 = any(cmd in c for c in C0)
    if in_c0 and answer is not None:
        C1.append({"role": "user", "content": question})
        C1.append({"role": "assistant", "content": answer})
        # Trim C1 to fit within token limit
        while count_tokens(" ".join([msg['content'] for msg in C1])) > MAX_TOKENS:
            C1.pop(0)

    return C1, H1


# Algorithm 2: Sanitize output
def sanitize(output: str) -> str:
    """Remove AI-like phrases and unwanted content"""
    if not output:
        return output

    # Remove code block markers
    output = output.replace("```bash\n", "").replace("```", "").strip()

    # Remove common AI prefixes and explanatory phrases
    ai_phrases = [
        r"^As an AI.*?\n",
        r"^I am.*?\n",
        r"^The command.*?\n",
        r"^This will.*?\n",
        r"^Output:.*?\n",
        r"^Here is.*?\n",
        r"^The result.*?\n",
    ]
    for phrase in ai_phrases:
        output = re.sub(phrase, "", output, flags=re.IGNORECASE | re.MULTILINE)

    # Remove trailing notes or comments
    output = re.sub(r"\n.*?(note|comment|explanation|as an ai).*?$", "", output, flags=re.IGNORECASE | re.DOTALL)

    # Clean up extra whitespace
    output = re.sub(r'\n\s*\n', '\n', output.strip())

    if not output:
        return output

    return output
