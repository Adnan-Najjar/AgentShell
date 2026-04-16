from datetime import datetime
import logging
import os
import re

from openai import OpenAI
from pydantic import BaseModel

from utils import (
    MODEL,
    MODEL_NAME,
    BASE_URL,
    API_KEY,
    SYSTEM_PROMPT,
    HOSTNAME,
    USER,
    USER_DIR,
    CURR_DIR,
    LOG_DIR
)
from tools import Tools

logger = logging.getLogger("agent")
logger.setLevel(logging.INFO)
logger.handlers.clear()

file_handler = logging.FileHandler(
    f"{LOG_DIR}/agent_{datetime.now().strftime('%d_%H-%M')}.log"
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
    home: str
    hostname: str
    pwd: str
    is_root: bool
    command_output: str


class Agent:
    def __init__(self, model: str = MODEL_NAME) -> None:
        logger.info(f"Initializing Agent with {model}")

        self.tools = Tools(model)

        self.current_state = {
            "HOSTNAME": HOSTNAME,
            "USER": USER,
            "HOME": USER_DIR,
            "LOGNAME": USER,
            "PWD": CURR_DIR,
            "_": "/bin/bash",  # args of last command
            "?": "0",  # last command status
            "IS_ROOT": False,
        }
        self.total_tokens = 0

        self.shell_prompt = self._shell_prompt(self.current_state)
        logger.info(f"Agent initialized. Current dir: {self.current_state['PWD']}")

    def _shell_prompt(self, state: dict) -> str:
        prompt = f"{state['USER']}@{state['HOSTNAME']}:{state['PWD']}{'#' if state['IS_ROOT'] else '$'} "
        return prompt.replace(state["HOME"], "~", 1)

    def _format_state(self) -> str:
        return f"""
Current state or environment variables in JSON:
{{
"user": "{self.current_state["USER"]}",
"home": "{self.current_state["HOME"]}",
"hostname": "{self.current_state["HOSTNAME"]}",
"pwd": "{self.current_state["PWD"]}",
"is_root": "{self.current_state["IS_ROOT"]}",
"command_output": "<your_output_here>"
}}
"""

    def _handle_llm(self, query: str, docs: str) -> str:
        full_query = f"{self._format_state()}\n\n{docs}\n\nUser Query: {query}"

        client = OpenAI(base_url=BASE_URL, api_key=API_KEY, timeout=None)

        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": full_query},
            ],
            temperature=0.1,
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
                "USER": structured_output.user,
                "HOME": structured_output.home,
                "HOSTNAME": structured_output.hostname,
                "PWD": structured_output.pwd,
                "IS_ROOT": structured_output.is_root,
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

        prompt = self.tools.handle_env_vars(query, self.current_state)

        parts = prompt.split(maxsplit=1)
        self.current_state["_"] = parts[1] if len(parts) > 1 else parts[0]

        command = parts[0]
        if command == "cd":
            output = self.tools.handle_cd(prompt, self.current_state)
        elif command == "export":
            output = self.tools.handle_export(prompt, self.current_state)
        elif command == "env":
            output = self.tools.handle_env(prompt, self.current_state)
        elif command == "apt" or command == "apt-get":
            output = self.tools.handle_apt(prompt)
        elif command == "pwd":
            output = self.current_state["PWD"]
            logger.info(f"pwd: {output}")
        elif command == "whoami":
            output = self.current_state["USER"]
            logger.info(f"whoami: {output}")
        elif command == "hostname":
            output = self.current_state["HOSTNAME"]
            logger.info(f"localhost: {output}")
        elif command == "history":
            output = self.tools.handle_history(prompt)
            logger.info(f"history: {output}")
        else:
            valid, error_msg = self.tools.validate_command(command)
            if not valid:
                output = error_msg
                logger.info(f"Invalid command: {command}")
            else:
                parsed: list = self.parse_command(query)
                docs = self.tools.get_docs(parsed)
                output = self._handle_llm(prompt, docs)

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
