import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest


def _compile_python_probe(output_path, exit_code=0):
    framework_root = Path(os.environ["WINDIR"]) / "Microsoft.NET"
    candidates = (
        framework_root / "Framework64" / "v4.0.30319" / "csc.exe",
        framework_root / "Framework" / "v4.0.30319" / "csc.exe",
    )
    compiler = next((candidate for candidate in candidates if candidate.is_file()), None)
    if compiler is None:
        raise unittest.SkipTest(".NET Framework C# compiler is unavailable")

    source_path = output_path.with_suffix(".cs")
    source_path.write_text(
        """
using System;

internal static class PythonProbe
{
    private static int Main(string[] args)
    {
        foreach (string argument in args)
        {
            Console.WriteLine("ARG=" + argument);
        }
        Console.WriteLine("CWD=" + Environment.CurrentDirectory);
        Console.WriteLine("PYTHONPATH=" + (Environment.GetEnvironmentVariable("PYTHONPATH") ?? ""));
        return __EXIT_CODE__;
    }
}
""".replace("__EXIT_CODE__", str(exit_code)).strip(),
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(compiler), "/nologo", f"/out:{output_path}", str(source_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)


class PackageSmokeTests(unittest.TestCase):
    def test_package_exposes_nonempty_version(self):
        import selfworkflow

        self.assertIsInstance(selfworkflow.__version__, str)
        self.assertTrue(selfworkflow.__version__.strip())

    def test_cli_version_matches_package_version(self):
        import selfworkflow

        repository_root = Path(__file__).resolve().parents[1]
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(repository_root / "src")
        result = subprocess.run(
            [sys.executable, "-m", "selfworkflow.cli", "--version"],
            cwd=repository_root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), selfworkflow.__version__)


class ProjectConfigurationTests(unittest.TestCase):
    def test_pyproject_declares_reproducible_src_package(self):
        repository_root = Path(__file__).resolve().parents[1]
        pyproject_path = repository_root / "pyproject.toml"
        self.assertTrue(pyproject_path.is_file(), "pyproject.toml must exist")
        configuration = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

        self.assertEqual(configuration["project"]["name"], "selfworkflow")
        self.assertEqual(configuration["project"]["version"], "0.1.0.dev0")
        self.assertEqual(configuration["project"]["requires-python"], ">=3.11")
        self.assertEqual(
            configuration["project"]["scripts"]["selfworkflow"],
            "selfworkflow.cli:main",
        )
        self.assertEqual(
            configuration["build-system"]["requires"], ["setuptools==83.0.0"]
        )
        self.assertEqual(
            configuration["tool"]["setuptools"]["package-dir"], {"": "src"}
        )

    def test_development_requirements_are_fully_pinned(self):
        repository_root = Path(__file__).resolve().parents[1]
        lock_path = repository_root / "requirements-dev.lock.txt"
        self.assertTrue(lock_path.is_file(), "requirements-dev.lock.txt must exist")
        requirements = {
            line.strip()
            for line in lock_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }

        self.assertEqual(
            requirements,
            {
                "PyYAML==6.0.3",
                "attrs==26.1.0",
                "jsonschema==4.26.0",
                "jsonschema-specifications==2025.9.1",
                "referencing==0.37.0",
                "rpds-py==2026.6.3",
                "setuptools==83.0.0",
                "typing_extensions==4.16.0",
            },
        )
        self.assertTrue(all("==" in requirement for requirement in requirements))

    def test_gitignore_excludes_local_environment_and_evidence(self):
        repository_root = Path(__file__).resolve().parents[1]
        ignored_patterns = {
            line.strip()
            for line in (repository_root / ".gitignore").read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }

        self.assertTrue(
            {
                ".venv/",
                "__pycache__/",
                "*.pyc",
                "build/",
                "artifacts/",
            }.issubset(ignored_patterns)
        )

    def test_readme_documents_reproducible_environment_commands(self):
        repository_root = Path(__file__).resolve().parents[1]
        readme_path = repository_root / "README.md"
        self.assertTrue(readme_path.is_file(), "README.md must exist")
        readme = readme_path.read_text(encoding="utf-8")

        self.assertIn("python -m venv .venv", readme)
        self.assertIn(
            ".venv\\Scripts\\python.exe -m pip install "
            "--disable-pip-version-check -r requirements-dev.lock.txt -e .",
            readme,
        )
        self.assertIn(".\\scripts\\test.ps1", readme)
        self.assertIn(".\\scripts\\verify.ps1 -Suite unit", readme)


class TestScriptTests(unittest.TestCase):
    def test_requires_repository_venv(self):
        repository_root = Path(__file__).resolve().parents[1]
        source_script = repository_root / "scripts" / "test.ps1"
        self.assertTrue(source_script.is_file(), "scripts/test.ps1 must exist")

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            temporary_scripts = temporary_root / "scripts"
            temporary_scripts.mkdir()
            script = temporary_scripts / "test.ps1"
            shutil.copy2(source_script, script)

            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                ],
                cwd=temporary_root,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 10, result.stderr)
        self.assertIn("repository .venv is required", result.stderr)

    def test_forwards_exact_dotted_test(self):
        repository_root = Path(__file__).resolve().parents[1]

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            temporary_scripts = temporary_root / "scripts"
            temporary_scripts.mkdir()
            shutil.copy2(repository_root / "scripts" / "test.ps1", temporary_scripts)
            python_executable = temporary_root / ".venv" / "Scripts" / "python.exe"
            python_executable.parent.mkdir(parents=True)
            _compile_python_probe(python_executable)
            dotted_test = "tests.test_smoke.PackageSmokeTests.test_package_exposes_nonempty_version"

            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(temporary_scripts / "test.ps1"),
                    "-Test",
                    dotted_test,
                ],
                cwd=temporary_root,
                capture_output=True,
                text=True,
                check=False,
            )

        arguments = [
            line.removeprefix("ARG=")
            for line in result.stdout.splitlines()
            if line.startswith("ARG=")
        ]
        self.assertEqual(arguments, ["-m", "unittest", dotted_test, "-v"], result.stderr)

    def test_sets_src_pythonpath_only_for_child_process(self):
        repository_root = Path(__file__).resolve().parents[1]
        parent_pythonpath = os.environ.get("PYTHONPATH")

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            temporary_scripts = temporary_root / "scripts"
            temporary_scripts.mkdir()
            shutil.copy2(repository_root / "scripts" / "test.ps1", temporary_scripts)
            python_executable = temporary_root / ".venv" / "Scripts" / "python.exe"
            python_executable.parent.mkdir(parents=True)
            _compile_python_probe(python_executable)
            source_root = temporary_root / "src"
            source_root.mkdir()
            environment = os.environ.copy()
            environment["PYTHONPATH"] = "parent-sentinel"

            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(temporary_scripts / "test.ps1"),
                    "-Test",
                    "tests.example",
                ],
                cwd=temporary_root,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            child_pythonpath = next(
                line.removeprefix("PYTHONPATH=")
                for line in result.stdout.splitlines()
                if line.startswith("PYTHONPATH=")
            )
            self.assertTrue(os.path.samefile(child_pythonpath, source_root))

        self.assertEqual(os.environ.get("PYTHONPATH"), parent_pythonpath)

    def test_runs_full_discovery_by_default(self):
        repository_root = Path(__file__).resolve().parents[1]

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            temporary_scripts = temporary_root / "scripts"
            temporary_scripts.mkdir()
            shutil.copy2(repository_root / "scripts" / "test.ps1", temporary_scripts)
            python_executable = temporary_root / ".venv" / "Scripts" / "python.exe"
            python_executable.parent.mkdir(parents=True)
            _compile_python_probe(python_executable)

            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(temporary_scripts / "test.ps1"),
                ],
                cwd=temporary_root,
                capture_output=True,
                text=True,
                check=False,
            )

        arguments = [
            line.removeprefix("ARG=")
            for line in result.stdout.splitlines()
            if line.startswith("ARG=")
        ]
        self.assertEqual(
            arguments,
            ["-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"],
            result.stderr,
        )

    def test_default_discovery_uses_repository_from_arbitrary_cwd(self):
        parent_cwd = Path.cwd()
        parent_pythonpath = os.environ.get("PYTHONPATH")
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            repository_root = temporary_root / "repository"
            scripts_root = repository_root / "scripts"
            scripts_root.mkdir(parents=True)
            shutil.copy2(
                Path(__file__).resolve().parents[1] / "scripts" / "test.ps1",
                scripts_root,
            )
            python_executable = repository_root / ".venv" / "Scripts" / "python.exe"
            python_executable.parent.mkdir(parents=True)
            _compile_python_probe(python_executable)
            (repository_root / "src").mkdir()
            (repository_root / "tests").mkdir()
            outside_cwd = temporary_root / "outside"
            outside_cwd.mkdir()
            environment = os.environ.copy()
            environment["PYTHONPATH"] = "parent-sentinel"

            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(scripts_root / "test.ps1"),
                ],
                cwd=outside_cwd,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            child_cwd = next(
                line.removeprefix("CWD=")
                for line in result.stdout.splitlines()
                if line.startswith("CWD=")
            )
            child_pythonpath = next(
                line.removeprefix("PYTHONPATH=")
                for line in result.stdout.splitlines()
                if line.startswith("PYTHONPATH=")
            )

            self.assertTrue(os.path.samefile(child_cwd, repository_root))
            self.assertTrue(os.path.samefile(child_pythonpath, repository_root / "src"))

        self.assertEqual(Path.cwd(), parent_cwd)
        self.assertEqual(os.environ.get("PYTHONPATH"), parent_pythonpath)


class VerifyScriptTests(unittest.TestCase):
    def test_unit_suite_wraps_test_script(self):
        repository_root = Path(__file__).resolve().parents[1]
        verify_script = repository_root / "scripts" / "verify.ps1"
        self.assertTrue(verify_script.is_file(), "scripts/verify.ps1 must exist")

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            temporary_scripts = temporary_root / "scripts"
            temporary_scripts.mkdir()
            shutil.copy2(repository_root / "scripts" / "test.ps1", temporary_scripts)
            shutil.copy2(verify_script, temporary_scripts)
            python_executable = temporary_root / ".venv" / "Scripts" / "python.exe"
            python_executable.parent.mkdir(parents=True)
            _compile_python_probe(python_executable)
            dotted_test = "tests.test_smoke.PackageSmokeTests"

            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(temporary_scripts / "verify.ps1"),
                    "-Suite",
                    "unit",
                    "-Test",
                    dotted_test,
                ],
                cwd=temporary_root,
                capture_output=True,
                text=True,
                check=False,
            )

        arguments = [
            line.removeprefix("ARG=")
            for line in result.stdout.splitlines()
            if line.startswith("ARG=")
        ]
        self.assertEqual(arguments, ["-m", "unittest", dotted_test, "-v"], result.stderr)

    def test_unimplemented_automated_suites_return_structured_failure(self):
        repository_root = Path(__file__).resolve().parents[1]
        verify_script = repository_root / "scripts" / "verify.ps1"

        for suite in ("conformance", "installer", "behavioral", "automated"):
            with self.subTest(suite=suite):
                result = subprocess.run(
                    [
                        "powershell.exe",
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(verify_script),
                        "-Suite",
                        suite,
                    ],
                    cwd=repository_root,
                    capture_output=True,
                    text=True,
                    check=False,
                )

                self.assertEqual(result.returncode, 20, result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(payload["suite"], suite)
                self.assertEqual(payload["status"], "not-implemented")
                self.assertEqual(payload["exitCode"], 20)

    def test_native_suite_requires_user_action(self):
        repository_root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(repository_root / "scripts" / "verify.ps1"),
                "-Suite",
                "native",
            ],
            cwd=repository_root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 30, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["suite"], "native")
        self.assertEqual(payload["status"], "requires-user-action")
        self.assertEqual(payload["exitCode"], 30)

    def test_all_suite_runs_unit_and_reports_incomplete_suites(self):
        repository_root = Path(__file__).resolve().parents[1]

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            temporary_scripts = temporary_root / "scripts"
            temporary_scripts.mkdir()
            shutil.copy2(repository_root / "scripts" / "test.ps1", temporary_scripts)
            shutil.copy2(repository_root / "scripts" / "verify.ps1", temporary_scripts)
            python_executable = temporary_root / ".venv" / "Scripts" / "python.exe"
            python_executable.parent.mkdir(parents=True)
            _compile_python_probe(python_executable)

            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(temporary_scripts / "verify.ps1"),
                    "-Suite",
                    "all",
                ],
                cwd=temporary_root,
                capture_output=True,
                text=True,
                check=False,
            )

        arguments = [
            line.removeprefix("ARG=")
            for line in result.stdout.splitlines()
            if line.startswith("ARG=")
        ]
        self.assertEqual(
            arguments,
            ["-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"],
            result.stderr,
        )
        self.assertEqual(result.returncode, 20, result.stderr)
        payload = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(payload["suite"], "all")
        self.assertEqual(payload["status"], "incomplete")
        self.assertEqual(payload["exitCode"], 20)

    def test_all_suite_propagates_unit_failure(self):
        repository_root = Path(__file__).resolve().parents[1]

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            temporary_scripts = temporary_root / "scripts"
            temporary_scripts.mkdir()
            shutil.copy2(repository_root / "scripts" / "test.ps1", temporary_scripts)
            shutil.copy2(repository_root / "scripts" / "verify.ps1", temporary_scripts)
            python_executable = temporary_root / ".venv" / "Scripts" / "python.exe"
            python_executable.parent.mkdir(parents=True)
            _compile_python_probe(python_executable, exit_code=7)

            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(temporary_scripts / "verify.ps1"),
                    "-Suite",
                    "all",
                ],
                cwd=temporary_root,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 7, result.stderr)
        payload = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["failedSuite"], "unit")


if __name__ == "__main__":
    unittest.main()
