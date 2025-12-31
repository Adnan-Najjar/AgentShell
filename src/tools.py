from langchain_core.tools import StructuredTool
import sqlite3
import os


class Tools:
    def __init__(self, thread_id: str):
        os.makedirs(thread_id, exist_ok=True)
        self.db_path = os.path.join(thread_id, "history.db")
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self):
        cursor = self.conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                command TEXT NOT NULL,
                output TEXT
            )
        """
        )
        self.conn.commit()

    def get_global_history(self) -> str:
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, command FROM history ORDER BY id LIMIT 500")
        results = cursor.fetchall()

        if results is None:
            return ""

        output = ""
        for cmd_id, command in results:
            output += f"\n {cmd_id}\t{command}"
        return output

    def set_global_history(self, command: str) -> int:
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO history (command, output) VALUES (?, NULL)", (command,)
        )
        self.conn.commit()
        return cursor.lastrowid if cursor.lastrowid else 1

    def update_history_output(self, cmd_id: int, output: str):
        cursor = self.conn.cursor()
        cursor.execute("UPDATE history SET output = ? WHERE id = ?", (output, cmd_id))
        self.conn.commit()

    def get_tools(self):
        return [
            StructuredTool.from_function(
                func=self.get_global_history,
                description="ONLY use when user explicitly requests command history. DO NOT call this tool proactively or to check previous interactions - you already have access to conversation history.",
                name="get_global_history",
            )
        ]

    def __del__(self):
        if hasattr(self, "conn"):
            self.conn.close()
