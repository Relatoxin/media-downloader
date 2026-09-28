import json
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RepositoryMetadataTest(unittest.TestCase):
    def test_public_metadata_and_tool_commands_are_declared(self) -> None:
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

        self.assertIn("MIT License", license_text)
        self.assertIn("Copyright (c) 2026 Relatoxin", license_text)
        self.assertEqual(pyproject["project"]["requires-python"], ">=3.12")
        self.assertIn("ruff", pyproject["tool"])
        self.assertIn("mypy", pyproject["tool"])
        self.assertEqual(
            package["scripts"]["test"], "node --test --test-isolation=none tests/js/extension_logic.test.js"
        )
        self.assertEqual(package["scripts"]["lint"], "eslint browser-extension tests/js")
        self.assertEqual(package["scripts"]["typecheck"], "tsc --noEmit")
        self.assertTrue(package["private"])

    def test_runtime_dependencies_are_directly_pinned(self) -> None:
        requirements = [
            line.strip()
            for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertGreaterEqual(len(requirements), 3)
        for requirement in requirements:
            with self.subTest(requirement=requirement):
                self.assertIn("==", requirement)
                self.assertNotIn(">=", requirement)

    def test_public_documentation_and_ci_are_present(self) -> None:
        required_paths = (
            "README.md",
            "README.ru.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "docs/architecture.md",
            "docs/security.md",
            "docs/testing.md",
            "docs/case-study.md",
            "docs/demo.md",
            "docs/assets/workflow.svg",
            ".github/workflows/ci.yml",
            ".github/dependabot.yml",
        )
        for relative_path in required_paths:
            with self.subTest(path=relative_path):
                path = ROOT / relative_path
                self.assertTrue(path.is_file())
                self.assertGreater(path.stat().st_size, 0)

        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("python -m unittest discover", workflow)
        self.assertIn("npm test", workflow)
        self.assertNotIn("youtube.com", workflow.lower())
        self.assertNotIn("tiktok.com", workflow.lower())


if __name__ == "__main__":
    unittest.main()
