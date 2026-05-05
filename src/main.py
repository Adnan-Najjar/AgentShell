from datetime import datetime
import json
import os
import pickle

from openai import APITimeoutError, RateLimitError, OpenAI
from pydantic import BaseModel, ValidationError

from tools import Tools
from utils import (
    API_KEY,
    BASE_URL,
    CURR_DIR,
    HOSTNAME,
    IS_ROOT,
    LOG_DIR,
    MAX_SCHEMA_RETRIES,
    MAX_VALIDATION_RETRIES,
    MODEL,
    FALLBACK_BASE_URL,
    FALLBACK_MODEL,
    FALLBACK_API_KEY,
    SYSTEM_PROMPT,
    TIMEOUT,
    USER,
    USER_DIR,
    extract_command_flags,
    extract_json,
    fix_json,
    log,
    parse_shell,
)


class OutputStructure(BaseModel):
    user: str
    home: str
    hostname: str
    pwd: str
    is_root: bool
    filesystem: dict
    command_output: str


class Agent:
    def __init__(self, id="127.0.0.1") -> None:
        log.info(f"Initializing Agent")

        self.output = id.replace(".", "_")

        self.client = OpenAI(
            base_url=BASE_URL,
            api_key=API_KEY,
            timeout=TIMEOUT,
            max_retries=MAX_SCHEMA_RETRIES,
        )

        self.current_model = MODEL

        self.tools = Tools(id)

        session_fs_path = f"{LOG_DIR}/{self.output}_filesystem.pkl"
        if os.path.exists(session_fs_path):
            with open(session_fs_path, "rb") as pklr:
                self.filesystem = pickle.load(pklr)
            log.info(f"Loaded session filesystem from {session_fs_path}")
        else:
            with open("data/filesystem.pkl", "rb") as pklr:
                self.filesystem = pickle.load(pklr)
            log.info("Loaded default filesystem")

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
        log.info(f"Agent initialized. Current dir: {self.current_state['PWD']}")

    def _shell_prompt(self, state: dict) -> str:
        prompt = f"{state['USER']}@{state['HOSTNAME']}:{state['PWD']}{'#' if state['IS_ROOT'] else '$'} "
        return prompt.replace(state["HOME"], "~", 1)

    def _format_state(self) -> str:
        return f"""
Dynamic environment variables in JSON (you must return all of them and change them if needed):
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
                parent_content = parent.get("content")
                if not isinstance(parent_content, dict):
                    parent_content = {}
                existing = parent_content.get(name, {})

                if existing:
                    # Merge: existing + new (new overwrites)
                    if "content" in existing and "content" in entry:
                        if isinstance(existing.get("content"), dict) and isinstance(
                            entry.get("content"), dict
                        ):
                            existing["content"].update(entry.get("content", {}))
                    merged = {**existing, **entry}
                    if "content" not in parent:
                        parent["content"] = {}
                    parent["content"][name] = merged
                    parent["content"][name]["modified"] = modified
                    log.info(f"save_to_fs: merged {full_path}")
                else:
                    entry_type = entry.get("type", "file")
                    if "content" not in parent:
                        parent["content"] = {}
                    if entry_type == "dir":
                        entry["content"] = {}
                    else:
                        entry["content"] = entry.get("content", "")
                    parent["content"][name] = entry
                    parent["content"][name]["modified"] = modified
                    log.info(f"save_to_fs: added {full_path}")
            except FileNotFoundError:
                self._create_path(full_path, entry)
                log.info(f"save_to_fs: created and saved {full_path}")

    def save_session_filesystem(self) -> str:
        """Save current filesystem state to per-session file (not global)."""
        import os
        from utils import LOG_DIR

        os.makedirs(LOG_DIR, exist_ok=True)
        filepath = f"{LOG_DIR}/{self.output}_filesystem.pkl"
        with open(filepath, "wb") as pklw:
            pickle.dump(self.filesystem, pklw)
        log.info(f"Saved session filesystem to {filepath}")
        return filepath

    def chat_completion(self, prompt: str):
        retry_info = ""
        content = ""

        try:
            for attempt in range(MAX_VALIDATION_RETRIES):
                full_prompt = f"{prompt}{retry_info}"

                try:
                    completion = self.client.chat.completions.create(
                        model=self.current_model,
                        messages=[
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": full_prompt},
                        ],
                        temperature=0.1,
                    )

                    content = completion.choices[0].message.content
                    if not content:
                        return ""

                    content = content.replace("```json", "", count=1).replace("```", "")
                    log.info(f"chat_completion: LLM returned {content}")

                    try:
                        data = json.loads(content)
                    except json.JSONDecodeError as e:
                        log.warning(f"JSON decode failed: {e}, trying fix_json...")
                        try:
                            fixed = fix_json(content)
                            data = json.loads(fixed)
                        except json.JSONDecodeError as e2:
                            log.warning(
                                f"fix_json failed: {e2}, trying extract_json..."
                            )
                            fixed = extract_json(content)
                            data = json.loads(fixed)

                    self.total_tokens = (
                        completion.usage.total_tokens if completion.usage else 0
                    )

                    try:
                        structured_output = OutputStructure(**data)
                    except Exception as e:
                        log.error(f"LLM error: {e}")
                        return ""

                    self.current_state = {
                        "USER": structured_output.user,
                        "HOME": structured_output.home,
                        "HOSTNAME": structured_output.hostname,
                        "PWD": structured_output.pwd,
                        "IS_ROOT": bool(structured_output.is_root),
                    }

                    self.save_to_fs(structured_output.filesystem)

                    return structured_output.command_output

                except json.JSONDecodeError as e:
                    log.warning(f"LLM: attempt {attempt + 1} failed (JSON): {e}")
                    if content:
                        try:
                            try:
                                fixed = fix_json(content)
                                data = json.loads(fixed)
                            except json.JSONDecodeError:
                                fixed = extract_json(content)
                                data = json.loads(fixed)
                            structured_output = OutputStructure(**data)
                        except Exception as fallback_error:
                            log.warning(f"Fallback also failed: {fallback_error}")
                            retry_info = f"\n\nInvalid JSON: {e}. ONLY return valid JSON with all fields."

                except ValidationError as e:
                    log.warning(f"LLM: attempt {attempt + 1} failed (Pydantic): {e}")
                    retry_info = f"\n\nMissing/invalid fields: {e}. Provide: user, home, hostname, pwd, is_root, filesystem, command_output."

                except APITimeoutError as e:
                    log.warning(f"LLM: Timed Out")
                    retry_info = f""

                except RateLimitError as e:
                    log.warning(f"Rate limit hit on {self.current_model}")

                    if self.current_model == MODEL:
                        self.current_model = FALLBACK_MODEL
                        self.client = OpenAI(
                            base_url=FALLBACK_BASE_URL,
                            api_key=FALLBACK_API_KEY,
                            timeout=TIMEOUT,
                            max_retries=MAX_SCHEMA_RETRIES,
                        )
                        log.info(f"Switching to fallback model: {self.current_model}")
                    else:
                        log.warning("Fallback model also rate-limited")
                    retry_info = f""

            return ""
        except:
            return ""

    def handle_command(self, command: str, args: list) -> str:
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
                out, fs_changes = self.tools.handle_curl(
                    args, self.current_state["PWD"]
                )
                if out:
                    if fs_changes:
                        self.save_to_fs(fs_changes)
                    return out
                else:
                    return ""

            case "wget":
                out, fs_changes = self.tools.handle_wget(
                    args, self.current_state["PWD"]
                )
                if out:
                    if fs_changes:
                        self.save_to_fs(fs_changes)
                    return out
                else:
                    return ""

            case _:
                valid, error_msg = self.tools.validate_command(command)
                if not valid:
                    log.info(f"Invalid command: {command} with args {args}")
                    return error_msg
                return ""

    def chat(self, query: str) -> str:
        log.info(f"Query: {query}")
        output = ""
        last_id = self.tools.set_history(query)

        parsed_cmd: list[list[str]] = parse_shell(query)
        if not parsed_cmd:
            return "syntax error"

        # Get args of the last command
        self.current_state["_"] = parsed_cmd[-1][-1]

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

        # Get the current state/environment
        state = self._format_state()
        log.info(state)

        # Get info about files/dirs in the command
        dirs = "Directory listing for "
        if not paths:
            path = self.current_state["PWD"]
            dirs += f"{path} {self.tools.parse_path(self.filesystem, path).get('content', {})}\n"
        else:
            for path in paths:
                dirs += f"{path}: {self.tools.parse_path(self.filesystem, path).get('content', {})}\n"

        log.info(dirs)

        prompt = f"{state}\n\n{docs}\n{dirs}\n{cmd_outputs}\nUser Query: {query}"

        output = self.chat_completion(prompt)

        self.shell_prompt = self._shell_prompt(self.current_state)

        self.tools.update_history(last_id, output)

        return output


if __name__ == "__main__":
    log.info("Starting Agent shell...")
    agent = Agent()
    while True:
        q = input(agent.shell_prompt)
        if q != "":
            response = agent.chat(q)
            if response != "":
                print(response)
