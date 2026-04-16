import logging
import os
import re
import sqlite3
import subprocess

from utils import OUTPUT_DIR, MODEL_NAME, ENV_VARS

logger = logging.getLogger("agent")


class Tools:
    def __init__(self, thread_id: str):
        self.id = thread_id
        self._prev_dir = None
        os.makedirs(f"{OUTPUT_DIR}/{MODEL_NAME}/history", exist_ok=True)

        self.conn = sqlite3.connect(
            f"{OUTPUT_DIR}/{MODEL_NAME}/history/{self.id}.db", check_same_thread=False
        )
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

    def __del__(self):
        if hasattr(self, "conn"):
            self.conn.close()

    def __exit__(self):
        if hasattr(self, "conn"):
            self.conn.close()

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

            help_re = re.compile(
                rf"^\s*(-+[a-zA-Z]+, )?{option}.*?^\s*(?=-)", re.MULTILINE | re.DOTALL
            )
            help_page = help_re.search(help_page)
            if help_page:
                return help_page.group()
        except subprocess.TimeoutExpired:
            logger.debug(f"RAG: Timeout fetching help for {command} {option}")
        except Exception as e:
            logger.debug(f"RAG: Error fetching help for {command} {option}: {e}")

        return ""

    def _man_page(self, command: str, option: str = "") -> str:
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

            if option == "":
                # Only get core info lke SYNOPSIS and DESCRIPTION
                core = re.search(
                    r"^SYNOPSIS.*?^\s*(?=-)", man_page, re.MULTILINE | re.DOTALL
                )
                return core.group() if core else ""
            man_re = re.compile(
                rf"^\s*(-+[a-zA-Z]+, )?{option}.*?^\s*(?=-)", re.MULTILINE | re.DOTALL
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
            output += self._man_page(command["command"])
            for option in command["flags"]:
                logger.info(f"RAG: command: {command['command']} | flags: {option}")
                if option:
                    output += self._help_page(command["command"], option)
                    output += "\n"
                    output += self._man_page(command["command"], option)
                    output += "\n"

        logger.info(f"RAG: Returned {output}")
        return re.sub(r"\n\s*\n", "", output)

    def handle_env(self, command: str, current_state: dict) -> str:
        logger.debug(f"env: {command}")
        parts = command.split(maxsplit=1)
        all_vars = dict(ENV_VARS)
        all_vars.update(current_state)

        if len(parts) == 1:
            filtered_vars = {k: v for k, v in all_vars.items() if k not in ("_", "?")}
            return "\n".join(f"{k}={v}" for k, v in filtered_vars.items())

        arg = parts[1].strip()
        if "=" in arg:
            return arg
        else:
            return all_vars.get(arg, "")

    def handle_export(self, command: str, current_state: dict) -> str:
        logger.debug(f"export: {command}")
        parts = command.split(maxsplit=1)
        var_val = parts[1].split("=")
        current_state[var_val[0]] = var_val[1]
        return ""

    def handle_apt(self, command: str) -> str:
        logger.debug(f"apt: {command}")
        help_menu = """
apt 0.9.7.9 for amd64 compiled on Oct 17 2014 09:15:56
Usage: apt-get [options] command
       apt-get [options] install|remove pkg1 [pkg2 ...]
       apt-get [options] source pkg1 [pkg2 ...]

apt-get is a simple command line interface for downloading and
installing packages. The most frequently used commands are update
and install.

Commands:
   update - Retrieve new lists of packages
   upgrade - Perform an upgrade
   install - Install new packages (pkg is libc6 not libc6.deb)
   remove - Remove packages
   autoremove - Remove automatically all unused packages
   purge - Remove packages and config files
   source - Download source archives
   build-dep - Configure build-dependencies for source packages
   dist-upgrade - Distribution upgrade, see apt-get(8)
   dselect-upgrade - Follow dselect selections
   clean - Erase downloaded archive files
   autoclean - Erase old downloaded archive files
   check - Verify that there are no broken dependencies
   changelog - Download and display the changelog for the given package
   download - Download the binary package into the current directory

Options:
  -h  This help text.
  -q  Loggable output - no progress indicator
  -qq No output except for errors
  -d  Download only - do NOT install or unpack archives
  -s  No-act. Perform ordering simulation
  -y  Assume Yes to all queries and do not prompt
  -f  Attempt to correct a system with broken dependencies in place
  -m  Attempt to continue if archives are unlocatable
  -u  Show a list of upgraded packages as well
  -b  Build the source package after fetching it
  -V  Show verbose version numbers
  -c=? Read this configuration file
  -o=? Set an arbitrary configuration option, eg -o dir::cache=/tmp
See the apt-get(8), sources.list(5) and apt.conf(5) manual
pages for more information and options.
                        This APT has Super Cow Powers.
"""
        upgrade = """
Reading package lists... Done
Building dependency tree
Reading state information... Done
0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.
"""
        update = """
Ign http://deb.debian.org wheezy Release.gpg
Ign http://deb.debian.org wheezy-updates Release.gpg
Ign http://security.debian.org wheezy/updates Release.gpg
Ign http://deb.debian.org wheezy Release
Ign http://security.debian.org wheezy/updates Release
Err http://security.debian.org wheezy/updates/main amd64 Packages

Ign http://deb.debian.org wheezy-updates Release
Err http://security.debian.org wheezy/updates/main amd64 Packages

Err http://security.debian.org wheezy/updates/main amd64 Packages

Err http://security.debian.org wheezy/updates/main amd64 Packages

Err http://security.debian.org wheezy/updates/main amd64 Packages
  404  Not Found [IP: 146.75.94.132 80]
Err http://deb.debian.org wheezy/main amd64 Packages
  404  Not Found
Err http://deb.debian.org wheezy-updates/main amd64 Packages
  404  Not Found
W: Failed to fetch http://deb.debian.org/debian/dists/wheezy/main/binary-amd64/Packages  404  Not Found

W: Failed to fetch http://security.debian.org/debian-security/dists/wheezy/updates/main/binary-amd64/Packages  404  Not Found [IP: 146.75.94.13 80]

W: Failed to fetch http://deb.debian.org/debian-updates/dists/wheezy-updates/main/binary-amd64/Packages  404  Not Found

E: Some index files failed to download. They have been ignored, or old ones used instead.
"""
        package_commands = [
            "install",
            "remove",
            "purge",
            "source",
            "build-dep",
            "download",
            "show",
            "check",
            "changelog",
        ]

        parts = command.split()
        if len(parts) == 1:
            return help_menu
        elif "upgrade" in parts:
            return upgrade
        elif "update" in parts:
            return update
        else:
            for pkg_cmd in package_commands:
                if pkg_cmd in parts:
                    try:
                        idx = parts.index(pkg_cmd)
                        package = parts[idx + 1]
                        return f"E: Unable to locate package {package}"
                    except:
                        continue
            else:
                return help_menu

    def handle_history(self, command: str) -> str:
        logger.debug(f"history: {command}")
        parts = command.split(maxsplit=1)
        if len(parts) > 1 and parts[1].startswith("-c"):
            self.delete_history()
            return ""
        return self.get_history()

    def handle_cd(self, command: str, current_state: dict) -> str:
        parts = command.split(maxsplit=1)
        target = parts[1].strip() if len(parts) > 1 else "~"

        current = current_state["PWD"]
        user_home = current_state["HOME"]

        if target == "~":
            new_path = user_home
        elif target == "-":
            new_path = self._prev_dir if self._prev_dir else user_home
        else:
            raw_path = os.path.join(current, target)
            new_path = os.path.normpath(raw_path)

        self._prev_dir = current
        current_state["PWD"] = new_path
        logger.info(f"cd: {current} -> {new_path}")
        return ""

    def handle_env_vars(self, query: str, current_state: dict) -> str:
        logger.debug(f"env_vars: {query}")
        all_vars = ENV_VARS | current_state
        return re.sub(r"\$(\w+)", lambda m: all_vars.get(m.group(1), m.group(0)), query)
