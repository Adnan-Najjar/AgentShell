import re
import shlex
from datetime import datetime
import json
import os
import pickle

from openai import APITimeoutError, RateLimitError, OpenAI
from pydantic import BaseModel, ValidationError

from tools import Tools
from filesystem import Filesystem
from utils import (
    API_KEY,
    BASE_URL,
    CURR_DIR,
    ENV_VARS,
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
    extract_json,
    fix_json,
    log,
)


OPERATORS = {"||", "&&", "|", ";"}
_OP_PATTERN = re.compile(r"(\|\||&&|[|;&])")


def parse_shell(
    query: str,
    cwd: str = CURR_DIR,
    state: dict | None = None,
    fs: Filesystem | None = None,
) -> tuple[list, set]:
    all_vars = dict(ENV_VARS)
    if state:
        all_vars |= {
            k: v for k, v in state.items() if k not in ("filesystem", "IS_ROOT")
        }

    def _expand(token: str) -> str:
        for name, val in all_vars.items():
            token = token.replace(f"${name}", val)
        return token

    try:
        padded = _OP_PATTERN.sub(r" \1 ", query)
        lexer = shlex.shlex(padded, posix=True)
        lexer.whitespace_split = True
        lexer.commenters = ""

        result: list[list[str]] = []
        current: list[str] = []
        paths: set[str] = set()

        for token in lexer:
            token = token.strip()
            if not token:
                continue

            if token in OPERATORS:
                if current:
                    result.append(current)
                    current = []
                result.append([token])
            else:
                expanded = _expand(token)
                if expanded.startswith("./"):
                    resolved = os.path.normpath(os.path.join(cwd, expanded))
                    paths.add(resolved)
                    current.append(resolved)
                else:
                    if fs and fs.is_path(expanded):
                        if expanded.startswith("/"):
                            paths.add(expanded)
                        else:
                            paths.add(os.path.normpath(os.path.join(cwd, expanded)))
                    current.append(expanded)

        if current:
            result.append(current)

    except ValueError:
        return [[query]], set()

    return result, paths


class OutputStructure(BaseModel):
    user: str
    home: str
    hostname: str
    pwd: str
    is_root: str
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
        self.history = []

        session_fs_path = f"{LOG_DIR}/{self.output}_filesystem.pkl"
        fs = {}
        if os.path.exists(session_fs_path):
            with open(session_fs_path, "rb") as pklr:
                fs: dict = pickle.load(pklr)
            log.info(f"Loaded session filesystem from {session_fs_path}")
        else:
            with open("data/filesystem.pkl", "rb") as pklr:
                fs: dict = pickle.load(pklr)
            log.info("Loaded default filesystem")
        self.filesystem = Filesystem(fs)

        self.current_state = {
            "HOSTNAME": HOSTNAME,
            "USER": USER,
            "HOME": USER_DIR,
            "LOGNAME": USER,
            "PWD": CURR_DIR,
            "_": "/bin/sh",
            "?": "0",
            "IS_ROOT": IS_ROOT,
            "filesystem": {},
        }
        self.prompt_tokens = 0

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

    def save_to_fs(self, fs_changes: dict) -> None:
        """Save filesystem changes from LLM."""
        if not fs_changes:
            return
        for full_path, entry in fs_changes.items():
            if full_path == "/":
                continue
            self.filesystem.put(full_path, entry)
            log.info(f"save_to_fs: saved {full_path}")

    def save_session_history(self):
        """Save current history state to .bash_history file."""
        now = datetime.now()
        self.filesystem.put(
            f"{self.current_state['HOME']}/.bash_history",
            {
                "type": "file",
                "permissions": "-rw-------",
                "owner": USER,
                "group": USER,
                "modified": now.strftime("%Y-%m-%d"),
                "content": "\n".join(self.history),
            },
        )

    def save_session_filesystem(self) -> str:
        """Save current filesystem state to per-session file (not global)."""
        self.save_session_history()

        os.makedirs(LOG_DIR, exist_ok=True)
        filepath = f"{LOG_DIR}/{self.output}_filesystem.pkl"
        with open(filepath, "wb") as pklw:
            pickle.dump(self.filesystem.fs, pklw)
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
                        data = json.loads(content, strict=False)
                    except json.JSONDecodeError as e:
                        log.warning(f"JSON decode failed: {e}, trying fix_json...")
                        try:
                            fixed = fix_json(content)
                            data = json.loads(fixed, strict=False)
                        except json.JSONDecodeError as e2:
                            log.warning(
                                f"fix_json failed: {e2}, trying extract_json..."
                            )
                            fixed = extract_json(content)
                            data = json.loads(fixed, strict=False)

                    self.prompt_tokens = (
                        completion.usage.prompt_tokens if completion.usage else 0
                    )

                    try:
                        structured_output = OutputStructure(**data)
                    except Exception as e:
                        log.error(f"LLM error: {e}")
                        return ""

                    self.current_state.update(
                        {
                            "USER": structured_output.user,
                            "HOME": structured_output.home,
                            "HOSTNAME": structured_output.hostname,
                            "PWD": structured_output.pwd,
                            "IS_ROOT": bool(structured_output.is_root),
                        }
                    )

                    self.save_to_fs(structured_output.filesystem)

                    return structured_output.command_output

                except json.JSONDecodeError as e:
                    log.warning(f"LLM: attempt {attempt + 1} failed (JSON): {e}")
                    if content:
                        try:
                            try:
                                fixed = fix_json(content)
                                data = json.loads(fixed, strict=False)
                            except json.JSONDecodeError:
                                fixed = extract_json(content)
                                data = json.loads(fixed, strict=False)
                            structured_output = OutputStructure(**data)
                        except Exception as fallback_error:
                            log.warning(f"Fallback also failed: {fallback_error}")
                            retry_info = f"\n\nInvalid JSON: {e}. ONLY return valid JSON with all fields."

                except ValidationError as e:
                    log.warning(f"LLM: attempt {attempt + 1} failed (Pydantic): {e}")
                    retry_info = f"\n\nMissing/invalid fields: {e}. Provide: user, home, hostname, pwd, is_root, filesystem, command_output."

                except APITimeoutError:
                    log.warning("LLM: Timed Out")
                    retry_info = ""

                except RateLimitError:
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
                    retry_info = ""

            return ""
        except Exception:
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

            case "history":
                return self.handle_history(args)

            case "curl":
                out, fs_changes = self.tools.handle_curl(
                    args, self.current_state["PWD"]
                )
                if out:
                    if fs_changes:
                        self.save_to_fs(fs_changes)
                    return out
                return ""

            case "wget":
                out, fs_changes = self.tools.handle_wget(
                    args, self.current_state["PWD"]
                )
                if out:
                    if fs_changes:
                        self.save_to_fs(fs_changes)
                    return out
                return ""

            case _:
                valid, error_msg = self.tools.validate_command(command)
                if not valid:
                    log.info(f"Invalid command: {command} with args {args}")
                    return error_msg
                return ""

    def handle_history(self, args: list) -> str:
        if "-c" in args:
            self.history = []
            return ""
        if not self.history:
            return ""
        return "\n".join(f"{i+1}\t{cmd}" for i, cmd in enumerate(self.history))

    def chat(self, query: str) -> str:
        log.info(f"Query: {query}")
        output = ""

        self.history.append(query)

        parsed_cmd, paths = parse_shell(
            query, self.current_state["PWD"], self.current_state, self.filesystem
        )
        if not parsed_cmd:
            return "syntax error"

        # Last arg of the last real command (not an operator token)
        last_cmd = next(
            (t for t in reversed(parsed_cmd) if t[0] not in OPERATORS), None
        )
        if last_cmd:
            self.current_state["_"] = last_cmd[-1]
        cmd_flags = {}
        user_query = ""
        cmd_outputs = ""

        for token in parsed_cmd:
            user_query += " ".join(token)
            command = token[0]
            if command in OPERATORS:
                continue

            args = token[1:]
            command_output = self.handle_command(command, args)
            if command_output:
                cmd_outputs += f"Output of {' '.join(token)} is {command_output}"

        log.info(cmd_outputs)

        state = self._format_state()
        log.info(state)

        if not paths:
            dirs = self.filesystem.path_info(self.current_state["PWD"])
        else:
            dirs = "\n".join(self.filesystem.path_info(p) for p in paths if p != "")
        dirs += (
            "\n\n(If directory or files are empty, generate plausible content instead)"
        )

        log.info(dirs)

        prompt = f"{state}\n{dirs}\n{cmd_outputs}\nUser Query: {user_query}"

        output = self.chat_completion(prompt)

        self.shell_prompt = self._shell_prompt(self.current_state)
        return output


if __name__ == "__main__":
    log.info("Starting Agent shell...")
    agent = Agent()
    try:
        while True:
            q = input(agent.shell_prompt)
            if q != "":
                response = agent.chat(q)
                if response != "":
                    print(response)
    except (KeyboardInterrupt, EOFError):
        print()
        agent.save_session_filesystem()
        log.info("Session saved. Goodbye.")
