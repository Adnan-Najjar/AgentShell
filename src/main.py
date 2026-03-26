import json
import os
import re

import openai

from utils import MODEL, SYSTEM_PROMPT, DEBIAN_PORT, run_cmd_ssh

KNOWLEDGE_BASE_PATH = "datasets/commands/control.json"
MAN_PAGES_CACHE = "datasets/man_pages.json"

client = openai.OpenAI(
    base_url="https://api.groq.com/openai/v1", api_key=os.environ.get("GROQ_API_KEY")
)

class ManPagesCache:
    def __init__(self, cache_path: str):
        self.cache_path = cache_path
        self.cache = {}
        if os.path.exists(cache_path):
            with open(cache_path, "r") as f:
                self.cache = json.load(f)

    def get_man_page(self, command: str) -> str | None:
        if command in self.cache:
            return self.cache[command]

        result = run_cmd_ssh(f"man -P cat {command}", DEBIAN_PORT)
        if result and result != "error" and "No manual entry for" not in result:
            self.cache[command] = result
            self._save()
            return result
        return None

    def _save(self):
        with open(self.cache_path, "w") as f:
            json.dump(self.cache, f, indent=2)


class SSHKnowledgeBase:
    def __init__(self, kb_path: str):
        self.commands = {}
        with open(kb_path, "r") as f:
            self.commands = json.load(f)

    def get_similar_commands(self, query: str, top_k: int = 3) -> list[tuple[str, str]]:
        query_lower = query.lower()
        matches = []

        for cmd, output in self.commands.items():
            cmd_lower = cmd.lower()
            score = 0

            if query_lower.strip() == cmd_lower.strip():
                score = 100
            elif query_lower.strip() in cmd_lower.strip() or cmd_lower.strip() in query_lower.strip():
                score = 50
            elif any(word in cmd_lower for word in query_lower.split() if len(word) > 2):
                score = 25

            if score > 0:
                matches.append((cmd, output, score))

        matches.sort(key=lambda x: x[2], reverse=True)
        return [(cmd, output) for cmd, output, _ in matches[:top_k]]


def extract_command_name(command: str) -> str | None:
    match = re.match(r"^\s*([a-zA-Z0-9_-]+)", command.strip())
    if match:
        return match.group(1)
    return None


class AI:
    def __init__(
        self,
        kb_path: str = KNOWLEDGE_BASE_PATH,
        man_cache_path: str = MAN_PAGES_CACHE,
    ):
        self.kb = SSHKnowledgeBase(kb_path)
        self.man_cache = ManPagesCache(man_cache_path)
        self.total_tokens = 0

    def chat(self, command: str) -> str:
        similar = self.kb.get_similar_commands(command, top_k=3)

        context_parts = []

        cmd_name = extract_command_name(command)
        if cmd_name:
            man_page = self.man_cache.get_man_page(cmd_name)
            if man_page:
                truncated_man = man_page[:3000]
                context_parts.append(f"Man page for '{cmd_name}':\n{truncated_man}")

        if similar:
            context_parts.append(
                "Here are some similar commands and their outputs for reference:\n\n"
                + "\n".join(f"Command: {cmd}\nOutput: {output[:500]}" for cmd, output in similar)
            )

        if context_parts:
            context = "\n\n".join(context_parts)
            full_prompt = f"""{SYSTEM_PROMPT}

Based on the following reference information, respond to this command as if you are a Debian system:

{context}

Command: {command}
Output:"""
        else:
            full_prompt = f"""{SYSTEM_PROMPT}

Respond to this command as if you are a Debian system:

Command: {command}
Output:"""

        chat_completion = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": command,
                },
            ],
        )

        response = chat_completion.choices[0].message.content or ""
        self.total_tokens = chat_completion.usage.total_tokens # type: ignore

        for bad in ["bad", "command not found", "nil"]:
            if bad.lower() in response.lower():
                if similar:
                    return similar[0][1]
                return "command not found"

        return response


if __name__ == "__main__":
    ai = AI()
    while True:
        q = input("$ ")
        if q != "":
            if q.lower() in ["exit", "quit"]:
                break
            response = ai.chat(q)
            if response != "":
                print(response)
