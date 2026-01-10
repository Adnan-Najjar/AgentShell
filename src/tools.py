from langchain_core.tools import StructuredTool
import sqlite3
import docker
from utils import OUTPUT_DIR


class Tools:
    def __init__(self, thread_id: str):
        self.id = thread_id

        self.conn = sqlite3.connect(f"{OUTPUT_DIR}/history.db", check_same_thread=False)
        self._init_db()

        self.container_name = "debian-sandbox"
        self.client = docker.from_env()
        self._ensure_container()

    # ==== HISTORY TOOL ====
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
        cursor = self.conn.cursor()
        cursor.execute(
            f"INSERT INTO {self.id} (command, output) VALUES (?, NULL)", (command,)
        )
        self.conn.commit()
        return cursor.lastrowid if cursor.lastrowid else 1

    def update_history(self, cmd_id: int, output: str):
        cursor = self.conn.cursor()
        cursor.execute(
            f"UPDATE {self.id} SET output = ? WHERE id = ?", (output, cmd_id)
        )
        self.conn.commit()

    def delete_history(self):
        cursor = self.conn.cursor()
        cursor.execute(f"UPDATE {self.id} SET deleted = 1")
        self.conn.commit()

    def __del__(self):
        if hasattr(self, "conn"):
            self.conn.close()

    def __exit__(self):
        if hasattr(self, "conn"):
            self.conn.close()

    # ======================
    # ====  BASH TOOL  ====
    def _ensure_container(self):
        try:
            self.container = self.client.containers.get(self.container_name)
            if self.container.status != "running":
                self.container.start()
        except:
            self.container = self.client.containers.run(
                "ubuntu:latest",  # used ubuntu here because it has all the basic tools installed
                name=self.container_name,
                detach=True,
                tty=True,
            )

    def validate_command(self, command: str) -> tuple[bool, str]:
        # Check command avaliblity
        exit_code, _ = self.container.exec_run(
            cmd=["/bin/bash", "-c", f"command -v {command}"]
        )
        error_msg = f"bash: {command.split()[0]}: command not found"
        if exit_code == 0:
            # Check command correctness
            exit_code, error_msg = self.container.exec_run(
                cmd=["/bin/bash", "-n", "-c", command]
            )

        return True if exit_code == 0 else False, error_msg

    def execute_bash(self, command: str) -> str:
        exit_code, output = self.container.exec_run(cmd=["/bin/bash", "-c", command])
        if exit_code != 0:
            return output.decode("utf-8")
        return f"{command}: {output.decode('utf-8')}"

    # ======================

    def get_tools(self):
        return [
            StructuredTool.from_function(
                func=self.get_history,
                description="ONLY use when user explicitly requests command history. DO NOT call this tool proactively or to check previous interactions - you already have access to conversation history.",
                name="get_history",
            ),
            StructuredTool.from_function(
                func=self.delete_history,
                description="ONLY use when user explicitly requests deletion of the command history.",
                name="delete_history",
            ),
            StructuredTool.from_function(
                func=self.execute_bash,
                description="ONLY use this tool for complex bash piping and string manipulation operations that require shell features. Do not use for simple commands or commands that need kernel access - respond directly instead.",
                name="execute_bash",
            ),
        ]
