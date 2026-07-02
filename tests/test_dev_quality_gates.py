from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def load_pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_dev_optional_dependencies_are_declared_without_runtime_dependencies() -> None:
    pyproject = load_pyproject()

    assert pyproject["project"]["dependencies"] == []
    dev_dependencies = pyproject["project"]["optional-dependencies"]["dev"]

    assert "pytest>=8" in dev_dependencies
    assert "ruff>=0.6" in dev_dependencies


def test_pytest_quality_gate_uses_tests_directory() -> None:
    pyproject = load_pyproject()
    pytest_options = pyproject["tool"]["pytest"]["ini_options"]

    assert pytest_options["testpaths"] == ["tests"]
    assert "test_*.py" in pytest_options["python_files"]
    assert "*_test.py" in pytest_options["python_files"]


def test_ruff_quality_gate_is_configured_for_project_python_version() -> None:
    pyproject = load_pyproject()
    ruff = pyproject["tool"]["ruff"]
    ruff_lint = ruff["lint"]
    ruff_format = ruff["format"]

    assert ruff["target-version"] == "py311"
    assert ruff["line-length"] == 100
    assert {"E", "F", "I", "UP"}.issubset(set(ruff_lint["select"]))
    assert ruff_format["quote-style"] == "double"


def test_readme_documents_dev_quality_gate_commands() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "python -m pip install -e .[dev]" in readme
    assert "python -m pytest" in readme
    assert "python -m ruff check ." in readme
    assert "python -m ruff format --check ." in readme
