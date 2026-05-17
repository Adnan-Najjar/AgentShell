import unittest
import os, sys

sys.path.insert(0, os.path.dirname(__file__))
from conftest import sample_filesystem


class TestFilesystemResolve(unittest.TestCase):
    def setUp(self):
        self.fs = sample_filesystem()

    def test_resolve_simple(self):
        self.assertEqual(self.fs._resolve("/home/user"), "/home/user")

    def test_resolve_root(self):
        self.assertEqual(self.fs._resolve("/"), "/")

    def test_resolve_dot(self):
        self.assertEqual(self.fs._resolve("/home/./user"), "/home/user")

    def test_resolve_double_dot(self):
        self.assertEqual(self.fs._resolve("/home/user/.."), "/home")

    def test_resolve_trailing(self):
        self.assertEqual(self.fs._resolve("/home/user/"), "/home/user")

    def test_resolve_glob_absolute_prefix(self):
        self.assertEqual(self.fs.resolve_glob("/*bin"), ["/bin"])

    def test_resolve_glob_wildcard_suffix(self):
        self.assertEqual(self.fs.resolve_glob("/usr/bin/*"),
                         ["/usr/bin/gcc", "/usr/bin/python"])

    def test_resolve_glob_dot_star(self):
        self.assertEqual(self.fs.resolve_glob("*.txt", cwd="/home/user"),
                         ["/home/user/file.txt"])

    def test_resolve_glob_doublestar(self):
        self.assertEqual(self.fs._resolve("**/"), "/**")

    def test_resolve_glob_path_wildcard(self):
        self.assertEqual(self.fs.resolve_glob("*.sh", cwd="/home/user"),
                         ["/home/user/script.sh"])


class TestFilesystemWalk(unittest.TestCase):
    def setUp(self):
        self.fs = sample_filesystem()

    def test_walk_root(self):
        node = self.fs._walk("/")
        self.assertEqual(node["type"], "dir")

    def test_walk_existing(self):
        node = self.fs._walk("/home/user")
        self.assertEqual(node["type"], "dir")

    def test_walk_file(self):
        node = self.fs._walk("/home/user/file.txt")
        self.assertEqual(node["type"], "file")
        self.assertEqual(node["content"], "hello world")

    def test_walk_missing(self):
        with self.assertRaises(KeyError):
            self.fs._walk("/nonexistent")

    def test_walk_deep_missing(self):
        with self.assertRaises(KeyError):
            self.fs._walk("/home/user/missing/file")

    def test_walk_deleted_raises(self):
        self.fs.put(
            "/tmp/secret.txt",
            {
                "type": "deleted",
            },
        )
        with self.assertRaises(KeyError):
            self.fs._walk("/tmp/secret.txt")

    def test_walk_deleted_parent_cascades(self):
        self.fs.put(
            "/tmp/olddir",
            {
                "type": "deleted",
            },
        )
        with self.assertRaises(KeyError):
            self.fs._walk("/tmp/olddir/child")


class TestFilesystemGet(unittest.TestCase):
    def setUp(self):
        self.fs = sample_filesystem()

    def test_get_root(self):
        node = self.fs.get("/")
        self.assertEqual(node["type"], "dir")

    def test_get_file(self):
        node = self.fs.get("/home/user/file.txt")
        self.assertEqual(node["content"], "hello world")

    def test_get_missing(self):
        with self.assertRaises(KeyError):
            self.fs.get("/ghost")

    def test_get_with_dots_in_path(self):
        node = self.fs.get("/home/./user/../user/file.txt")
        self.assertEqual(node["content"], "hello world")

    def test_get_deleted_raises(self):
        self.fs.put(
            "/tmp/gone.txt",
            {
                "type": "deleted",
            },
        )
        with self.assertRaises(KeyError):
            self.fs.get("/tmp/gone.txt")

    def test_put_overrides_deleted(self):
        self.fs.put("/tmp/gone.txt", {"type": "deleted"})
        self.fs.put("/tmp/gone.txt", {"type": "file", "content": "restored"})
        node = self.fs.get("/tmp/gone.txt")
        self.assertEqual(node["content"], "restored")
        self.assertEqual(node["type"], "file")


class TestFilesystemIsPath(unittest.TestCase):
    def setUp(self):
        self.fs = sample_filesystem()

    def test_absolute(self):
        self.assertTrue(self.fs.is_path("/etc/passwd"))

    def test_relative_dot(self):
        self.assertTrue(self.fs.is_path("./script.sh"))

    def test_relative_double_dot(self):
        self.assertTrue(self.fs.is_path("../other"))

    def test_with_slash(self):
        self.assertTrue(self.fs.is_path("dir/file.txt"))

    def test_dotted_filename(self):
        self.assertTrue(self.fs.is_path("file.txt"))

    def test_ip_address(self):
        self.assertFalse(self.fs.is_path("172.18.0.21"))

    def test_ip_address_localhost(self):
        self.assertFalse(self.fs.is_path("127.0.0.1"))

    def test_flag_like(self):
        self.assertFalse(self.fs.is_path("--verbose"))

    def test_flag_like_short(self):
        self.assertFalse(self.fs.is_path("-la"))

    def test_simple_name(self):
        self.assertFalse(self.fs.is_path("ls"))

    def test_simple_name_with_hyphen(self):
        self.assertFalse(self.fs.is_path("my-command"))

    def test_command_with_space(self):
        self.assertFalse(self.fs.is_path("ls -la"))

    def test_absolute_with_space(self):
        self.assertTrue(self.fs.is_path("/tmp/my file.txt"))

    def test_dotted_invalid_ip(self):
        self.assertFalse(self.fs.is_path("999.999.999.999"))

    def test_current_dir(self):
        self.assertTrue(self.fs.is_path("."))

    def test_current_dir_tmp(self):
        self.assertTrue(self.fs.is_path("./tmp"))

    def test_empty_string(self):
        self.assertFalse(self.fs.is_path(""))

    def test_glob_absolute_prefix(self):
        self.assertTrue(self.fs.is_path("/*bin"))

    def test_glob_wildcard_suffix(self):
        self.assertTrue(self.fs.is_path("/usr/bin/*"))

    def test_glob_dot_star(self):
        self.assertTrue(self.fs.is_path("*.txt"))

    def test_glob_doublestar(self):
        self.assertTrue(self.fs.is_path("**/"))

    def test_glob_path_wildcard(self):
        self.assertTrue(self.fs.is_path("**/*.md"))

    def test_glob_no_slash_no_dot(self):
        self.assertFalse(self.fs.is_path("*bin"))


class TestFilesystemPathInfo(unittest.TestCase):
    def setUp(self):
        self.fs = sample_filesystem()

    def test_path_info_dir(self):
        info = self.fs.path_info("/home/user")
        self.assertIn("Directory listing for", info)
        self.assertIn("file.txt", info)
        self.assertIn("script.sh", info)

    def test_path_info_file(self):
        info = self.fs.path_info("/home/user/file.txt")
        self.assertIn("listing for", info)
        self.assertIn("hello world", info)

    def test_path_info_missing(self):
        info = self.fs.path_info("/ghost")
        self.assertEqual(info, "")

    def test_path_info_root(self):
        info = self.fs.path_info("/")
        self.assertIn("Directory listing for", info)

    def test_path_info_dir_string_content(self):
        self.fs.put("/tmp/weird", {"type": "dir", "content": "<content_trimmed>"})
        info = self.fs.path_info("/tmp/weird")
        self.assertIn("Directory listing for", info)
        self.assertNotIn("AttributeError", info)

    def test_path_info_dir_empty_content(self):
        self.fs.put("/tmp/empty", {"type": "dir", "content": ""})
        info = self.fs.path_info("/tmp/empty")
        self.assertIn("Directory listing for", info)

    def test_path_info_filters_deleted(self):
        self.fs.put("/tmp/mydir", {"type": "dir", "content": {}})
        self.fs.put("/tmp/mydir/keep.txt", {"type": "file", "content": "keep"})
        self.fs.put("/tmp/mydir/gone.txt", {"type": "deleted"})
        info = self.fs.path_info("/tmp/mydir")
        self.assertIn("keep.txt", info)
        self.assertNotIn("gone.txt", info)

    def test_path_info_deleted_file_returns_empty(self):
        self.fs.put("/tmp/mydir", {"type": "dir", "content": {}})
        self.fs.put("/tmp/mydir/gone.txt", {"type": "deleted"})
        info = self.fs.path_info("/tmp/mydir/gone.txt")
        self.assertEqual(info, "")

    def test_path_info_malformed_string_entry(self):
        self.fs.put("/tmp/malformed", {"type": "dir", "content": {}})
        self.fs.fs["/"]["content"]["tmp"]["content"]["malformed"]["content"][
            "bad"
        ] = "string value"
        info = self.fs.path_info("/tmp/malformed")
        self.assertIn("Directory listing for", info)
        self.assertIn("bad", info)
        self.assertNotIn("AttributeError", info)
        self.assertNotIn("Traceback", info)


class TestFilesystemPut(unittest.TestCase):
    def setUp(self):
        self.fs = sample_filesystem()

    def test_put_new_file(self):
        self.fs.put(
            "/tmp/newfile.txt",
            {
                "type": "file",
                "content": "new content",
                "permissions": "-rw-r--r--",
                "owner": "user",
                "group": "user",
            },
        )
        node = self.fs.get("/tmp/newfile.txt")
        self.assertEqual(node["content"], "new content")
        self.assertEqual(node["type"], "file")

    def test_put_new_dir(self):
        self.fs.put(
            "/tmp/newdir",
            {
                "type": "dir",
            },
        )
        node = self.fs.get("/tmp/newdir")
        self.assertEqual(node["type"], "dir")

    def test_put_update_existing(self):
        self.fs.put(
            "/home/user/file.txt",
            {
                "type": "file",
                "content": "updated content",
                "permissions": "-rw-r--r--",
                "owner": "user",
                "group": "user",
            },
        )
        node = self.fs.get("/home/user/file.txt")
        self.assertEqual(node["content"], "updated content")

    def test_put_with_parent_creation(self):
        self.fs.put(
            "/a/b/c/file.txt",
            {
                "type": "file",
                "content": "deep",
            },
        )
        node = self.fs.get("/a/b/c/file.txt")
        self.assertEqual(node["content"], "deep")

    def test_put_root_noop(self):
        self.fs.put("/", {"type": "file", "content": "should not overwrite"})
        node = self.fs.get("/")
        self.assertEqual(node["type"], "dir")

    def test_put_preserves_siblings(self):
        self.fs.put(
            "/etc/newfile.conf",
            {
                "type": "file",
                "content": "config",
            },
        )
        passwd = self.fs.get("/etc/passwd")
        self.assertEqual(passwd["type"], "file")


if __name__ == "__main__":
    unittest.main()
