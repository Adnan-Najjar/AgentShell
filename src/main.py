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


OPERATORS = {"||", "&&", ";"}
COMPOUND_KEYWORDS = {
    "for",
    "while",
    "until",
    "if",
    "case",
    "elif",
    "then",
    "else",
    "function",
    "{",
}
_OP_PATTERN = re.compile(r"(\|\||&&|[;&])")


class OutputStructure(BaseModel):
    filesystem: dict = {}
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
        return f"State: user={self.current_state['USER']}, home={self.current_state['HOME']}, hostname={self.current_state['HOSTNAME']}, pwd={self.current_state['PWD']}, is_root={self.current_state['IS_ROOT']}"

    def parse_shell(self, query: str) -> tuple[list, list[set]]:
        cwd = self.current_state["PWD"]

        first = query.lstrip().split(maxsplit=1)[0] if query.strip() else ""
        if first in COMPOUND_KEYWORDS:
            return None, []

        # Protect $() before paren stripping
        cmdsub_map = {}

        def _save_cmdsub(m):
            key = f"\x00CSUB{len(cmdsub_map)}\x00"
            cmdsub_map[key] = m.group(0)
            return key

        query = re.sub(r"\$\(([^)]*)\)", _save_cmdsub, query)

        query = query.replace("(", "").replace(")", "")

        # Protect redirect-adjacent & before _OP_PATTERN
        redir_map = {}

        def _save_redir(m):
            key = f"\x00RED{len(redir_map)}\x00"
            redir_map[key] = m.group(0)
            return key

        query = re.sub(r"\d+>&\d+", _save_redir, query)
        query = re.sub(r"&>(?=\s|$)", _save_redir, query)

        query = re.sub(r"(?<!\|)\|(?!\|)", " | ", query)

        try:
            padded = _OP_PATTERN.sub(r" \1 ", query)
            lexer = shlex.shlex(padded, posix=True)
            lexer.whitespace_split = True
            lexer.commenters = ""

            # Fast path for $() — preserves $(...) as strings, returns list[list[str]]
            if cmdsub_map:
                segments: list[list[str]] = []
                current: list[str] = []

                for token in lexer:
                    token = token.strip()
                    if not token:
                        continue
                    if token in cmdsub_map:
                        current.append(cmdsub_map[token])
                    elif token in redir_map:
                        current.append(redir_map[token])
                    elif token in OPERATORS:
                        if current:
                            segments.append(current)
                            current = []
                        segments.append([token])
                    elif token == "|":
                        current.append("|")
                    else:
                        expanded = self.tools.handle_env_vars(
                            [token], self.current_state
                        )[0]
                        current.append(expanded)

                if current:
                    segments.append(current)

                return segments, [set() for _ in segments]

            result: list[list[str]] = []
            result_paths: list[set[str]] = []
            current: list[str] = []
            current_paths: set[str] = set()

            def _append_current():
                nonlocal current, current_paths, result, result_paths
                if current:
                    result.append(current)
                    result_paths.append(current_paths)
                    current = []
                    current_paths = set()

            for token in lexer:
                token = token.strip()
                if not token:
                    continue

                if token in redir_map:
                    token = redir_map[token]

                if token in OPERATORS:
                    _append_current()
                    result.append([token])
                    result_paths.append(set())
                elif token == "|":
                    current.append("|")
                else:
                    expanded = self.tools.handle_env_vars([token], self.current_state)[
                        0
                    ]
                    if expanded.startswith("./"):
                        resolved = os.path.normpath(os.path.join(cwd, expanded))
                        current_paths.add(resolved)
                        current.append(resolved)
                    else:
                        if self.filesystem.is_path(expanded):
                            if expanded.startswith("/"):
                                current_paths.add(expanded)
                            else:
                                current_paths.add(
                                    os.path.normpath(os.path.join(cwd, expanded))
                                )
                        current.append(expanded)

            _append_current()

        except ValueError:
            return [[query]], [set()]

        return result, result_paths

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

                    content = re.sub(r'\\([^"\\/bfnrtu])', r"\1", content)

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

                    structured_output = OutputStructure(**data)

                    bad = [
                        p
                        for p, e in structured_output.filesystem.items()
                        if e.get("type", "file") == "file"
                        and not e.get("content")
                    ]
                    if bad:
                        paths_str = ", ".join(bad)
                        retry_info = f"\n\nFiles missing content: {paths_str}. Every file entry MUST include non-empty 'content'."
                        continue

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
                            retry_info = f'\n\nInvalid JSON: {e}. Follow this structure:\n{{\n  "filesystem": {{}},\n  "command_output": ...\n}}'

                except ValidationError as e:
                    log.warning(f"LLM: attempt {attempt + 1} failed (Pydantic): {e}")
                    retry_info = f"\n\nMissing/invalid fields: {e}. Only return filesystem and command_output."

                except APITimeoutError:
                    log.warning("LLM: Timed Out")
                    retry_info = '\n\nReturn ONLY valid JSON: {"filesystem": {}, "command_output": "..."}'

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
        if command == "sudo":
            self.current_state["IS_ROOT"] = True
            return self.handle_command(args[0], args[1:])

        match command:
            case "cd":
                return self.tools.handle_cd(args, self.current_state, self.filesystem)
            case "export":
                return self.tools.handle_export(args, self.current_state)
            case "env":
                return self.tools.handle_env(args, self.current_state)
            case "hostname":
                return self.tools.handle_hostname(args, self.current_state)
            case "su":
                return self.tools.handle_su(args, self.current_state)
            case "pwd":
                return self.current_state["PWD"] + "\n"
            case "exit" | "logout":
                return self.tools.handle_exit(args, self.current_state)
            case "apt" | "apt-get":
                return self.tools.handle_apt(args)
            case "history":
                return self.handle_history(args)
            case "curl":
                return self.tools.handle_curl(
                    args, self.current_state["PWD"], self.filesystem
                )
            case "wget":
                return self.tools.handle_wget(
                    args, self.current_state["PWD"], self.filesystem
                )
            case _:
                if "/" in command:
                    return None
                valid, error_msg = self.tools.validate_command(command)
                if not valid:
                    log.info(f"Invalid command: {command} with args {args}")
                    return error_msg
                return None

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

        parsed_cmd, paths_list = self.parse_shell(query)
        if parsed_cmd is None:
            state = self._format_state()
            dirs = self.filesystem.path_info(self.current_state["PWD"])
            dirs += (
                "(If directory or files are empty, generate plausible content instead)"
            )
            return (
                self.chat_completion(f"{state}\n{dirs}\nUser Query: {query}").rstrip(
                    "\n"
                )
                + "\n"
            )
        if not parsed_cmd:
            return "syntax error"

        last_cmd = next(
            (t for t in reversed(parsed_cmd) if t[0] not in OPERATORS), None
        )
        if last_cmd:
            self.current_state["_"] = last_cmd[-1]

        for i, token in enumerate(parsed_cmd):
            command = token[0]
            if command in OPERATORS:
                continue

            was_root = self.current_state["IS_ROOT"]
            result = self.handle_command(command, token[1:])
            self.current_state["IS_ROOT"] = was_root

            if result is None:
                log.info(f"LLM needed: {' '.join(token)}")
                state = self._format_state()
                log.info(f"State: {state}")

                paths = paths_list[i] if i < len(paths_list) else set()
                log.info(f"Paths extracted {paths}")
                dirs = self.filesystem.path_info(self.current_state["PWD"])
                if paths:
                    dirs += "\n".join(
                        self.filesystem.path_info(p) for p in paths if p != ""
                    )
                dirs += "(If directory or files are empty, generate plausible content instead, unless its <content_trimmed>)"
                log.info(dirs)

                prompt = f"{state}\n{dirs}\nUser Query: {' '.join(token)}"

                token_output = self.chat_completion(prompt)
                output += (token_output or "").rstrip("\n") + "\n"
            elif result:
                log.info(f"Manually handled: {' '.join(token)}")
                output += result.rstrip("\n") + "\n"

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
