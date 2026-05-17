import os
import re
import fnmatch
from datetime import datetime

from utils import USER, motd

filesystem = {
    "/": {
        "type": "dir",
        "permissions": "drwxr-xr-x",
        "owner": "root",
        "group": "root",
        "modified": "2025-01-15",
        "content": {
            "bin": {
                "type": "symlink",
                "target": "/usr/bin",
                "permissions": "lrwxrwxrwx",
                "owner": "root",
                "group": "root",
                "modified": "2025-01-15",
            },
            "sbin": {
                "type": "symlink",
                "target": "/usr/sbin",
                "permissions": "lrwxrwxrwx",
                "owner": "root",
                "group": "root",
                "modified": "2025-01-15",
            },
            "boot": {
                "type": "dir",
                "permissions": "drwxr-xr-x",
                "owner": "root",
                "group": "root",
                "modified": "2025-06-20",
                "size": "4096",
                "content": {},
            },
            "dev": {
                "type": "dir",
                "permissions": "drwxr-xr-x",
                "owner": "root",
                "group": "root",
                "modified": "2025-01-15",
                "size": "4096",
                "content": {
                    "null": {
                        "type": "char_device",
                        "permissions": "crw-rw-rw-",
                        "owner": "root",
                        "group": "root",
                        "modified": "2025-01-15",
                        "size": "0",
                    },
                    "zero": {
                        "type": "char_device",
                        "permissions": "crw-rw-rw-",
                        "owner": "root",
                        "group": "root",
                        "modified": "2025-01-15",
                        "size": "0",
                    },
                    "tty": {
                        "type": "char_device",
                        "permissions": "crw-rw-rw-",
                        "owner": "root",
                        "group": "root",
                        "modified": "2025-01-15",
                        "size": "0",
                    },
                },
            },
            "etc": {
                "type": "dir",
                "permissions": "drwxr-xr-x",
                "owner": "root",
                "group": "root",
                "modified": "2025-04-10",
                "size": "4096",
                "content": {
                    "motd": {
                        "type": "file",
                        "permissions": "-rw-r--r--",
                        "owner": "root",
                        "group": "root",
                        "modified": "2025-03-22",
                        "size": "2KB",
                        "content": motd(),
                    },
                    "passwd": {
                        "type": "file",
                        "permissions": "-rw-r--r--",
                        "owner": "root",
                        "group": "root",
                        "modified": "2025-03-22",
                        "size": "2KB",
                    },
                    "hosts": {
                        "type": "file",
                        "permissions": "-rw-r--r--",
                        "owner": "root",
                        "group": "root",
                        "modified": "2025-01-15",
                        "size": "1KB",
                    },
                    "ssh": {
                        "type": "dir",
                        "permissions": "drwx------",
                        "owner": "root",
                        "group": "root",
                        "modified": "2025-02-01",
                        "size": "4096",
                        "content": {
                            "sshd_config": {
                                "type": "file",
                                "permissions": "-rw-------",
                                "owner": "root",
                                "group": "root",
                                "modified": "2025-02-01",
                                "size": "3KB",
                            }
                        },
                    },
                },
            },
            "home": {
                "type": "dir",
                "permissions": "drwxr-xr-x",
                "owner": "root",
                "group": "root",
                "modified": "2025-01-15",
                "size": "4096",
                "content": {
                    USER: {
                        "type": "dir",
                        "permissions": "drwxr-xr-x",
                        "owner": "user",
                        "group": "user",
                        "modified": "2025-04-05",
                        "size": "4096",
                        "content": {
                            ".bashrc": {
                                "type": "file",
                                "permissions": "-rw-r--r--",
                                "owner": "user",
                                "group": "user",
                                "modified": "2025-04-05",
                                "size": "1KB",
                                "content": "# ~/.bashrc\n[ -z \"$PS1\" ] && return\nHISTCONTROL=ignoreboth\nshopt -s histappend checkwinsize\nHISTSIZE=1000\nHISTFILESIZE=2000\nif [ -x /usr/bin/dircolors ]; then\n    eval \"$(dircolors -b)\"\n    alias ls='ls --color=auto'\nfi\nalias ll='ls -alF'\nalias la='ls -A'\nPS1='\\[\\033[01;32m\\]\\u@\\h\\[\\033[00m\\]:\\[\\033[01;34m\\]\\w\\[\\033[00m\\]\\$ '\n"
                            },
                        },
                    }
                },
            },
            "lib": {
                "type": "symlink",
                "target": "/usr/lib",
                "permissions": "lrwxrwxrwx",
                "owner": "root",
                "group": "root",
                "modified": "2025-01-15",
            },
            "lib64": {
                "type": "symlink",
                "target": "/usr/lib64",
                "permissions": "lrwxrwxrwx",
                "owner": "root",
                "group": "root",
                "modified": "2025-01-15",
            },
            "media": {
                "type": "dir",
                "permissions": "drwxr-xr-x",
                "owner": "root",
                "group": "root",
                "modified": "2025-01-15",
                "size": "4096",
                "content": {},
            },
            "mnt": {
                "type": "dir",
                "permissions": "drwxr-xr-x",
                "owner": "root",
                "group": "root",
                "modified": "2025-01-15",
                "size": "4096",
                "content": {},
            },
            "opt": {
                "type": "dir",
                "permissions": "drwxr-xr-x",
                "owner": "root",
                "group": "root",
                "modified": "2025-01-15",
                "size": "4096",
                "content": {},
            },
            "proc": {
                "type": "dir",
                "permissions": "dr-xr-xr-x",
                "owner": "root",
                "group": "root",
                "modified": "2025-01-15",
                "size": "4096",
                "content": {},
            },
            "root": {
                "type": "dir",
                "permissions": "drwx------",
                "owner": "root",
                "group": "root",
                "modified": "2025-04-18",
                "size": "4096",
                "content": {},
            },
            "run": {
                "type": "dir",
                "permissions": "drwxr-xr-x",
                "owner": "root",
                "group": "root",
                "modified": "2025-04-21",
                "size": "4096",
                "content": {
                    "utmp": {
                        "type": "file",
                        "permissions": "-rw-rw-r--",
                        "owner": "root",
                        "group": "utmp",
                        "modified": "2025-04-21",
                        "size": "1KB",
                    }
                },
            },
            "srv": {
                "type": "dir",
                "permissions": "drwxr-xr-x",
                "owner": "root",
                "group": "root",
                "modified": "2025-01-15",
                "size": "4096",
                "content": {},
            },
            "sys": {
                "type": "dir",
                "permissions": "dr-xr-xr-x",
                "owner": "root",
                "group": "root",
                "modified": "2025-01-15",
                "size": "4096",
                "content": {},
            },
            "tmp": {
                "type": "dir",
                "permissions": "drwxrwxrwt",
                "owner": "root",
                "group": "root",
                "modified": "2025-04-21",
                "size": "4096",
                "content": {},
            },
            "usr": {
                "type": "dir",
                "permissions": "drwxr-xr-x",
                "owner": "root",
                "group": "root",
                "modified": "2025-01-15",
                "size": "4096",
                "content": {},
            },
            "var": {
                "type": "dir",
                "permissions": "drwxr-xr-x",
                "owner": "root",
                "group": "root",
                "modified": "2025-01-15",
                "size": "4096",
                "content": {
                    "log": {
                        "type": "dir",
                        "permissions": "drwxr-xr-x",
                        "owner": "root",
                        "group": "root",
                        "modified": "2025-01-15",
                        "size": "4096",
                        "content": {},
                    },
                },
            },
        },
    }
}


class Filesystem:
    def __init__(self, filesystem: dict):
        self.fs = filesystem

    def _now(self) -> str:
        return datetime.now().strftime("%b %d %H:%M")

    def _resolve(self, path: str) -> str:
        """Resolve . and .. components in a path."""
        parts = []
        for part in path.split("/"):
            if part == "" or part == ".":
                continue
            elif part == "..":
                if parts:
                    parts.pop()
            else:
                parts.append(part)
        return "/" + "/".join(parts)

    def resolve_glob(self, pattern: str, cwd: str = "/") -> list[str]:
        """Resolve a glob pattern against the filesystem, returning matching paths."""
        if not pattern.startswith("/"):
            pattern = os.path.join(cwd, pattern)
        resolved = self._resolve(pattern)
        if not any(c in resolved for c in "*?["):
            return [resolved]

        parent, glob_part = os.path.split(resolved)
        if not parent:
            parent = "/"
        try:
            parent_node = self._walk(parent)
        except KeyError:
            return []
        if parent_node.get("type") != "dir":
            return []

        children = parent_node.get("content", {})
        if not isinstance(children, dict):
            return []

        matches = []
        for name, entry in children.items():
            if entry.get("type") == "deleted":
                continue
            if fnmatch.fnmatch(name, glob_part):
                matches.append(os.path.join(parent, name))
        return sorted(matches)

    def _walk(self, path: str) -> dict:
        """Resolve a path to its node, raising KeyError if not found."""
        parts = [p for p in path.split("/") if p]
        node = self.fs["/"]
        for part in parts:
            content = node.get("content")
            if not isinstance(content, dict) or part not in content:
                raise KeyError(f"Path not found: {path!r} (missing {part!r})")
            node = content[part]
            if node.get("type") == "deleted":
                raise KeyError(f"Path not found: {path!r} (deleted)")
        return node

    def get(self, path: str) -> dict:
        path = self._resolve(path)
        if path == "/":
            return self.fs["/"]
        node = self._walk(path)
        if callable(node.get("content")):
            node["content"] = node["content"]()
        return node

    _IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")

    def is_path(self, token: str) -> bool:
        if self._IP_RE.match(token):
            return False
        if " " in token:
            return (
                token.startswith("/")
                or token.startswith("./")
                or token.startswith("../")
            )
        return (
            token.startswith("/")
            or token.startswith("./")
            or token.startswith("../")
            or "/" in token
            or ("." in os.path.basename(token) and not token.startswith("-"))
        )

    def path_info(self, path: str) -> str:
        try:
            node = self.get(path)
            if node.get("type") == "dir":
                children = {
                    name: {
                        k: (v if k != "content" else "<content_trimmed>")
                        for k, v in entry.items()
                    }
                    for name, entry in node.get("content", {}).items()
                }
                return f"Directory listing for {path}: {children}"
            else:
                return f"listing for {path}: {node}"
        except KeyError:
            return ""

    def put(self, path: str, entry: dict) -> None:
        """
        Insert or merge entry at path, creating any missing parent dirs.

        entry should contain at least 'type' ('file' or 'dir') and 'content'.
        If the node already exists its fields are merged (new values win);
        dict contents are deep-merged so existing children are preserved.
        """
        parts = [p for p in path.split("/") if p]
        if not parts:
            return  # refuse to overwrite root

        name = parts[-1]
        node = self.fs["/"]

        # Walk / create intermediate dirs
        for part in parts[:-1]:
            if "content" not in node or not isinstance(node["content"], dict):
                node["content"] = {}
            if part not in node["content"]:
                node["content"][part] = {
                    "type": "dir",
                    "content": {},
                    "modified": self._now(),
                }
            node = node["content"][part]

        if "content" not in node or not isinstance(node["content"], dict):
            node["content"] = {}

        existing = node["content"].get(name)
        entry["modified"] = self._now()

        if existing:
            # Deep-merge dict contents (e.g. directory children)
            if isinstance(existing.get("content"), dict) and isinstance(
                entry.get("content"), dict
            ):
                existing["content"].update(entry["content"])
            node["content"][name] = {**existing, **entry}
        else:
            # Sensible defaults for new nodes
            if entry.get("type") == "dir" and "content" not in entry:
                entry["content"] = {}
            elif entry.get("type", "file") == "file" and "content" not in entry:
                entry["content"] = ""
            node["content"][name] = entry

    def add_content(self, full_path: str, content: str, state: dict = None) -> None:
        """Create or overwrite a file with content, auto-generating metadata.
        State is a dict with USER key for owner/group; defaults to root.
        """
        owner = state.get("USER", "root") if state else "root"
        self.put(full_path, {
            "type": "file",
            "permissions": "-rw-r--r--",
            "owner": owner,
            "group": owner,
            "modified": self._now(),
            "size": str(int(len(content) / 1024) + 1) + "KB",
            "content": content,
        })


if __name__ == "__main__":
    import pickle

    with open("data/filesystem.pkl", "wb") as pklw:
        pickle.dump(filesystem, pklw)
