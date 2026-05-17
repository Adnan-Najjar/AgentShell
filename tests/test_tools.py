import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(__file__))
from conftest import tools_instance, state, root_state, sample_filesystem


class TestToolsValidateCommand(unittest.TestCase):
    def setUp(self):
        self.tools = tools_instance()

    def test_validate_existing(self):
        valid, msg = self.tools.validate_command("ls")
        self.assertTrue(valid)
        self.assertEqual(msg, "")

    def test_validate_existing_with_arg(self):
        valid, msg = self.tools.validate_command("echo hello")
        self.assertTrue(valid)

    def test_validate_missing(self):
        valid, msg = self.tools.validate_command("zzznotacmd")
        self.assertFalse(valid)
        self.assertIn("not found", msg)


class TestToolsHandleEnv(unittest.TestCase):
    def setUp(self):
        self.tools = tools_instance()
        self.state = state()

    def test_env_no_args_returns_all(self):
        result = self.tools.handle_env([], self.state)
        self.assertIn("TERM=linux", result)

    def test_env_specific_var(self):
        result = self.tools.handle_env(["TERM"], self.state)
        self.assertEqual(result, "linux")

    def test_env_with_equals(self):
        result = self.tools.handle_env(["FOO=bar"], self.state)
        self.assertEqual(result, "FOO=bar")

    def test_env_hostname(self):
        result = self.tools.handle_env(["HOSTNAME"], self.state)
        self.assertEqual(result, "testhost")


class TestToolsHandleExport(unittest.TestCase):
    def setUp(self):
        self.tools = tools_instance()
        self.state = state()

    def test_export_sets_var(self):
        self.tools.handle_export(["MYVAR=hello"], self.state)
        self.assertEqual(self.state["MYVAR"], "hello")

    def test_export_overwrites(self):
        self.state["EXISTING"] = "old"
        self.tools.handle_export(["EXISTING=new"], self.state)
        self.assertEqual(self.state["EXISTING"], "new")


class TestToolsHandleApt(unittest.TestCase):
    def setUp(self):
        self.tools = tools_instance()

    def test_apt_no_args(self):
        result = self.tools.handle_apt([])
        self.assertIn("apt-get", result)

    def test_apt_update(self):
        result = self.tools.handle_apt(["update"])
        self.assertIn("Reading package lists", result)

    def test_apt_upgrade(self):
        result = self.tools.handle_apt(["upgrade"])
        self.assertIn("0 upgraded", result)

    def test_apt_install(self):
        result = self.tools.handle_apt(["install", "nano"])
        self.assertIn("Unable to locate package nano", result)

    def test_apt_remove(self):
        result = self.tools.handle_apt(["remove", "nano"])
        self.assertIn("Unable to locate package nano", result)


class TestToolsHandleHostname(unittest.TestCase):
    def setUp(self):
        self.tools = tools_instance()
        self.state = state()

    def test_hostname_get(self):
        result = self.tools.handle_hostname([], self.state)
        self.assertIn("testhost", result)

    def test_hostname_set(self):
        self.tools.handle_hostname(["newbox"], self.state)
        self.assertEqual(self.state["HOSTNAME"], "newbox")


class TestToolsHandleSu(unittest.TestCase):
    def setUp(self):
        self.tools = tools_instance()
        self.s = state()

    def test_su_default_root(self):
        self.tools.handle_su([], self.s)
        self.assertEqual(self.s["USER"], "root")
        self.assertTrue(self.s["IS_ROOT"])

    def test_su_root(self):
        self.tools.handle_su(["root"], self.s)
        self.assertEqual(self.s["USER"], "root")
        self.assertEqual(self.s["HOME"], "/root")

    def test_su_user(self):
        self.tools.handle_su(["user"], self.s)
        self.assertEqual(self.s["USER"], "user")
        self.assertEqual(self.s["HOME"], "/home/user")

    def test_su_invalid(self):
        result = self.tools.handle_su(["bob"], self.s)
        self.assertIn("does not exist", result)
        self.assertEqual(self.s["USER"], "user")
        self.assertEqual(self.s["HOME"], "/home/user")
        self.assertFalse(self.s["IS_ROOT"])


class TestToolsHandleExit(unittest.TestCase):
    def setUp(self):
        self.tools = tools_instance()
        self.s = root_state()

    def test_exit_resets_user(self):
        self.tools.handle_exit([], self.s)
        self.assertEqual(self.s["USER"], "user")
        self.assertFalse(self.s["IS_ROOT"])

    def test_exit_resets_home(self):
        self.tools.handle_exit([], self.s)
        self.assertEqual(self.s["HOME"], "/home/user")


class TestToolsHandleCd(unittest.TestCase):
    def setUp(self):
        self.tools = tools_instance()
        self.fs = sample_filesystem()
        self.s = state()

    def test_cd_absolute(self):
        self.tools.handle_cd(["/tmp"], self.s, self.fs)
        self.assertEqual(self.s["PWD"], "/tmp")

    def test_cd_relative(self):
        self.tools.handle_cd([".."], self.s, self.fs)
        self.assertEqual(self.s["PWD"], "/home")

    def test_cd_home(self):
        self.tools.handle_cd(["~"], self.s, self.fs)
        self.assertEqual(self.s["PWD"], "/home/user")

    def test_cd_empty_defaults_home(self):
        self.s["PWD"] = "/tmp"
        self.tools.handle_cd([], self.s, self.fs)
        self.assertEqual(self.s["PWD"], "/home/user")

    def test_cd_dash(self):
        self.s["PWD"] = "/tmp"
        self.tools.handle_cd(["/var"], self.s, self.fs)
        self.tools.handle_cd(["-"], self.s, self.fs)
        self.assertEqual(self.s["PWD"], "/tmp")

    def test_cd_non_existent(self):
        result = self.tools.handle_cd(["/nonexistent"], self.s, self.fs)
        self.assertIn("No such file", result)
        self.assertEqual(self.s["PWD"], "/home/user")

    def test_cd_not_a_dir(self):
        result = self.tools.handle_cd(["/home/user/file.txt"], self.s, self.fs)
        self.assertIn("Not a directory", result)
        self.assertEqual(self.s["PWD"], "/home/user")

    def test_cd_deep_path(self):
        self.tools.handle_cd(["/var/log"], self.s, self.fs)
        self.assertEqual(self.s["PWD"], "/var/log")

    def test_cd_parent_of_root(self):
        self.s["PWD"] = "/"
        self.tools.handle_cd([".."], self.s, self.fs)
        self.assertEqual(self.s["PWD"], "/")


class TestToolsHandleEnvVars(unittest.TestCase):
    def setUp(self):
        self.tools = tools_instance()
        self.s = state()

    def test_expand_user(self):
        result = self.tools.handle_env_vars(["$USER"], self.s)
        self.assertEqual(result, ["user"])

    def test_expand_home(self):
        result = self.tools.handle_env_vars(["$HOME"], self.s)
        self.assertEqual(result, ["/home/user"])

    def test_no_expansion(self):
        result = self.tools.handle_env_vars(["hello"], self.s)
        self.assertEqual(result, ["hello"])

    def test_multiple_args(self):
        result = self.tools.handle_env_vars(["$USER", "$HOSTNAME"], self.s)
        self.assertEqual(result, ["user", "testhost"])

    def test_var_in_middle(self):
        result = self.tools.handle_env_vars(["prefix_${USER}_suffix"], self.s)
        self.assertEqual(result, ["prefix_${USER}_suffix"])

    def test_skips_special_vars(self):
        result = self.tools.handle_env_vars(["$IS_ROOT", "$filesystem"], self.s)
        self.assertEqual(result, ["$IS_ROOT", "$filesystem"])


class TestToolsHandleWget(unittest.TestCase):
    def setUp(self):
        self.tools = tools_instance()

    def test_wget_no_url(self):
        result = self.tools.handle_wget([], "/tmp")
        self.assertIn("missing URL", result)

    def test_wget_simple_url_passed(self):
        result = self.tools.handle_wget(["http://example.com/file"], "/tmp")
        self.assertIsInstance(result, str)


class TestToolsHandleCurl(unittest.TestCase):
    def setUp(self):
        self.tools = tools_instance()

    def test_curl_no_url(self):
        result = self.tools.handle_curl([], "/tmp")
        self.assertIn("no URL", result)

    def test_curl_simple_url_passed(self):
        result = self.tools.handle_curl(["http://example.com/file"], "/tmp")
        self.assertIsInstance(result, str)


if __name__ == "__main__":
    unittest.main()
