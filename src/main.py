from datetime import datetime
import json
import logging
import re

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from utils import (
    MODEL,
    MODEL_NAME,
    BASE_URL,
    API_KEY,
    SYSTEM_PROMPT,
    HOSTNAME,
    USER,
    IS_ROOT,
    USER_DIR,
    CURR_DIR,
    LOG_DIR,
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
    filesystem: dict
    command_output: str


class Agent:
    def __init__(self, model: str = MODEL_NAME) -> None:
        logger.info(f"Initializing Agent with {model}")

        self.client = OpenAI(base_url=BASE_URL, api_key=API_KEY, timeout=None)

        self.tools = Tools(model)

        self.current_state = {
            "HOSTNAME": HOSTNAME,
            "USER": USER,
            "HOME": USER_DIR,
            "LOGNAME": USER,
            "PWD": CURR_DIR,
            "_": "/bin/sh",  # args of last command
            "?": "0",  # last command status
            "IS_ROOT": IS_ROOT,
            "filesystem": {},
        }
        self.total_tokens = 0

        self.shell_prompt = self._shell_prompt(self.current_state)
        logger.info(f"Agent initialized. Current dir: {self.current_state['PWD']}")

    def _shell_prompt(self, state: dict) -> str:
        prompt = f"{state['USER']}@{state['HOSTNAME']}:{state['PWD']}{'#' if state['IS_ROOT'] else '$'} "
        return prompt.replace(state["HOME"], "~", 1)

    def _format_state(self) -> str:
        return f"""
Dynamic environment variables in JSON (you must return all of them):
{{
"user": "{self.current_state["USER"]}",
"home": "{self.current_state["HOME"]}",
"hostname": "{self.current_state["HOSTNAME"]}",
"pwd": "{self.current_state["PWD"]}",
"is_root": "{self.current_state["IS_ROOT"]}",
"filesystem": {self.current_state["filesystem"]},
"command_output": "<your_output_here>"
}}
"""

    def _chat_completion(self, prompt: str):
        max_retries = 3
        retry_info = ""

        for attempt in range(max_retries):
            full_prompt = f"{prompt}{retry_info}"
            logger.info(
                f"LLM: attempt {attempt + 1}/{max_retries}, prompt length: {len(full_prompt)}"
            )

            try:
                completion = self.client.chat.completions.create(
                    model=MODEL,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": full_prompt},
                    ],
                    temperature=0.1,
                )

                content = completion.choices[0].message.content
                if not content:
                    raise ValueError("Empty response from LLM")

                logger.info(
                    f"LLM: raw response ({len(content)} chars): {content[:1000]}"
                )

                data = json.loads(content)
                logger.info(f"LLM: parsed JSON: {json.dumps(data)[:1000]}")

                self.total_tokens = (
                    completion.usage.total_tokens if completion.usage else 0
                )

                return OutputStructure(**data)

            except json.JSONDecodeError as e:
                logger.warning(f"LLM: attempt {attempt + 1} failed (JSON): {e}")
                retry_info = (
                    f"\n\nInvalid JSON: {e}. ONLY return valid JSON with all fields."
                )

            except ValidationError as e:
                logger.warning(f"LLM: attempt {attempt + 1} failed (Pydantic): {e}")
                retry_info = f"\n\nMissing/invalid fields: {e}. Provide: user, home, hostname, pwd, is_root, filesystem, command_output."

        raise Exception(f"LLM failed after {max_retries} retries")

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
        elif command == "curl" or command == "wget":
            output = self.tools.handle_downloads(prompt)
        else:
            valid, error_msg = self.tools.validate_command(command)
            if not valid:
                output = error_msg
                logger.info(f"Invalid command: {command}")
            else:
                parsed: list = self.parse_command(query)
                docs = self.tools.get_docs(parsed)
                prompt = f"{self._format_state()}\n\n{docs}\n\nUser Query: {query}"

                try:
                    structured_output = self._chat_completion(prompt)
                except Exception as e:
                    logger.error(f"LLM error: {e}")
                    return ""

                logger.info(f"State update: {structured_output.model_dump()}")

                self.current_state = {
                    "USER": structured_output.user,
                    "HOME": structured_output.home,
                    "HOSTNAME": structured_output.hostname,
                    "PWD": structured_output.pwd,
                    "IS_ROOT": structured_output.is_root,
                    "filesystem": structured_output.filesystem,
                }

                return structured_output.command_output

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
