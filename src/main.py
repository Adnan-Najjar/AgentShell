from datetime import datetime
import json
import logging
import pickle

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from tools import Tools
from utils import (
    API_KEY,
    BASE_URL,
    CURR_DIR,
    HOSTNAME,
    IS_ROOT,
    LOG_DIR,
    MODEL,
    MODEL_NAME,
    SYSTEM_PROMPT,
    USER,
    USER_DIR,
    extract_command_flags,
    parse_shell,
)

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

        with open("data/filesystem.pkl", "rb") as pklr:
            self.filesystem = pickle.load(pklr)

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
"filesystem": {{}},
"command_output": "<your_output_here>"
}}
"""

    def _create_path(self, full_path: str, entry: dict) -> None:
        """Create parent dirs and add entry."""
        parts = [p for p in full_path.split("/") if p]
        name = parts[-1]

        now = datetime.now()
        modified = now.strftime("%b %d %H:%M")

        current = self.filesystem["/"]
        for part in parts[:-1]:
            if "content" not in current:
                current["content"] = {}
            if part not in current["content"]:
                current["content"][part] = {
                    "type": "dir",
                    "content": {},
                    "modified": modified,
                }
            current = current["content"][part]

        if "content" not in current:
            current["content"] = {}
        entry["modified"] = modified
        current["content"][name] = entry

    def save_to_fs(self, fs_changes: dict) -> None:
        """Save filesystem changes from LLM - merge with existing entries."""
        if not fs_changes:
            return

        now = datetime.now()
        modified = now.strftime("%b %d %H:%M")
        logger.info(f"save_to_fs: processing {len(fs_changes)} changes")

        for full_path, entry in fs_changes.items():
            if full_path == "/":
                continue

            parts = [p for p in full_path.split("/") if p]
            if not parts:
                continue

            name = parts[-1]
            parent_path = "/" + "/".join(parts[:-1])

            try:
                parent = self.tools.parse_path(self.filesystem, parent_path)
                existing = parent["content"].get(name, {})

                if existing:
                    # Merge: existing + new (new overwrites)
                    if "content" in existing and "content" in entry:
                        existing["content"].update(entry.get("content", {}))
                    merged = {**existing, **entry}
                    parent["content"][name] = merged
                    parent["content"][name]["modified"] = modified
                    logger.info(f"save_to_fs: merged {full_path}")
                else:
                    parent["content"][name] = entry
                    parent["content"][name]["modified"] = modified
                    logger.info(f"save_to_fs: added {full_path}")
            except FileNotFoundError:
                self._create_path(full_path, entry)
                logger.info(f"save_to_fs: created and saved {full_path}")

    def chat_completion(self, prompt: str):
        max_retries = 3
        retry_info = ""
        logger.info(f"LLM: prompt given {prompt}")

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

                content = content.replace("```json", "", count=1).replace("```", "")

                logger.info(
                    f"LLM: raw response ({len(content)} chars): {content[:1000]}"
                )

                data = json.loads(content)
                logger.info(f"LLM: parsed JSON: {json.dumps(data)[:1000]}")

                self.total_tokens = (
                    completion.usage.total_tokens if completion.usage else 0
                )

                try:
                    structured_output = OutputStructure(**data)
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
                }

                self.save_to_fs(structured_output.filesystem)

                return structured_output.command_output

            except json.JSONDecodeError as e:
                logger.warning(f"LLM: attempt {attempt + 1} failed (JSON): {e}")
                retry_info = (
                    f"\n\nInvalid JSON: {e}. ONLY return valid JSON with all fields."
                )

            except ValidationError as e:
                logger.warning(f"LLM: attempt {attempt + 1} failed (Pydantic): {e}")
                retry_info = f"\n\nMissing/invalid fields: {e}. Provide: user, home, hostname, pwd, is_root, filesystem, command_output."

        raise Exception(f"LLM failed after {max_retries} retries")

    def handle_command(self, command: str, args: list) -> str:
        valid, error_msg = self.tools.validate_command(command)
        if not valid:
            logger.info(f"Invalid command: {command} with args {args}")
            return error_msg

        match command:
            case "cd":
                return self.tools.handle_cd(args, self.current_state, self.filesystem)

            case "export":
                return self.tools.handle_export(args, self.current_state)

            case "env":
                return self.tools.handle_env(args, self.current_state)

            case "apt" | "apt-get":
                return self.tools.handle_apt(args)

            case "pwd":
                return self.current_state["PWD"]

            case "whoami":
                return self.current_state["USER"]

            case "hostname":
                return self.current_state["HOSTNAME"]

            case "history":
                return self.tools.handle_history(args)

            case "curl":
                out = self.tools.handle_curl(args)
                if out:
                    return out
                else:
                    return ""

            case "wget":
                out = self.tools.handle_wget(args)
                if out:
                    return out
                else:
                    return ""

            case _:
                return ""

    def chat(self, query: str) -> str:
        logger.info(f"Query: {query}")

        output = ""
        last_id = self.tools.set_history(query)

        parsed_cmd: list[list[str]] = parse_shell(query)
        if not parsed_cmd:
            return "syntax error"

        # Get args of the last command
        self.current_state["_"] = parsed_cmd[-1][-1]

        # If it was only one command handle it
        handle_command_output = self.handle_command(parsed_cmd[0][0], parsed_cmd[0][1:])
        if len(parsed_cmd) < 2 and handle_command_output:
            return handle_command_output

        # if it was nested commands
        paths = set()
        cmd_flags = {}
        cmd_outputs = ""
        for token in parsed_cmd:
            command = token[0]
            args_raw = token[1:]

            # Expand environment variables
            args = self.tools.handle_env_vars(args_raw, self.current_state)

            # Extract paths from args
            for arg in args:
                if arg.startswith("/") or arg.startswith("./") or arg.startswith("../"):
                    paths.add(arg)
                elif arg and "/" in arg and not arg.startswith("-"):
                    paths.add(arg)

            # Extract command and flags
            cmd_flags = extract_command_flags(args)
            cmd_flags["command"] = command

            # ====  handled manually ====
            command_output = self.handle_command(command, args)
            if command_output:
                cmd_outputs += f"Output of {' '.join(token)} is {command_output}"

        # ====  handled by AI   ====
        # Get info about the command
        docs = self.tools.get_docs(cmd_flags)

        # Get info about files/dirs in the command
        dirs = "Directory listing for "
        if not paths:
            path = self.current_state["PWD"]
            dirs += f"{path} {self.tools.parse_path(self.filesystem, path).get('content', {})}\n"
        else:
            for path in paths:
                dirs += f"{path}: {self.tools.parse_path(self.filesystem, path).get('content', {})}\n"

        logger.info(f"Directory listing: {dirs}")
        prompt = f"{self._format_state()}\n\n{docs}\n{dirs}\n{cmd_outputs}\nUser Query: {query}"

        output = self.chat_completion(prompt)

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
