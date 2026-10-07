"""The deployment definition must stay deployable and stay secret-free.

These tests are static on purpose: they read the files that a build actually
consumes, so a change that would break a deploy or leak a secret fails here
rather than during a release.
"""

import re
import unittest
from pathlib import Path

BACKEND_DIRECTORY = Path(__file__).resolve().parent
REQUIREMENTS = BACKEND_DIRECTORY / "requirements.txt"
DOCKERFILE = BACKEND_DIRECTORY / "Dockerfile"
DOCKERIGNORE = BACKEND_DIRECTORY / ".dockerignore"

#: Files the image must never carry, whatever the build context contains.
NEVER_IN_IMAGE = (
    ".env",
    ".qa-tests",
    ".qa-temp",
    ".qa-disposable",
    "venv",
    ".venv",
    "__pycache__",
    "data",
)


def requirement_lines() -> list[str]:
    return [
        line.strip()
        for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def normalize(name: str) -> str:
    """Compare package names the way pip does: case and separators ignored."""
    return re.sub(r"[-_.]+", "-", name).lower()


def parsed_requirements() -> dict[str, str]:
    pinned = {}
    for line in requirement_lines():
        match = re.fullmatch(r"([A-Za-z0-9_.\-]+)(\[[A-Za-z0-9_,.\-]+\])?==([^\s;]+)", line)
        if not match:
            raise AssertionError(f"Requirement is not an exact pin: {line!r}")
        pinned[normalize(match.group(1))] = match.group(3)
    return pinned


def docker_directives() -> str:
    """The Dockerfile with comments removed.

    A marker check has to see only what Docker itself executes, otherwise prose
    explaining that ``.env`` stays out of the image would fail the check.
    """
    text = DOCKERFILE.read_text(encoding="utf-8")
    return "\n".join(
        line for line in text.splitlines() if line.strip() and not line.strip().startswith("#")
    )


class RequirementsTests(unittest.TestCase):
    """Startup must not depend on whatever PyPI serves today."""

    def setUp(self):
        self.pinned = parsed_requirements()

    def test_every_requirement_is_exactly_pinned(self):
        self.assertTrue(self.pinned)

    def test_no_unpinned_or_range_entries(self):
        for line in requirement_lines():
            self.assertNotRegex(line, r"(>=|<=|~=|>|<|^\w+$)", f"not an exact pin: {line!r}")

    def test_direct_runtime_imports_are_present(self):
        """Every third-party module the application imports must be declared."""
        for name in ("fastapi", "pydantic", "uvicorn", "PyJWT", "openai", "SQLAlchemy", "asyncpg", "alembic"):
            self.assertIn(name.lower(), self.pinned)

    def test_starlette_and_pydantic_core_are_pinned(self):
        """Transitive pins, so a resolution change cannot alter behaviour."""
        for name in ("starlette", "pydantic-core", "anyio", "greenlet"):
            self.assertIn(name, self.pinned)

    def test_openai_transitive_dependencies_are_pinned(self):
        for name in ("httpx2", "httpcore2", "jiter"):
            self.assertIn(name, self.pinned)

    def test_versions_are_plausible_and_explicit(self):
        for name, version in self.pinned.items():
            self.assertRegex(version, r"^\d+\.\d+", f"{name} is not a concrete version")

    def test_no_local_or_editable_paths(self):
        for line in requirement_lines():
            self.assertNotIn("-e ", line)
            self.assertNotIn("file://", line)
            self.assertNotIn("http://", line)
            self.assertNotIn("https://", line)


class DockerfileTests(unittest.TestCase):
    """The start command is the part that actually runs in production."""

    def setUp(self):
        self.text = DOCKERFILE.read_text(encoding="utf-8")
        self.cmd = self._json_cmd()

    def _json_cmd(self) -> list[str]:
        match = re.search(r"^CMD\s+(\[.*\])\s*$", self.text, re.MULTILINE)
        self.assertIsNotNone(match, "CMD must be an exec-form JSON array")
        import json

        return json.loads(match.group(1))

    def test_starts_uvicorn_with_the_application(self):
        self.assertEqual("uvicorn", self.cmd[0])
        self.assertIn("server:app", self.cmd)

    def test_binds_all_interfaces_on_port_8000(self):
        self.assertIn("--host", self.cmd)
        self.assertEqual("0.0.0.0", self.cmd[self.cmd.index("--host") + 1])
        self.assertIn("--port", self.cmd)
        self.assertEqual("8000", self.cmd[self.cmd.index("--port") + 1])

    def test_exactly_one_worker(self):
        self.assertIn("--workers", self.cmd)
        self.assertEqual("1", self.cmd[self.cmd.index("--workers") + 1])
        self.assertEqual(1, self.cmd.count("--workers"))

    def test_worker_count_cannot_be_overridden_by_the_environment(self):
        """A stray WEB_CONCURRENCY must not be able to add workers."""
        self.assertNotIn("WEB_CONCURRENCY", docker_directives())
        self.assertNotIn("$", docker_directives().replace("${", ""))
        self.assertNotIn("%PORT%", docker_directives())

    def test_no_multiple_worker_server_is_introduced(self):
        lowered = docker_directives().lower()
        self.assertNotIn("gunicorn", lowered)
        self.assertNotIn("uvicorn[standard]", lowered)

    def test_base_image_is_pinned_to_the_tested_interpreter(self):
        match = re.search(r"^FROM\s+(\S+)", self.text, re.MULTILINE)
        self.assertIsNotNone(match)
        self.assertEqual("python:3.14-slim", match.group(1))

    def test_runs_as_a_non_root_user(self):
        self.assertRegex(docker_directives(), r"(?m)^USER\s+(?!root)\S+")

    def test_installs_from_the_pinned_requirements(self):
        self.assertRegex(self.text, r"(?m)^RUN\s+python -m pip install -r requirements\.txt")

    def test_requirements_are_copied_before_the_source(self):
        self.assertLess(
            self.text.index("COPY requirements.txt"),
            self.text.index("COPY server.py"),
            "dependencies must be a separate, cacheable layer",
        )

    def test_no_secret_or_environment_value_is_embedded(self):
        for marker in (
            "SUPABASE",
            "DATABASE_URL",
            "OPENAI_API_KEY",
            "ZOOM_",
            "JWT_SECRET",
            "postgresql://",
            "postgresql+asyncpg://",
            ".env",
        ):
            self.assertNotIn(marker, docker_directives(), f"Dockerfile must not embed {marker}")

    def test_no_env_directive_carries_configuration(self):
        """ENV may only hold interpreter and pip behaviour, never app config."""
        for line in re.findall(r"^ENV\s+(.+)$", docker_directives(), re.MULTILINE):
            for pair in re.findall(r"([A-Z_][A-Z_0-9]*)\s*=", line):
                self.assertIn(
                    pair,
                    ("PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE", "PIP_NO_CACHE_DIR", "PIP_DISABLE_PIP_VERSION_CHECK"),
                )

    def test_copies_only_runtime_source(self):
        copied = re.findall(r"^COPY\s+(\S+)", docker_directives(), re.MULTILINE)
        for path in copied:
            self.assertNotIn("test_", path)
            self.assertNotIn("data", path)
            self.assertNotIn(".env", path)
            self.assertNotIn("venv", path)

    def test_exposes_the_container_port(self):
        self.assertRegex(docker_directives(), r"(?m)^EXPOSE\s+8000\s*$")


class DockerignoreTests(unittest.TestCase):
    """The ignore file is the safety boundary for the build context."""

    def setUp(self):
        self.lines = [
            line.strip()
            for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    def test_environment_files_are_excluded(self):
        self.assertIn(".env", self.lines)

    def test_product_data_is_excluded(self):
        self.assertIn("data/", self.lines)

    def test_local_virtualenvs_are_excluded(self):
        self.assertIn("venv/", self.lines)
        self.assertIn(".venv/", self.lines)

    def test_qa_scratch_directories_are_excluded(self):
        self.assertIn(".qa-*", self.lines)

    def test_tests_are_excluded(self):
        self.assertIn("test_*.py", self.lines)

    def test_runtime_logs_are_excluded(self):
        self.assertIn("*.log", self.lines)


if __name__ == "__main__":
    unittest.main()