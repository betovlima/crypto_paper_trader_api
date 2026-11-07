from pathlib import Path


FRONTEND_EXTENSIONS = {".js", ".jsx", ".mjs", ".ts", ".tsx", ".css", ".html"}
FRONTEND_ROOT_ENTRIES = {
    ".npmrc",
    "audit-types.d.ts",
    "index.html",
    "package.json",
    "package-lock.json",
    "public",
    "tsconfig.audit.json",
    "vite.config.js",
}


def test_api_repository_contains_no_frontend_application() -> None:
    root = Path(__file__).resolve().parents[1]
    src = root / "src"

    assert sorted(path.name for path in src.iterdir()) == ["crypto_paper_trader_api"]
    assert (src / "crypto_paper_trader_api" / "app.py").is_file()

    unexpected_root = sorted(name for name in FRONTEND_ROOT_ENTRIES if (root / name).exists())
    assert not unexpected_root, f"Unexpected frontend files at repository root: {unexpected_root}"

    unexpected_sources = sorted(
        str(path.relative_to(root))
        for folder in (src, root / "scripts")
        for path in folder.rglob("*")
        if path.is_file() and path.suffix.lower() in FRONTEND_EXTENSIONS
    )
    assert not unexpected_sources, f"Unexpected frontend source files: {unexpected_sources}"
