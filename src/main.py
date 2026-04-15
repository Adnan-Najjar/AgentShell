from datetime import datetime
import logging
import os
import re

from openai import OpenAI
from pydantic import BaseModel

from utils import MODEL, MODEL_NAME, BASE_URL, API_KEY, SYSTEM_PROMPT
from tools import Tools

logger = logging.getLogger("agent")
logger.setLevel(logging.INFO)
logger.handlers.clear()

file_handler = logging.FileHandler(
    f"logs/agent_{datetime.now().strftime('%d_%H-%M')}.log"
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(
    logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
)
logger.addHandler(file_handler)


class OutputStructure(BaseModel):
    user: str
    user_dir: str
    localhost: str
    current_dir: str
    is_root: bool
    command_output: str


class Agent:
    def __init__(self, model: str = MODEL_NAME) -> None:
        logger.info(f"Initializing Agent with {model}")

        self.tools = Tools(model)
        self.conversation_history: list[dict] = []

        self.current_state = {
            "user": "user",
            "user_dir": "/home/user",
            "localhost": "ubuntu",
            "current_dir": "/home/user",
            "is_root": False,
        }
        self.total_tokens = 0

        self.shell_prompt = self._shell_prompt(self.current_state)
        logger.info(
            f"Agent initialized. Current dir: {self.current_state['current_dir']}"
        )

    def _shell_prompt(self, state: dict) -> str:
        prompt = f"{state['user']}@{state['localhost']}:{state['current_dir']}{'#' if state['is_root'] else '$'} "
        return prompt.replace(state["user_dir"], "~", 1)

    def _format_state(self) -> str:
        return f"""Current State:
- User: {self.current_state["user"]}
- Home: {self.current_state["user_dir"]}
- Hostname: {self.current_state["localhost"]}
- Current Directory: {self.current_state["current_dir"]}
- Is Root: {self.current_state["is_root"]}"""

    # Handle history deletion and retrieval
    def _handle_history(self, command: str) -> str:
        parts = command.split(maxsplit=1)
        if len(parts) > 1 and parts[1].startswith("-c"):
            self.tools.delete_history()
            return ""
        return self.tools.get_history()

    def _handle_cd(self, command: str) -> str:
        parts = command.split(maxsplit=1)
        target = parts[1].strip() if len(parts) > 1 else "~"

        current = self.current_state["current_dir"]
        user_home = self.current_state["user_dir"]

        # 1. Handle special shortcuts
        if target == "~":
            new_path = user_home
        elif target == "-":
            new_path = getattr(self, "_prev_dir", user_home)
        else:
            # 2. Resolve Path (Handles absolute, relative, and "..")
            # os.path.join handles the "/" vs "sub/dir" logic automatically
            raw_path = os.path.join(current, target)
            new_path = os.path.normpath(raw_path)

        # 3. Update state
        self._prev_dir = current
        self.current_state["current_dir"] = new_path
        logger.info(f"cd: {current} -> {new_path}")
        return ""

    def _format_history(self) -> str:
        if not self.conversation_history:
            return "No history yet."

        history_str = "Recent History (last 5 commands):\n"
        for i, entry in enumerate(self.conversation_history, 1):
            history_str += f"{i}. > {entry['query']}\n"
            history_str += f"output> {entry['output']}\n"
        return history_str

    def _handle_llm(self, query: str, docs: str) -> str:
        history_context = self._format_history()
        logger.info(f"History context: {history_context}...")
        full_query = f"{self._format_state()}\n{history_context}\n\n{docs}\n\nUser Query: {query}"

        client = OpenAI(base_url=BASE_URL, api_key=API_KEY)

        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": full_query},
            ],
            temperature=0.5,
            response_format={"type": "json_object"},
        )

        self.total_tokens = response.usage.total_tokens if response.usage else 0

        logger.info(f"Raw JSON: {response.choices[0].message.content}")

        try:
            structured_output = OutputStructure.model_validate_json(
                response.choices[0].message.content or ""
            )

            logger.info(f"State update: {structured_output.model_dump()}")

            self.current_state = {
                "user": structured_output.user,
                "user_dir": structured_output.user_dir,
                "localhost": structured_output.localhost,
                "current_dir": structured_output.current_dir,
                "is_root": structured_output.is_root,
            }

            logger.info(
                f"Output: {structured_output.command_output[:100]}{'...' if len(structured_output.command_output) > 100 else ''}"
            )

            return structured_output.command_output

        except Exception as e:
            logger.error(f"Failed to parse response: {e}")
            return ""

    def parse_command(self, query: str) -> list:
        # Split by shell operators: |, ||, &&, ;
        parts = re.split(r"\s*(?:\|{1,2}|&&|;)\s*", query)
        parsed_commands = []

        for raw_command in parts:
            if not raw_command.strip():
                continue

            tokens = raw_command.split()
            if not tokens:
                continue

            cmd_name = tokens[0]
            flags = []

            # Extract only flags, split combined flags
            # Example: "-la file" -> ["-l", "-a"]
            for token in tokens[1:]:
                if token.startswith("--"):
                    flags.append(token)
                elif token.startswith("-"):
                    flags.extend([f"-{c}" for c in token[1:]])

            parsed_commands.append(
                {
                    "command": cmd_name,
                    "flags": flags,
                }
            )

        return parsed_commands

    def chat(self, query: str) -> str:
        logger.info(f"Query: {query}")

        output = ""
        last_id = self.tools.set_history(query)

        command = query.split()[0]
        if command == "cd":
            output = self._handle_cd(query)
        elif command == "pwd":
            output = self.current_state["current_dir"]
            logger.info(f"pwd: {output}")
        elif command == "whoami":
            output = self.current_state["user"]
            logger.info(f"whoami: {output}")
        elif command == "hostname":
            output = self.current_state["localhost"]
            logger.info(f"localhost: {output}")
        elif command == "history":
            output = self._handle_history(query)
            logger.info(f"history: {output}")
        else:
            valid, error_msg = self.tools.validate_command(command)
            if not valid:
                output = error_msg
                logger.info(f"Invalid command: {command}")
            else:
                parsed: list = self.parse_command(query)
                docs = self.tools.get_docs(parsed)
                output = self._handle_llm(query, docs)

        self.shell_prompt = self._shell_prompt(self.current_state)

        self.tools.update_history(last_id, output)

        self.conversation_history.append({"query": query, "output": output})
        if len(self.conversation_history) > 5:
            self.conversation_history = self.conversation_history[-5:]

        return output


if __name__ == "__main__":
    logger.info("Starting Agent shell")
    agent = Agent()
    while True:
        q = input(agent.shell_prompt)
        if q != "":
            response = agent.chat(q)
            if response != "":
                print(response)
            logger.info(f"Prompt updated: {agent.shell_prompt}")
