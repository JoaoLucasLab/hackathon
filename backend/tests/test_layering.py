"""ENG-01: engine/, llm/ and api/ must not import from schools/byui directly.
They use the interfaces in schools/base.py."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
GUARDED = ["engine", "llm", "api"]
FORBIDDEN = "app.schools.byui"


def _module_name(path: Path, app: Path) -> str:
    parts = path.relative_to(app.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _imports(path: Path, app: Path) -> list[str]:
    """Absolute names of every module imported by `path`, relative imports resolved."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = _module_name(path, app)
    if path.name != "__init__.py":
        package = package.rpartition(".")[0]
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - (node.level - 1)]
                module = ".".join([*base, node.module] if node.module else base)
            else:
                module = node.module or ""
            found.append(module)
            # `from app.schools import byui`
            found.extend(f"{module}.{alias.name}" for alias in node.names)
    return found


def _violations(root: Path, app: Path = APP) -> list[str]:
    bad = []
    for path in sorted(root.rglob("*.py")):
        for name in _imports(path, app):
            if name == FORBIDDEN or name.startswith(FORBIDDEN + "."):
                bad.append(f"{path.relative_to(app)} imports {name}")
    return bad


def _probe(tmp_path: Path, source: str) -> list[str]:
    """Run the detector on a throwaway app/engine/probe.py."""
    app = tmp_path / "app"
    engine = app / "engine"
    engine.mkdir(parents=True)
    (engine / "probe.py").write_text(source + "\n", encoding="utf-8")
    return _violations(engine, app)


@pytest.mark.parametrize("folder", GUARDED)
def test_no_direct_byui_imports(folder: str) -> None:
    root = APP / folder
    assert root.is_dir(), f"missing app/{folder}/"
    assert _violations(root) == []


@pytest.mark.parametrize(
    "source",
    [
        "import app.schools.byui",
        "import app.schools.byui.rules as rules",
        "from app.schools.byui import rules",
        "from app.schools.byui.rules import ByuiRules",
        "from app.schools import byui",
        "from ..schools.byui import rules",
        "from ..schools import byui",
    ],
)
def test_detector_catches(tmp_path: Path, source: str) -> None:
    """The check itself works, including relative imports."""
    assert _probe(tmp_path, source), source


def test_detector_allows_base(tmp_path: Path) -> None:
    assert _probe(tmp_path, "from app.schools.base import SchoolRules") == []
