import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "The Windows build script only runs on Windows")
class BuildScriptTest(unittest.TestCase):
    def _clean_workspace(self, project: Path) -> None:
        for child in project.iterdir():
            if child.name == ".gitkeep":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

    def test_uses_python_from_path_when_virtual_environment_is_absent(self) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        self.assertIsNotNone(powershell)

        project = ROOT / "tests" / "fixtures" / "build_script_workspace"
        self._clean_workspace(project)
        self.addCleanup(self._clean_workspace, project)

        try:
            shutil.copy2(ROOT / "build.ps1", project / "build.ps1")
            (project / "MediaDownloader.spec").write_text("# test spec\n", encoding="utf-8")

            command_directory = project / "bin"
            command_directory.mkdir()
            (command_directory / "python.cmd").write_text(
                "@echo off\r\n"
                "mkdir dist\\MediaDownloader\\_internal\r\n"
                "type nul > dist\\MediaDownloader\\MediaDownloader.exe\r\n"
                "exit /b 0\r\n",
                encoding="utf-8",
            )

            environment = os.environ.copy()
            environment["PATH"] = f"{command_directory}{os.pathsep}{environment['PATH']}"
            result = subprocess.run(
                [str(powershell), "-NoProfile", "-File", str(project / "build.ps1")],
                cwd=project,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((project / "MediaDownloader.exe").is_file())
            self.assertTrue((project / "_internal").is_dir())
        finally:
            self._clean_workspace(project)


if __name__ == "__main__":
    unittest.main()
