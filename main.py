import ollama
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
C1 = []  # Session context history (QA pairs that affect future outputs)
H1 = []  # Session global history (all inputs)
MAX_TOKENS = 4000  # 4k context limit (like the paper)

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
        context = choose_context(question)
        messages.extend(context)

    messages.append({"role": "user", "content": question})

    try:
        if "openai" in MODEL:
            from openai import OpenAI
            import os

            client = OpenAI(
                base_url="https://models.github.ai/inference",
                api_key=os.environ["OPENAI_API_KEY"],
            )
            response = client.chat.completions.create(messages=messages, seed=67, temperature=0, model=MODEL)  # type: ignore
            output = response.choices[0].message.content
            total_tokens = response.usage.total_tokens if response.usage else 0
            if output == "nil":
                return None, total_tokens
        else:
            response = ollama.chat(
                model=MODEL, messages=messages, options={"temperature": 0}
            )

            if not response or not response.get("message"):
                return None, 0

            output = response["message"]["content"]

            # Calculate tokens
            prompt_tokens = response.get("prompt_eval_count", 0)
            response_tokens = response.get("eval_count", 0)
            total_tokens = prompt_tokens + response_tokens

            if output == "nil":
                return None, total_tokens
        if useFEI:
            # Sanitize output
            sanitized_output = sanitize(output) if output else output

            # Update context
            C1, H1 = update_context(question, sanitized_output, C1, H1)
            return sanitized_output, total_tokens
        else:
            return output, total_tokens

    except Exception as e:
        print(f"Error getting LLM response: {e}")
        return None, 0


# Algorithm 3: Choose Context
def choose_context(input: str) -> List[dict]:
    """Select context history or global history based on question type and token limits"""
    # Calculate current token usage
    c1_str = str(C1)
    current_tokens = count_tokens(SYSTEM_PROMPT) + count_tokens(c1_str) + count_tokens(input)
    token_limit = MAX_TOKENS * 0.8
    # If question requires full history or context is too large, use global history
    if input in H0 or (current_tokens > token_limit):
        # Use last commands until token limit
        context = []
        tokens_used = count_tokens(SYSTEM_PROMPT) + count_tokens(input)
        for q in reversed(H1):
            q_tokens = count_tokens(q)
            if tokens_used + q_tokens > token_limit:
                break
            context.insert(0, {"role": "user", "content": q})
            tokens_used += q_tokens
        return context
    else:
        # Use context history
        context = []
        tokens_used = count_tokens(SYSTEM_PROMPT) + count_tokens(input)
        for qa_pair in reversed(C1):
            pair_tokens = count_tokens(qa_pair[0]) + count_tokens(qa_pair[1])
            if tokens_used + pair_tokens > token_limit:
                break
            context.insert(0, {"role": "user", "content": qa_pair[0]})
            context.insert(1, {"role": "assistant", "content": qa_pair[1]})
            tokens_used += pair_tokens
        return context


# Algorithm 4: Update Context
def update_context(
    question: str, answer: Optional[str], C1: List, H1: List
) -> Tuple[List, List]:
    """Update session context history and global history"""
    # Update global history
    H1.append(question)
    # Trim H1 to fit within token limit
    while count_tokens(" ".join(H1)) > MAX_TOKENS:
        H1.pop(0)

    # Update context history if question affects future outputs
    cmd = question.split()[0] if question.split() else ""
    in_c0 = any(cmd in c for c in C0)
    if in_c0 and answer is not None:
        C1.append((question, answer))
        # Trim C1 to fit within token limit
        while count_tokens(str(C1)) > MAX_TOKENS:
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
