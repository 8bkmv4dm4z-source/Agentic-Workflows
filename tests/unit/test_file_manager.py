"""Tests for file_manager tool."""

import os
import tempfile
import unittest
from pathlib import Path

from agentic_workflows.tools.file_manager import FileManagerTool


class TestFileManagerTool(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = FileManagerTool()
        self._original_cwd = os.getcwd()
        self._tmp = tempfile.mkdtemp()
        os.chdir(self._tmp)

    def tearDown(self) -> None:
        os.chdir(self._original_cwd)
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_mkdir(self) -> None:
        result = self.tool.execute({"operation": "mkdir", "source": "new_dir"})
        self.assertIn("result", result)
        self.assertTrue(Path("new_dir").is_dir())

    def test_stat_file(self) -> None:
        Path("test.txt").write_text("hello", encoding="utf-8")
        result = self.tool.execute({"operation": "stat", "source": "test.txt"})
        self.assertEqual(result["type"], "file")
        self.assertEqual(result["size_bytes"], 5)

    def test_copy_file(self) -> None:
        Path("src.txt").write_text("data", encoding="utf-8")
        result = self.tool.execute({"operation": "copy", "source": "src.txt", "destination": "dst.txt"})
        self.assertIn("result", result)
        self.assertTrue(Path("dst.txt").exists())
        self.assertEqual(Path("dst.txt").read_text(), "data")

    def test_move_file(self) -> None:
        Path("a.txt").write_text("content", encoding="utf-8")
        result = self.tool.execute({"operation": "move", "source": "a.txt", "destination": "b.txt"})
        self.assertIn("result", result)
        self.assertFalse(Path("a.txt").exists())
        self.assertTrue(Path("b.txt").exists())

    def test_rename_file(self) -> None:
        Path("old.txt").write_text("content", encoding="utf-8")
        result = self.tool.execute({"operation": "rename", "source": "old.txt", "destination": "new.txt"})
        self.assertIn("result", result)
        self.assertTrue(Path("new.txt").exists())

    def test_delete_file(self) -> None:
        Path("del.txt").write_text("bye", encoding="utf-8")
        result = self.tool.execute({"operation": "delete", "source": "del.txt"})
        self.assertIn("result", result)
        self.assertFalse(Path("del.txt").exists())

    def test_delete_nonempty_dir_requires_force(self) -> None:
        Path("mydir").mkdir()
        (Path("mydir") / "file.txt").write_text("x", encoding="utf-8")
        result = self.tool.execute({"operation": "delete", "source": "mydir"})
        self.assertIn("error", result)

    def test_delete_nonempty_dir_with_force(self) -> None:
        Path("mydir2").mkdir()
        (Path("mydir2") / "file.txt").write_text("x", encoding="utf-8")
        result = self.tool.execute({"operation": "delete", "source": "mydir2", "force": True})
        self.assertIn("result", result)
        self.assertFalse(Path("mydir2").exists())

    def test_missing_operation(self) -> None:
        result = self.tool.execute({"source": "test"})
        self.assertIn("error", result)

    def test_missing_source(self) -> None:
        result = self.tool.execute({"operation": "stat"})
        self.assertIn("error", result)

    def test_copy_requires_destination(self) -> None:
        Path("x.txt").write_text("x", encoding="utf-8")
        result = self.tool.execute({"operation": "copy", "source": "x.txt"})
        self.assertIn("error", result)

    def test_path_traversal_blocked(self) -> None:
        result = self.tool.execute({"operation": "stat", "source": "/etc/passwd"})
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
