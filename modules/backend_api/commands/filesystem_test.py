#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path

from modules.backend_api.commands.filesystem import _fs_list_dir


class FilesystemListDirectoryTest(unittest.TestCase):
    def test_existing_file_opens_its_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "selected.pdf"
            source.write_bytes(b"pdf")

            result = _fs_list_dir({"path": str(source)})

            self.assertEqual(Path(result["path"]), Path(temp_dir))
            self.assertIsNone(result["recovered_from"])

    def test_missing_selected_file_recovers_to_existing_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "deleted.pdf"

            result = _fs_list_dir({
                "path": str(missing),
                "recover_missing_ancestor": True,
            })

            self.assertEqual(Path(result["path"]), Path(temp_dir))
            self.assertEqual(Path(result["recovered_from"]), missing)
            self.assertEqual(Path(result["parent"]), Path(temp_dir).parent)

    def test_nested_missing_directory_recovers_to_nearest_existing_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            existing = Path(temp_dir) / "existing"
            existing.mkdir()
            missing = existing / "removed" / "child"

            result = _fs_list_dir({
                "path": str(missing),
                "recover_missing_ancestor": True,
            })

            self.assertEqual(Path(result["path"]), existing)

    def test_manual_missing_path_still_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "does-not-exist"

            with self.assertRaises(FileNotFoundError):
                _fs_list_dir({"path": str(missing)})


if __name__ == "__main__":
    unittest.main()
