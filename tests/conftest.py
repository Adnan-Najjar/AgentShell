import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from unittest.mock import patch, MagicMock

_patcher = patch("requests.get", return_value=MagicMock(text="1.2.3.4"))
_patcher.start()

from filesystem import Filesystem
from tools import Tools


SAMPLE_FS = {
    "/": {
        "type": "dir",
        "content": {
            "bin": {
                "type": "dir",
                "content": {
                    "sh": {
                        "type": "file",
                        "content": "",
                        "permissions": "-rwxr-xr-x",
                        "owner": "root",
                        "group": "root",
                        "modified": "2025-01-01",
                        "size": "1MB",
                    },
                    "ls": {
                        "type": "file",
                        "content": "",
                        "permissions": "-rwxr-xr-x",
                        "owner": "root",
                        "group": "root",
                        "modified": "2025-01-01",
                        "size": "500KB",
                    },
                },
            },
            "usr": {
                "type": "dir",
                "content": {
                    "bin": {
                        "type": "dir",
                        "content": {
                            "python": {
                                "type": "file",
                                "content": "",
                                "permissions": "-rwxr-xr-x",
                                "owner": "root",
                                "group": "root",
                                "modified": "2025-01-01",
                                "size": "10MB",
                            },
                            "gcc": {
                                "type": "file",
                                "content": "",
                                "permissions": "-rwxr-xr-x",
                                "owner": "root",
                                "group": "root",
                                "modified": "2025-01-01",
                                "size": "5MB",
                            },
                        },
                    },
                },
            },
            "home": {
                "type": "dir",
                "content": {
                    "user": {
                        "type": "dir",
                        "content": {
                            "file.txt": {
                                "type": "file",
                                "content": "hello world",
                                "permissions": "-rw-r--r--",
                                "owner": "user",
                                "group": "user",
                                "modified": "2025-01-01",
                                "size": "1KB",
                            },
                            "script.sh": {
                                "type": "file",
                                "content": "echo hi",
                                "permissions": "-rwxr-xr-x",
                                "owner": "user",
                                "group": "user",
                                "modified": "2025-01-01",
                                "size": "100B",
                            },
                        },
                    },
                },
            },
            "etc": {
                "type": "dir",
                "content": {
                    "passwd": {
                        "type": "file",
                        "content": "user:x:1000:1000::/home/user:/bin/sh\n",
                        "permissions": "-rw-r--r--",
                        "owner": "root",
                        "group": "root",
                        "modified": "2025-01-01",
                        "size": "2KB",
                    },
                    "hosts": {
                        "type": "file",
                        "content": "127.0.0.1 localhost\n",
                        "permissions": "-rw-r--r--",
                        "owner": "root",
                        "group": "root",
                        "modified": "2025-01-01",
                        "size": "1KB",
                    },
                },
            },
            "tmp": {
                "type": "dir",
                "content": {},
            },
            "var": {
                "type": "dir",
                "content": {
                    "log": {
                        "type": "dir",
                        "content": {},
                    },
                },
            },
        },
    },
}


import copy


def sample_filesystem() -> Filesystem:
    return Filesystem(copy.deepcopy(SAMPLE_FS))


def state() -> dict:
    return {
        "HOSTNAME": "testhost",
        "USER": "user",
        "HOME": "/home/user",
        "LOGNAME": "user",
        "PWD": "/home/user",
        "_": "/bin/sh",
        "?": "0",
        "IS_ROOT": False,
        "filesystem": {},
    }


def root_state() -> dict:
    s = state()
    s["USER"] = "root"
    s["HOME"] = "/root"
    s["IS_ROOT"] = True
    s["PWD"] = "/root"
    return s


def tools_instance() -> Tools:
    return Tools("127.0.0.1")
