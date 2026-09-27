from __future__ import annotations

import unittest
from pathlib import Path

from media_downloader.explorer import ExplorerStatus, show_in_explorer


class ExplorerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / ".tmp"
        self.root.mkdir(exist_ok=True)

    def test_existing_file_is_selected_with_argument_list(self) -> None:
        media = self.root / "explorer episode 01.mp4"
        media.write_bytes(b"media")
        selected: list[Path] = []

        result = show_in_explorer(media, selector=lambda path: selected.append(path))

        self.assertEqual(result.status, ExplorerStatus.SELECTED)
        self.assertEqual(selected, [media.resolve()])
        media.unlink()

    def test_missing_file_returns_folder_fallback_without_launching(self) -> None:
        missing = self.root / "explorer-moved.mp4"
        if missing.exists():
            missing.unlink()
        selected: list[Path] = []

        result = show_in_explorer(missing, selector=lambda path: selected.append(path))

        self.assertEqual(result.status, ExplorerStatus.MISSING)
        self.assertEqual(result.folder, self.root.resolve())
        self.assertEqual(selected, [])

    def test_shell_selection_failure_is_reported(self) -> None:
        media = self.root / "explorer-failure.mp4"
        media.write_bytes(b"media")

        def fail(_path: Path) -> None:
            raise OSError("shell failed")

        result = show_in_explorer(media, selector=fail)
        self.assertEqual(result.status, ExplorerStatus.FAILED)
        self.assertIn("shell failed", result.error)
        media.unlink()


if __name__ == "__main__":
    unittest.main()

