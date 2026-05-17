import os
import sys
import unittest
from unittest.mock import patch, MagicMock
import builtins

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

_patcher = patch("requests.get", return_value=MagicMock(text="1.2.3.4"))
_patcher.start()

from conftest import sample_filesystem, state, root_state


class TestParseShell(unittest.TestCase):
    def setUp(self):
        self._openai_patch = patch("main.OpenAI")
        mock_openai = self._openai_patch.start()
        mock_openai.return_value = MagicMock()
        from main import Agent

        self.agent = Agent("127.0.0.1")

    def tearDown(self):
        self._openai_patch.stop()

    def test_parse_simple(self):
        result, paths_list = self.agent.parse_shell("ls -la")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], ["ls", "-la"])

    def test_parse_with_path(self):
        result, paths_list = self.agent.parse_shell("cat /etc/passwd")
        self.assertIn("/etc/passwd", paths_list[0])

    def test_parse_compound_and(self):
        result, paths_list = self.agent.parse_shell("ls && pwd")
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0], ["ls"])
        self.assertEqual(result[1], ["&&"])
        self.assertEqual(result[2], ["pwd"])

    def test_parse_compound_or(self):
        result, paths_list = self.agent.parse_shell("ls || echo fail")
        self.assertEqual(len(result), 3)
        self.assertEqual(result[1], ["||"])

    def test_parse_per_group_paths(self):
        result, paths_list = self.agent.parse_shell("cd /var/log && ls")
        self.assertGreaterEqual(len(paths_list), 2)
        if paths_list[0]:
            self.assertIn("/var/log", paths_list[0])

    def test_parse_dot_slash_resolves(self):
        result, paths_list = self.agent.parse_shell("./script.sh")
        self.assertTrue(result[0][0].startswith(self.agent.current_state["PWD"]))

    def test_parse_for_loop(self):
        result, paths_list = self.agent.parse_shell("for i in 1 2 3; do echo $i; done")
        self.assertIsNone(result)

    def test_parse_while_loop(self):
        result, paths_list = self.agent.parse_shell("while true; do sleep 1; done")
        self.assertIsNone(result)

    def test_parse_if_statement(self):
        result, paths_list = self.agent.parse_shell("if true; then echo yes; fi")
        self.assertIsNone(result)

    def test_parse_brace_group(self):
        result, paths_list = self.agent.parse_shell("{ echo hello; echo world; }")
        self.assertIsNone(result)

    def test_parse_empty(self):
        result, paths_list = self.agent.parse_shell("")
        self.assertEqual(len(result), 0)

    def test_parse_env_var_expanded(self):
        result, paths_list = self.agent.parse_shell("echo $HOME")
        self.assertIn(self.agent.current_state["HOME"], result[0])

    def test_parse_semicolon_separated(self):
        result, paths_list = self.agent.parse_shell("cd /tmp; ls")
        self.assertGreaterEqual(len(result), 3)
        self.assertEqual(result[0], ["cd", "/tmp"])
        self.assertEqual(result[2], ["ls"])

    def test_parse_pipe(self):
        result, paths_list = self.agent.parse_shell("ls | grep foo")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], ["ls", "|", "grep", "foo"])

    def test_parse_pipe_no_spaces(self):
        result, paths_list = self.agent.parse_shell("ls|grep foo")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], ["ls", "|", "grep", "foo"])

    def test_parse_pipe_and_operator(self):
        result, paths_list = self.agent.parse_shell("ls | grep foo && pwd")
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0], ["ls", "|", "grep", "foo"])
        self.assertEqual(result[1], ["&&"])
        self.assertEqual(result[2], ["pwd"])

    def test_parse_cmd_substitution(self):
        result, paths_list = self.agent.parse_shell("echo $(whoami)")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], ["echo", "$(whoami)"])

    def test_parse_var_expansion_not_caught(self):
        result, paths_list = self.agent.parse_shell("echo $HOME")
        self.assertEqual(result[0], ["echo", self.agent.current_state["HOME"]])

    def test_parse_background_not_caught(self):
        result, paths_list = self.agent.parse_shell("sleep 5 &")
        self.assertEqual(result[0], ["sleep", "5", "&"])

    def test_parse_redirect_ampersand(self):
        result, paths_list = self.agent.parse_shell("nc -z host 2>&1")
        self.assertEqual(result[0], ["nc", "-z", "host", "2>&1"])

    def test_parse_simple_redirect_not_caught(self):
        result, paths_list = self.agent.parse_shell("echo hello > /tmp/file")
        self.assertEqual(result[0], ["echo", "hello", ">", "/tmp/file"])
        self.assertEqual(paths_list, [{"/tmp/file"}])

    def test_parse_redirect_both(self):
        result, paths_list = self.agent.parse_shell("echo hello &> /dev/null")
        self.assertEqual(result[0], ["echo", "hello", "&>", "/dev/null"])
        self.assertEqual(paths_list, [{"/dev/null"}])

    def test_parse_complex(self):
        result, paths_list = self.agent.parse_shell(
            "useradd -m -p \"$(openssl passwd -1 'password')\" john"
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0],
            ["useradd", "-m", "-p", "$(openssl passwd -1 'password')", "john"],
        )


class TestHandleCommand(unittest.TestCase):
    def setUp(self):
        self._openai_patch = patch("main.OpenAI")
        mock_openai = self._openai_patch.start()
        mock_openai.return_value = MagicMock()
        from main import Agent

        self.agent = Agent("127.0.0.1")
        self.agent.filesystem = sample_filesystem()

    def tearDown(self):
        self._openai_patch.stop()

    def test_handle_cd(self):
        result = self.agent.handle_command("cd", ["/tmp"])
        self.assertEqual(self.agent.current_state["PWD"], "/tmp")
        self.assertEqual(result, "")

    def test_handle_pwd(self):
        result = self.agent.handle_command("pwd", [])
        self.assertIn(self.agent.current_state["PWD"], result)

    def test_handle_export(self):
        result = self.agent.handle_command("export", ["FOO=bar"])
        self.assertEqual(result, "")
        self.assertEqual(self.agent.current_state["FOO"], "bar")

    def test_handle_env(self):
        result = self.agent.handle_command("env", [])
        self.assertIn("TERM=linux", result)

    def test_handle_hostname(self):
        result = self.agent.handle_command("hostname", [])
        self.assertIn("prod", result)

    def test_handle_su(self):
        self.agent.current_state["IS_ROOT"] = False
        self.agent.current_state["USER"] = "user"
        result = self.agent.handle_command("su", ["root"])
        self.assertTrue(self.agent.current_state["IS_ROOT"])
        self.assertEqual(self.agent.current_state["USER"], "root")
        self.assertEqual(self.agent.current_state["HOME"], "/root")

    def test_handle_exit(self):
        self.agent.current_state["IS_ROOT"] = False
        self.agent.current_state["USER"] = "user"
        self.agent.current_state["HOME"] = "/home/user"
        self.agent.handle_command("su", ["root"])
        self.agent.handle_command("exit", [])
        self.assertFalse(self.agent.current_state["IS_ROOT"])
        self.assertEqual(self.agent.current_state["USER"], "user")
        self.assertEqual(self.agent.current_state["HOME"], "/home/user")

    def test_handle_history(self):
        self.agent.history = ["ls", "pwd"]
        result = self.agent.handle_command("history", [])
        self.assertIn("ls", result)
        self.assertIn("pwd", result)

    def test_handle_history_clear(self):
        self.agent.history = ["ls", "pwd"]
        self.agent.handle_command("history", ["-c"])
        self.assertEqual(self.agent.history, [])

    def test_handle_apt(self):
        result = self.agent.handle_command("apt", [])
        self.assertIn("apt-get", result)

    def test_handle_invalid(self):
        result = self.agent.handle_command("zzznotacmd", [])
        self.assertIsNotNone(result)
        self.assertIn("not found", result)

    def test_handle_script_path_returns_none(self):
        result = self.agent.handle_command("/home/user/script.sh", [])
        self.assertIsNone(result)

    def test_handle_script_with_dot_slash(self):
        self.agent.current_state["PWD"] = "/home/user"
        result = self.agent.handle_command("/home/user/script.sh", [])
        self.assertIsNone(result)

    def test_handle_sudo_builtin(self):
        self.agent.current_state["IS_ROOT"] = False
        result = self.agent.handle_command("sudo", ["apt", "update"])
        self.assertTrue(self.agent.current_state["IS_ROOT"])
        self.assertTrue(len(result) > 0)

    def test_handle_sudo_unknown(self):
        self.agent.current_state["IS_ROOT"] = False
        result = self.agent.handle_command("sudo", ["/usr/bin/env"])
        self.assertTrue(self.agent.current_state["IS_ROOT"])
        self.assertIsNone(result)

    def test_handle_sudo_already_root(self):
        self.agent.current_state["IS_ROOT"] = True
        result = self.agent.handle_command("sudo", ["apt", "update"])
        self.assertTrue(self.agent.current_state["IS_ROOT"])
        self.assertTrue(len(result) > 0)

    def test_handle_sudo_cd(self):
        self.agent.current_state["IS_ROOT"] = False
        result = self.agent.handle_command("sudo", ["cd", "/var/log"])
        self.assertTrue(self.agent.current_state["IS_ROOT"])
        self.assertEqual(self.agent.current_state["PWD"], "/var/log")


class TestHandleHistory(unittest.TestCase):
    def setUp(self):
        self._openai_patch = patch("main.OpenAI")
        mock_openai = self._openai_patch.start()
        mock_openai.return_value = MagicMock()
        from main import Agent

        self.agent = Agent("127.0.0.1")

    def tearDown(self):
        self._openai_patch.stop()

    def test_empty(self):
        self.assertEqual(self.agent.handle_history([]), "")

    def test_with_entries(self):
        self.agent.history = ["ls", "pwd", "cd /tmp"]
        result = self.agent.handle_history([])
        lines = result.strip().split("\n")
        self.assertEqual(len(lines), 3)
        self.assertIn("ls", lines[0])
        self.assertIn("pwd", lines[1])

    def test_clear_flag(self):
        self.agent.history = ["ls", "pwd"]
        self.agent.handle_history(["-c"])
        self.assertEqual(self.agent.history, [])


class TestShellPrompt(unittest.TestCase):
    def setUp(self):
        self._openai_patch = patch("main.OpenAI")
        mock_openai = self._openai_patch.start()
        mock_openai.return_value = MagicMock()
        from main import Agent

        self.agent = Agent("127.0.0.1")

    def tearDown(self):
        self._openai_patch.stop()

    def test_user_prompt(self):
        prompt = self.agent._shell_prompt(self.agent.current_state)
        expected_suffix = "# " if self.agent.current_state["IS_ROOT"] else "$ "
        self.assertTrue(prompt.endswith(expected_suffix))

    def test_root_prompt(self):
        s = self.agent.current_state.copy()
        s["IS_ROOT"] = True
        prompt = self.agent._shell_prompt(s)
        self.assertTrue(prompt.endswith("# "))

    def test_home_substitution(self):
        self.agent.current_state["PWD"] = self.agent.current_state["HOME"]
        prompt = self.agent._shell_prompt(self.agent.current_state)
        self.assertIn("~", prompt)

    def test_custom_user(self):
        s = {
            "USER": "admin",
            "HOSTNAME": "server",
            "PWD": "/var/log",
            "HOME": "/home/admin",
            "IS_ROOT": False,
        }
        prompt = self.agent._shell_prompt(s)
        self.assertEqual(prompt, "admin@server:/var/log$ ")


class TestFormatState(unittest.TestCase):
    def setUp(self):
        self._openai_patch = patch("main.OpenAI")
        mock_openai = self._openai_patch.start()
        mock_openai.return_value = MagicMock()
        from main import Agent

        self.agent = Agent("127.0.0.1")

    def tearDown(self):
        self._openai_patch.stop()

    def test_format_state(self):
        formatted = self.agent._format_state()
        self.assertIn("user=", formatted)
        self.assertIn("hostname=", formatted)
        self.assertIn("pwd=", formatted)
        self.assertIn("is_root=", formatted)


class TestSaveToFs(unittest.TestCase):
    def setUp(self):
        self._openai_patch = patch("main.OpenAI")
        mock_openai = self._openai_patch.start()
        mock_openai.return_value = MagicMock()
        from main import Agent

        self.agent = Agent("127.0.0.1")

    def tearDown(self):
        self._openai_patch.stop()

    def test_save_empty_dict(self):
        self.agent.filesystem = sample_filesystem()
        before = self.agent.filesystem.get("/etc/hosts")
        self.agent.save_to_fs({})
        after = self.agent.filesystem.get("/etc/hosts")
        self.assertEqual(before, after)

    def test_save_new_file(self):
        self.agent.filesystem = sample_filesystem()
        self.agent.save_to_fs(
            {
                "/tmp/test.txt": {
                    "type": "file",
                    "content": "test content",
                    "permissions": "-rw-r--r--",
                    "owner": "user",
                    "group": "user",
                }
            }
        )
        node = self.agent.filesystem.get("/tmp/test.txt")
        self.assertEqual(node["content"], "test content")

    def test_save_root_ignored(self):
        self.agent.filesystem = sample_filesystem()
        original = self.agent.filesystem.get("/")
        self.agent.save_to_fs({"/": {"type": "file", "content": "hacked"}})
        after = self.agent.filesystem.get("/")
        self.assertEqual(original, after)


if __name__ == "__main__":
    unittest.main()
