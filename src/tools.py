import logging
import re
import sqlite3
import subprocess

from utils import OUTPUT_DIR

logger = logging.getLogger("agent")


class Tools:
    def __init__(self, thread_id: str):
        self.id = thread_id

        self.conn = sqlite3.connect(f"{OUTPUT_DIR}/history.db", check_same_thread=False)
        self._init_db()

    def _init_db(self):
        cursor = self.conn.cursor()
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.id} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                command TEXT NOT NULL,
                output TEXT,
                deleted INTEGER DEFAULT 0
            )
            """
        )
        self.conn.commit()

    def get_history(self) -> str:
        """Show command history."""
        cursor = self.conn.cursor()
        cursor.execute(
            f"SELECT ROW_NUMBER() OVER (ORDER BY id), command FROM {self.id} WHERE deleted = 0 LIMIT 500"
        )
        results = cursor.fetchall()

        if results is None:
            return ""

        output = ""
        for cmd_id, command in results:
            output += f"\n {cmd_id}\t{command}"
        return output

    def set_history(self, command: str) -> int:
        """Store command in history."""
        cursor = self.conn.cursor()
        cursor.execute(
            f"INSERT INTO {self.id} (command, output) VALUES (?, NULL)", (command,)
        )
        self.conn.commit()
        return cursor.lastrowid if cursor.lastrowid else 1

    def update_history(self, cmd_id: int, output: str):
        """Update command output in history."""
        cursor = self.conn.cursor()
        cursor.execute(
            f"UPDATE {self.id} SET output = ? WHERE id = ?", (output, cmd_id)
        )
        self.conn.commit()

    def delete_history(self):
        """Clear all command history."""
        cursor = self.conn.cursor()
        cursor.execute(f"UPDATE {self.id} SET deleted = 1")
        self.conn.commit()

    def validate_command(self, command: str) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                ["bash", "-c", f"command -v {command.split()[0]}"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode != 0:
                return False, f"bash: {command.split()[0]}: command not found"

            result = subprocess.run(
                ["bash", "-n", "-c", command], capture_output=True, timeout=5
            )
            return (
                result.returncode == 0,
                "syntax error" if result.returncode != 0 else "",
            )
        except subprocess.TimeoutExpired:
            return False, "command timed out"

    def _help_page(self, command: str, option: str) -> str:
        logger.debug(f"RAG: Fetching --help for {command} {option}")

        try:
            help_cmd = f"{command} --help"
            result = subprocess.run(
                ["bash", "-c", help_cmd], capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                logger.debug(f"RAG: No help page found for {command} {option}")
                return ""
            help_page = result.stdout

            if option == "":
                return "\n".join(help_page.splitlines()[0:4])
            help_re = re.compile(
                rf"^\s*(-[a-zA-Z], )?{option}.*?^\s*(?=-)", re.MULTILINE | re.DOTALL
            )
            help_page = help_re.search(help_page)
            if help_page:
                return help_page.group()
        except subprocess.TimeoutExpired:
            logger.debug(f"RAG: Timeout fetching help for {command} {option}")
        except Exception as e:
            logger.debug(f"RAG: Error fetching help for {command} {option}: {e}")

        return ""

    def _man_page(self, command: str, option: str) -> str:
        logger.debug(f"RAG: Fetching man page for {command} {option}")

        try:
            man_cmd = f"MANWIDTH=999 man -P cat {command}"
            result = subprocess.run(
                ["bash", "-c", man_cmd], capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                logger.debug(f"RAG: No man page found for {command} {option}")
                return ""
            man_page = result.stdout

            man_re = re.compile(
                rf"^\s*(-[a-zA-Z], )?{option}.*?^\s*(?=-)", re.MULTILINE | re.DOTALL
            )
            man_page = man_re.search(man_page)
            if man_page:
                return man_page.group()
        except subprocess.TimeoutExpired:
            logger.debug(f"RAG: Timeout fetching man page for {command} {option}")
        except Exception as e:
            logger.debug(f"RAG: Error fetching man page for {command} {option}: {e}")

        return ""

    def get_docs(self, commands: list) -> str:
        logger.info(f"RAG: Request for {len(commands)} commands")

        output = ""
        for command in commands:
            output += self._help_page(command["command"], "")
            for option in command["flags"]:
                logger.info(f"RAG: command: {command['command']} | flags: {option}")
                if option:
                    output += self._help_page(command["command"], option)
                    output += "\n"
                    output += self._man_page(command["command"], option)
                    output += "\n"

        logger.info(f"RAG: Returned {output}")
        return output

    def __del__(self):
        if hasattr(self, "conn"):
            self.conn.close()

    def __exit__(self):
        if hasattr(self, "conn"):
            self.conn.close()
