import ollama
import re

MODEL = "gemma3"
SYSTEM_PROMPT = """
You are a fully configured Debian 7 system named
svr01 logged in as the root user in the /root directory
with all packages installed. When given a command,
respond with the output of that command. Send only
the command output. Do not send any additional notes
or comments under any circumstance.
Send nil if that command has no output."""

# Context management sets
C0 = {'cd', 'mkdir', 'rmdir', 'rm', 'touch', 'cp', 'mv', 'chmod', 'chown', 'ln', 'mount', 'umount'}  # Commands that affect future outputs
H0 = {'history', '!!', '!-1', '!-2'}  # Commands that require full input history
KILL_CMDS = {'exit', 'shutdown', 'reboot', 'logout'}  # Commands that end session

# Initialize histories
C1 = []  # Session context history (QA pairs that affect future outputs)
H1 = []  # Session global history (all inputs)
MAX_TOKENS = 4000  # 4k context limit (like the paper)

def get_llm_response(question: str) -> tuple[str | None, int]:
    """FEI-enhanced LLM response with context management"""
    global C1, H1
    
    if len(question.strip()) < 1:
        return None, 0
    
    # Check for kill commands
    if question.strip().split()[0] in KILL_CMDS:
        return None, 0
    
    # Choose appropriate context
    context = choose_context(question)
    
    # Build messages
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]
    messages.extend(context)
    messages.append({"role": "user", "content": question})
    
    try:
        response = ollama.chat(
            model=MODEL,
            messages=messages,
            options={"temperature": 0}
        )
        
        if not response or not response.get("message"):
            return None, 0
        
        output = response["message"]["content"]
        if output == "nil":
            return None, 0
        
        # Sanitize output
        sanitized_output = sanitize(output)
        
        # Update context
        C1, H1 = update_context(question, sanitized_output, C1, H1)
        
        # Calculate tokens
        prompt_tokens = response.get('prompt_eval_count', 0)
        response_tokens = response.get('eval_count', 0)
        total_tokens = prompt_tokens + response_tokens
        
        return sanitized_output, total_tokens
        
    except Exception as e:
        print(f"Error getting LLM response: {e}")
        return None, 0

# Algorithm 3: Choose Context
def choose_context(input: str) -> list:
    """Select context history or global history based on question type and token limits"""
    # Calculate current token usage
    current_tokens = len(SYSTEM_PROMPT) + len(str(C1)) + len(input)
    token_limit = MAX_TOKENS * 0.8
    # If question requires full history or context is too large, use global history
    if input in H0 or (current_tokens > token_limit):
        return [{"role": "user", "content": q} for q in H1[-10:]]  # Last 10 commands
    else:
        # Use context history
        context = []
        for qa_pair in C1[-5:]:  # Last 5 context-changing QA pairs
            context.append({"role": "user", "content": qa_pair[0]})
            context.append({"role": "assistant", "content": qa_pair[1]})
        return context

# Algorithm 4: Update Context
def update_context(question: str, answer: str, C1: list, H1: list) -> tuple[list, list]:
    """Update session context history and global history"""
    # Update global history
    H1.append(question)
    if len(H1) > 50:  # Keep last 50 commands
        H1 = H1[-50:]
    
    # Update context history if question affects future outputs
    cmd = question.split()[0] if question.split() else ""
    in_c0 = any(cmd in c for c in C0)
    if in_c0:
        C1.append((question, answer))
        if len(C1) > 20:  # Keep last 20 context-changing QA pairs
            C1 = C1[-20:]
    
    return C1, H1

# Algorithm 2: Sanitize outpu
def sanitize(output: str) -> str:
    """Remove AI-like phrases and maintain deception"""
    if not output:
        return output
    
    output = re.sub(r"I.*", ' ', output).strip()
    
    if not output:
        return output 
    
    return output
