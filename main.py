import ollama

SYSTEM_PROMPT = """
You are a fully configured Debian 7 system named
svr01 logged in as the root user in the /root directory
with all packages installed. When given a command,
respond with the output of that command. Send only
the command output. Do not send any additional notes
or comments under any circumstance. Send nil if that
command has no output"""

# Initialize chat history with system prompt
chat_history = [
    {"role": "system", "content": SYSTEM_PROMPT}
]

def get_llm_response(input: str) -> tuple[str | None, int]:
    if len(input) < 1:
        return None, 0
    
    # Add user message to history
    chat_history.append({"role": "user", "content": input})
    
    response = ollama.chat(
        model="qwen2.5-coder:0.5b",
        messages=chat_history,
        options={"temperature": 0}
    )
    
    if not response or not response.get("message"):
        return None, 0
    
    output = response["message"]["content"]
    if output == "nil":
        return None, 0
    
    # Add assistant response to history
    chat_history.append({"role": "assistant", "content": output})
    
    # Access token usage information from the response
    prompt_tokens = response.get('prompt_eval_count', 0)
    response_tokens = response.get('eval_count', 0)
    total_tokens = prompt_tokens + response_tokens
    
    return output, total_tokens

def clear_chat_history():
    """Reset chat history to only contain system prompt"""
    global chat_history
    chat_history = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]
