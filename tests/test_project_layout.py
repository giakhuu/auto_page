from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_phase_one_package_layout_exists() -> None:
    expected_paths = [
        ROOT / "app" / "__init__.py",
        ROOT / "app" / "bot" / "__init__.py",
        ROOT / "app" / "services" / "__init__.py",
        ROOT / "app" / "core" / "__init__.py",
        ROOT / "app" / "models" / "__init__.py",
        ROOT / "tests" / "__init__.py",
    ]

    missing = [str(path.relative_to(ROOT)) for path in expected_paths if not path.exists()]

    assert not missing, f"Missing scaffold paths: {missing}"
