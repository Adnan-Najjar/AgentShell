from datetime import datetime
import ipaddress
import os
import random
import re
import shlex
import shutil
import socket
import subprocess
from urllib.parse import urljoin, urlparse

import requests

from utils import ENV_VARS, LOG_DIR, log


class Tools:
    def __init__(self, ip_addr: str):
        self._prev_dir = None
        self.output = ip_addr.replace(".", "_")

    def validate_command(self, command: str) -> tuple[bool, str]:
        try:
            tokens = shlex.split(command)
            cmd = tokens[0] if tokens else ""

            # Check command exists
            if shutil.which(cmd) is None:
                return False, f"bash: {cmd}: command not found"

            # Check syntax safely
            proc = subprocess.run(
                ["bash", "-n"],
                input=command,
                text=True,
                capture_output=True,
                timeout=5,
            )

            if proc.returncode != 0:
                return False, proc.stderr.strip() or "syntax error"

            return True, ""
        except:
            return False, "syntax error"

    def _help_page(self, command: str, option: str) -> str:
        try:
            result = subprocess.run(
                [command, "--help"], capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                log.info(f"RAG: No help page found for {command} {option}")
                return ""
            help_page = result.stdout

            help_re = re.compile(
                rf"^\s*(-+[a-zA-Z]+, )?{option}.*?^\s*(?=-)", re.MULTILINE | re.DOTALL
            )
            help_page = help_re.search(help_page)
            if help_page:
                return help_page.group()
        except subprocess.TimeoutExpired:
            log.info(f"RAG: Timeout fetching help for {command} {option}")
        except Exception as e:
            log.info(f"RAG: Error fetching help for {command} {option}: {e}")

        return ""

    def _man_page(self, command: str, option: str = "") -> str:
        try:
            result = subprocess.run(
                ["man", "-P", "cat", command],
                capture_output=True,
                text=True,
                timeout=10,
                env={"MANWIDTH": "999"},
            )
            if result.returncode != 0:
                log.info(f"RAG: No man page found for {command} {option}")
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
            log.info(f"RAG: Timeout fetching man page for {command} {option}")
        except Exception as e:
            log.info(f"RAG: Error fetching man page for {command} {option}: {e}")

        return ""

    def get_docs(self, command: dict) -> str:
        log.info(f"RAG: Request for {command} commands")

        output = self._man_page(command["command"])
        for option in command["flags"]:
            if option:
                output += self._help_page(command["command"], option)
                output += "\n"
                output += self._man_page(command["command"], option)
                output += "\n"

        output = re.sub(r"\s{2,}", " ", output)
        log.info(f"RAG: Returned {output}")
        return output

    def handle_env(self, args: list, current_state: dict) -> str:
        log.info(f"env: {args}")

        all_vars = dict(ENV_VARS) | current_state
        not_vars = ["0", "#", "-", "?", "IS_ROOT", "filesystem"]

        if not args:
            filtered_vars = {k: v for k, v in all_vars.items() if k not in not_vars}
            return "\n".join(f"{k}={v}" for k, v in filtered_vars.items())

        arg = args[0]
        if "=" in arg:
            return arg
        else:
            return all_vars.get(arg, "")

    def handle_export(self, args: list, current_state: dict) -> str:
        log.info(f"export: {args}")
        var_val = args[0].split("=")
        current_state[var_val[0]] = var_val[1]
        return ""

    def handle_apt(self, args: list) -> str:
        log.info(f"apt: {args}")
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
Hit:1 http://archive.ubuntu.com/ubuntu lunar InRelease
Get:2 http://archive.ubuntu.com/ubuntu lunar-updates InRelease [109 kB]
Get:3 http://archive.ubuntu.com/ubuntu lunar-backports InRelease [101 kB]
Get:4 http://security.ubuntu.com/ubuntu lunar-security InRelease [101 kB]
Err:2 http://archive.ubuntu.com/ubuntu lunar-updates InRelease
  The following signatures were invalid: EXPKEYSIG 871920D1991BC93C Ubuntu Archive Automatic Signing Key
Err:3 http://archive.ubuntu.com/ubuntu lunar-backports InRelease
  The following signatures were invalid: EXPKEYSIG 871920D1991BC93C Ubuntu Archive Automatic Signing Key
Err:4 http://security.ubuntu.com/ubuntu lunar-security InRelease
  The following signatures were invalid: EXPKEYSIG 871920D1991BC93C Ubuntu Archive Automatic Signing Key
Reading package lists... Done
W: GPG error: http://archive.ubuntu.com/ubuntu lunar-updates InRelease: The following signatures were invalid: EXPKEYSIG 871920D1991BC93C Ubuntu Archive Automatic Signing Key
E: The repository 'http://archive.ubuntu.com/ubuntu lunar-updates InRelease' is no longer signed.
N: Updating from such a repository can't be done securely, and is therefore disabled by default.
E: The repository 'http://security.ubuntu.com/ubuntu lunar-security InRelease' is no longer signed.
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

        if not args:
            return help_menu
        elif "upgrade" in args:
            return upgrade
        elif "update" in args:
            return update
        else:
            for pkg_cmd in package_commands:
                if pkg_cmd in args:
                    try:
                        idx = args.index(pkg_cmd)
                        package = args[idx + 1]
                        return f"E: Unable to locate package {package}"
                    except:
                        continue
            else:
                return help_menu

    def handle_cd(self, args: list, current_state: dict, filesystem: dict) -> str:
        target = args[0] if len(args) > 0 else "~"
        current = current_state["PWD"]
        user_home = current_state["HOME"]

        if target == "~":
            new_path = user_home
        elif target == "-":
            new_path = self._prev_dir if self._prev_dir else user_home
        else:
            if os.path.isabs(target):
                full_path = target
            else:
                full_path = os.path.join(current, target)
            new_path = os.path.normpath(full_path)
            try:
                node = filesystem.get(new_path)
                if node.get("type") != "dir":
                    return f"cd: {target}: Not a directory"
            except KeyError:
                return f"cd: {target}: No such file or directory"

        self._prev_dir = current
        current_state["PWD"] = new_path
        log.info(f"cd: {current} -> {new_path}")
        return ""

    def handle_env_vars(self, args: list, current_state: dict) -> list:
        """
        Expand environment variables in args.
        Works like bash - $VAR can be anywhere in the argument.
        Unrecognized vars are kept as-is.
        Returns a list of expanded args.
        """
        all_vars = ENV_VARS | current_state

        expanded = []
        for arg in args:
            # Replace $VAR patterns anywhere in string
            new_arg = arg
            for var_name, var_value in all_vars.items():
                if var_name in ("filesystem", "IS_ROOT"):
                    continue
                new_arg = new_arg.replace(f"${var_name}", var_value)
            expanded.append(new_arg)

        if args != expanded:
            log.info(f"env_vars: {expanded}")
        return expanded

    def _is_blocked_host(self, arg) -> bool:
        return False # WARN: REMOVE IN DEPLOYMENT
        try:
            parsed = urlparse(arg)
            host = parsed.hostname or arg

            # Resolve hostname to all IPs
            infos = socket.getaddrinfo(host, None)

            for info in infos:
                ip = info[4][0]
                ip_obj = ipaddress.ip_address(ip)

                if (
                    ip_obj.is_loopback
                    or ip_obj.is_private
                    or ip_obj.is_link_local
                    or ip_obj.is_reserved
                ):
                    return True

            return False
        except Exception:
            # If resolution fails, safer to block
            return True

    def handle_downloads(
        self, url: str, output_path: str, command: str = "wget"
    ) -> dict | None:
        parsed = urlparse(url)

        if parsed.scheme not in ("http", "https"):
            log.warn(f"Download blocked: unsupported scheme {parsed.scheme!r}")
            return None

        if not parsed.hostname or self._is_blocked_host(parsed.hostname):
            log.warn(f"Download blocked: host {parsed.hostname!r} is local/private")
            return None

        # User-Agent based on command
        if command == "curl":
            headers = {"User-Agent": "curl/8.4.0"}
        else:
            headers = {"User-Agent": "Wget/1.21.3"}

        try:
            current_url = url

            for _ in range(3):  # redirect limit
                response = requests.get(
                    current_url,
                    allow_redirects=False,
                    headers=headers,
                    timeout=10,
                )

                # Handle redirects manually
                if 300 <= response.status_code < 400:
                    location = response.headers.get("Location")
                    if not location:
                        log.warn("No location header")
                        return None

                    next_url = urljoin(current_url, location)
                    parsed_next = urlparse(next_url)

                    if not parsed_next.hostname or self._is_blocked_host(
                        parsed_next.hostname
                    ):
                        log.warn(
                            f"Redirect blocked: host {parsed_next.hostname!r} is local/private"
                        )
                        return None

                    current_url = next_url
                    continue

                if response.status_code != 200:
                    log.warn(
                        f"Download failed: HTTP {response.status_code} for {current_url}"
                    )
                    return None

                content = response.content

                with open(output_path, "wb") as f:
                    f.write(content)

                return {
                    "url": current_url,
                    "status": response.status_code,
                    "size": len(content),
                }

            log.warn(f"Download failed: too many redirects for {url}")
            return None

        except Exception as e:
            log.warn(f"Download failed: {e}")
            return None

    def handle_wget(self, args: list, pwd: str = "/root") -> tuple[str, dict]:
        url = None
        output_file = None
        stdout = False

        i = 0
        while i < len(args):
            arg = args[i]

            if arg.startswith(("http://", "https://", "ftp://")):
                url = arg
            elif not arg.startswith("-") and ("." in arg or "/" in arg or ":" in arg):
                url = "http://" + arg
            elif arg in (">", ">>"):
                stdout = False
                if i + 1 < len(args):
                    output_file = args[i + 1]
                    i += 1
            elif arg == "-O":
                if i + 1 < len(args):
                    if args[i + 1] == "-":
                        stdout = True
                        output_file = None
                    else:
                        stdout = False
                        output_file = args[i + 1]
                    i += 1
            elif arg == "-o":
                if i + 1 < len(args):
                    stdout = False
                    output_file = args[i + 1]
                    i += 1
            elif arg.startswith(("-O=", "-o=")):
                stdout = False
                output_file = arg.split("=", 1)[1]
            i += 1

        if not url:
            return ("wget: missing URL\n", {})

        parsed = urlparse(url)
        domain = parsed.hostname or "unknown"

        filename = os.path.basename(output_file) if output_file else "index.html"

        downloads_dir = os.path.join(LOG_DIR, f"{self.output}_downloads")
        os.makedirs(downloads_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(downloads_dir, f"{domain}_{timestamp}_{filename}")

        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        result = self.handle_downloads(url, output_path, command="wget")

        if not result:
            return (f"--{start_time}--  {url}\nERROR: download failed\n", {})

        size = result["size"]

        # Fake resolving IP
        try:
            ip = socket.gethostbyname(domain)
        except Exception:
            ip = "0.0.0.0"

        # Simulated progress
        progress = f"{filename:<20} 100%[===================>] {size} bytes"

        response = (
            f"--{start_time}--  {url}\n"
            f"Resolving {domain}... {ip}\n"
            f"Connecting to {domain}... connected.\n"
            f"HTTP request sent, awaiting response... {result['status']} OK\n"
            f"Length: {size}\n"
            f"Saving to: '{filename}'\n\n"
            f"{progress}\n\n"
            f"{start_time} - '{filename}' saved [{size}/{size}]\n"
        )

        # If stdout (-O -), include content but don't add to filesystem
        if stdout:
            try:
                with open(output_path, "r") as f:
                    content = f.read()
                os.remove(output_path)
                return (content + response, {})
            except:
                return (response, {})

        # Add downloaded file to filesystem
        modified = datetime.now().strftime("%b %d %H:%M")
        try:
            with open(output_path, "r") as f:
                file_content = f.read()
        except:
            file_content = ""
        fs_entry = {
            "type": "file",
            "permissions": "-rw-r--r--",
            "owner": "root",
            "group": "root",
            "modified": modified,
            "size": str(size),
            "content": file_content,
        }

        return (response, {f"{pwd}/{filename}": fs_entry})

    def handle_curl(self, args: list, pwd: str = "/root") -> tuple[str, dict]:
        url = None
        output_file = None
        stdout = True  # curl defaults to stdout

        i = 0
        while i < len(args):
            arg = args[i]

            if arg.startswith(("http://", "https://", "ftp://")):
                url = arg
            elif not arg.startswith("-") and ("." in arg or "/" in arg or ":" in arg):
                url = "http://" + arg
            elif arg in (">", ">>"):
                stdout = False
                if i + 1 < len(args):
                    output_file = args[i + 1]
                    i += 1
            elif arg == "-o":
                if i + 1 < len(args):
                    if args[i + 1] == "-":
                        stdout = True
                        output_file = None
                    else:
                        stdout = False
                        output_file = args[i + 1]
                    i += 1
            elif arg == "-O":
                if i + 1 < len(args):
                    if args[i + 1] == "-":
                        stdout = True
                    else:
                        stdout = False
                        output_file = args[i + 1]
                    i += 1
            elif arg.startswith(("-o=", "-O=")):
                stdout = False
                output_file = arg.split("=", 1)[1]
            i += 1

        if not url:
            return ("curl: (2) no URL specified\n", {})

        filename = os.path.basename(output_file) if output_file else "output"

        downloads_dir = os.path.join(LOG_DIR, f"{self.output}_downloads")
        os.makedirs(downloads_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(downloads_dir, f"{timestamp}_{filename}")

        result = self.handle_downloads(url, output_path, command="curl")

        if not result:
            return ("curl: (7) Failed to connect\n", {})

        size = result["size"]

        # Fake speed
        speed = random.randint(5000, 50000)

        progress = (
            "% Total    % Received % Xferd  Average Speed   Time    Time     Time  Current\n"
            "                                 Dload  Upload   Total   Spent   Left  Speed\n\n"
            f"100 {size:6}  100 {size:6}    0     0  {speed:6}      0 --:--:-- --:--:-- --:--:-- {speed}\n"
        )

        # If stdout or no output file, include content but don't add to filesystem
        if stdout:
            try:
                with open(output_path, "r") as f:
                    content = f.read()
                os.remove(output_path)
                return (content + progress, {})
            except:
                return (progress, {})

        # Add downloaded file to filesystem
        modified = datetime.now().strftime("%b %d %H:%M")
        try:
            with open(output_path, "r") as f:
                file_content = f.read()
        except:
            file_content = ""
        fs_entry = {
            "type": "file",
            "permissions": "-rw-r--r--",
            "owner": "root",
            "group": "root",
            "modified": modified,
            "size": str(size),
            "content": file_content,
        }

        return (progress, {f"{pwd}/{filename}": fs_entry})
