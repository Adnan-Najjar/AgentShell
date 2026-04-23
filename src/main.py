from datetime import datetime
import json
import logging
import pickle
import shlex

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
    extract_paths,
    parse_shell,
    extract_command_flags,
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

    def _parse_path(self, path) -> dict:
        logger.info(f"_parse_path: input path={path}")

        # Handle absolute vs relative
        if not path.startswith("/"):
            path = self.current_state["PWD"] + "/" + path

        # Normalize the path (handle . and ..)
        raw_parts = [p for p in path.split("/") if p]
        clean_parts = []
        for part in raw_parts:
            if part == "..":
                if clean_parts:
                    clean_parts.pop()
            elif part == ".":
                continue
            else:
                clean_parts.append(part)

        logger.info(f"_parse_path: normalized path={path}, parts={clean_parts}")

        # Traverse the filesystem
        current: dict = self.filesystem["/"]
        for part in clean_parts:
            if part not in current.get("content", {}):
                logger.warning(f"_parse_path: part not found={part}")
                raise FileNotFoundError(f"No such file or directory: {part}")

            current = current["content"][part]
            logger.info(
                f"_parse_path: traversed part={part}, type={current.get('type')}"
            )

            # Handle symlinks
            if current.get("type") == "symlink":
                target = current.get("target", {})
                logger.info(f"_parse_path: following symlink to={target}")
                current = self._parse_path(target)

        logger.info(f"_parse_path: returning {current}")
        return current

    def _create_path(self, full_path: str, entry: dict) -> None:
        """Create parent dirs and add entry."""
        parts = [p for p in full_path.split("/") if p]
        name = parts[-1]

        current = self.filesystem["/"]
        for part in parts[:-1]:
            if "content" not in current:
                current["content"] = {}
            if part not in current["content"]:
                current["content"][part] = {"type": "dir", "content": {}}
            current = current["content"][part]

        if "content" not in current:
            current["content"] = {}
        current["content"][name] = entry

    def save_to_fs(self, fs_changes: dict) -> None:
        """Save filesystem changes from LLM - merge with existing entries."""
        if not fs_changes:
            return

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
                parent = self._parse_path(parent_path)
                existing = parent["content"].get(name, {})

                if existing:
                    # Merge: existing + new (new overwrites)
                    if "content" in existing and "content" in entry:
                        existing["content"].update(entry.get("content", {}))
                    merged = {**existing, **entry}
                    parent["content"][name] = merged
                    logger.info(f"save_to_fs: merged {full_path}")
                else:
                    parent["content"][name] = entry
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

    def chat(self, query: str) -> str:
        logger.info(f"Query: {query}")

        output = ""
        last_id = self.tools.set_history(query)

        # Expand environment variables
        prompt = self.tools.handle_env_vars(query, self.current_state)

        # TODO: use parse_shell somehow
        try:
            tokens = shlex.split(prompt)
            command = tokens[0] if tokens else ""
        except:
            return "syntax error"

        # Get args of the last command
        self.current_state["_"] = " ".join(tokens[1:]) if len(tokens) > 1 else command

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
        elif command == "curl" or command == "wget":
            output = self.tools.handle_downloads(prompt)
        else:
            valid, error_msg = self.tools.validate_command(command)
            if not valid:
                output = error_msg
                logger.info(f"Invalid command: {command}")
            else:
                # Get info about the command
                parsed: dict = extract_command_flags(query)
                docs = self.tools.get_docs(parsed)

                # Get info about files/dirs in the command
                paths = extract_paths(prompt)
                dirs = "Directory listing for "
                if not paths:
                    path = self.current_state["PWD"]
                    dirs += f"{path} {self._parse_path(path)['content']}\n"
                else:
                    for path in paths:
                        dirs += f"{path}: {self._parse_path(path)['content']}\n"

                logger.info(f"Directory listing: {dirs}")
                prompt = (
                    f"{self._format_state()}\n\n{docs}\n{dirs}\nUser Query: {query}"
                )

                return self.chat_completion(prompt)

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
