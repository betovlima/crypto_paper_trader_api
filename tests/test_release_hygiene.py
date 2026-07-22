from pathlib import Path


def test_gitignore_excludes_runtime_data() -> None:
    project_root = Path(__file__).resolve().parents[1]
    gitignore = (project_root / ".gitignore").read_text(encoding="utf-8")
    assert "data/" in gitignore
    assert "*.db" in gitignore
    assert "*.sqlite" in gitignore
    assert "*.sqlite3" in gitignore
