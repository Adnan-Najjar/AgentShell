import logging
import os
import re

from ollama import chat
from pydantic import BaseModel

from tools import Tools
from utils import MODEL, SYSTEM_PROMPT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("agent")


class OutputStructure(BaseModel):
    user: str
    user_dir: str
    localhost: str
    current_dir: str
    is_root: bool
    command_output: str


class Agent:
    def __init__(self, thread_id: str = "thread") -> None:
        logger.info(f"Initializing Agent with thread_id={thread_id}")

        self.tools = Tools(thread_id)

        self.current_state = {
            "user": "root",
            "user_dir": "/root",
            "localhost": "svr04",
            "current_dir": "/root",
            "is_root": True,
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

    def _handle_llm(self, query: str) -> str:
        full_query = f"{self._format_state()}\nUser Query: {query}"

        response = chat(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": full_query},
            ],
            format=OutputStructure.model_json_schema(),
            options={"temperature": 0.1, "seed": 42},
        )

        self.total_tokens = (response.eval_count or 0) + (
            response.prompt_eval_count or 0
        )

        logger.info(f"Raw JSON: {response.message.content}")

        try:
            structured_output = OutputStructure.model_validate_json(
                response.message.content or ""
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
                if token.startswith("-"):
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
        elif command == "history":
            output = self._handle_history(query)
            logger.info(f"history: {output}")
        else:
            valid, error_msg = self.tools.validate_command(command)
            if not valid:
                output = error_msg
                logger.info(f"Invalid command: {command}")
            else:
                # parsed: list = self.parse_command(query)
                # TODO: RAG using parsed flages
                output = self._handle_llm(query)

        self.shell_prompt = self._shell_prompt(self.current_state)

        self.tools.update_history(last_id, output)

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
