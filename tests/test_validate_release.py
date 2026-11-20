"""Release validation must reject inconsistent tags, notes, and packages."""

import io
import subprocess
import tarfile
import zipfile

import pytest

from scripts.validate_release import (
    release_notes,
    validate_release,
    validate_tag_commit,
)


@pytest.fixture
def release_root(tmp_path):
    root = tmp_path / "source"
    (root / "combustion_ble").mkdir(parents=True)
    (root / "combustion_ble/version.py").write_text('VERSION = "0.4.0"\n')
    (root / "CHANGELOG.md").write_text(
        "## [v0.4.0](https://example.com/v0.4.0) - 2026-11-20\n- New API\n"
    )
    (root / "pyproject.toml").write_text(
        '[project]\nname = "combustion_ble"\nrequires-python = ">=3.14.2"\n'
    )
    return root


def test_release_notes_stop_at_next_heading():
    changelog = """## Unreleased

## [v0.4.0](https://example.com/v0.4.0) - 2026-11-20
- New API

## [v0.3.3](https://example.com/v0.3.3) - 2024-03-11
- Older change
"""
    assert release_notes("v0.4.0", changelog) == "- New API\n"


@pytest.mark.parametrize("tag", ["main", "0.4.0", "v0.4.0rc1", "v0.4.0\n", "v99.0.0"])
def test_invalid_or_mismatched_release_tag(tag, release_root):
    with pytest.raises(ValueError):
        validate_release(tag, release_root)


@pytest.mark.parametrize(
    "changelog",
    ["## Unreleased\n- Change\n", "## [v0.4.0](https://example.com) - 2026-11-20\n"],
)
def test_missing_or_empty_release_notes(changelog):
    with pytest.raises(ValueError):
        release_notes("v0.4.0", changelog)


def test_reject_unexpected_distribution_files(tmp_path, release_root):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "combustion_ble-0.3.3.tar.gz").touch()
    with pytest.raises(ValueError, match="Expected exactly"):
        validate_release("v0.4.0", release_root, dist)


def test_reject_wheel_missing_required_modules(tmp_path, release_root):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "combustion_ble-0.4.0.tar.gz").touch()
    with zipfile.ZipFile(dist / "combustion_ble-0.4.0-py3-none-any.whl", "w") as wheel:
        wheel.writestr("combustion_ble-0.4.0.dist-info/METADATA", "Version: 0.4.0\n")
    with pytest.raises(ValueError, match="Wheel is missing"):
        validate_release("v0.4.0", release_root, dist)


@pytest.mark.parametrize(
    "metadata",
    [
        "Name: combustion_ble\nVersion: 0.4.0\nRequires-Python: >=3.14.2\n",
        "Name: wrong_package\nVersion: 0.4.0\nRequires-Python: >=3.14.2\n",
        "Name: combustion_ble\nVersion: 0.3.3\nRequires-Python: >=3.14.2\n",
        "Name: combustion_ble\nVersion: 0.4.0\nRequires-Python: >=3.11\n",
    ],
)
def test_distribution_metadata(metadata, tmp_path, release_root):
    dist = tmp_path / "dist"
    dist.mkdir()
    with zipfile.ZipFile(dist / "combustion_ble-0.4.0-py3-none-any.whl", "w") as wheel:
        wheel.writestr("combustion_ble-0.4.0.dist-info/METADATA", metadata)
        for name in ("py.typed", "meatnet.py", "advertising.py"):
            wheel.writestr(f"combustion_ble/{name}", "")
    with tarfile.open(dist / "combustion_ble-0.4.0.tar.gz", "w:gz") as sdist:
        data = metadata.encode()
        info = tarfile.TarInfo("combustion_ble-0.4.0/PKG-INFO")
        info.size = len(data)
        sdist.addfile(info, io.BytesIO(data))
    if "Name: combustion_ble\nVersion: 0.4.0\nRequires-Python: >=3.14.2\n" == metadata:
        assert validate_release("v0.4.0", release_root, dist) == "- New API\n"
    else:
        with pytest.raises(ValueError, match="does not match source"):
            validate_release("v0.4.0", release_root, dist)


@pytest.fixture
def git_repo(tmp_path):
    def git(*args):
        return subprocess.check_output(
            ["git", "-c", "user.name=Release Test", "-c", "user.email=test@example.com", *args],
            cwd=tmp_path,
            text=True,
        ).strip()

    git("init", "-q")
    git("commit", "--allow-empty", "-m", "Initial commit")
    return tmp_path, git


def test_missing_tag_validation_does_not_create_tag(git_repo):
    root, git = git_repo
    validate_tag_commit("v0.4.0", root)
    assert git("tag", "--list") == ""


@pytest.mark.parametrize("annotated", [False, True])
def test_existing_tag_at_selected_commit_is_allowed(git_repo, annotated):
    root, git = git_repo
    if annotated:
        git("tag", "-a", "v0.4.0", "-m", "Release")
    else:
        git("tag", "v0.4.0")
    validate_tag_commit("v0.4.0", root)


@pytest.mark.parametrize("annotated", [False, True])
def test_existing_tag_at_other_commit_is_rejected_and_preserved(git_repo, annotated):
    root, git = git_repo
    if annotated:
        git("tag", "-a", "v0.4.0", "-m", "Release")
    else:
        git("tag", "v0.4.0")
    original = git("rev-parse", "refs/tags/v0.4.0")
    git("commit", "--allow-empty", "-m", "Later commit")
    with pytest.raises(ValueError, match="different commit"):
        validate_tag_commit("v0.4.0", root)
    assert git("rev-parse", "refs/tags/v0.4.0") == original


def test_tag_validation_does_not_hide_git_errors(tmp_path):
    with pytest.raises(subprocess.CalledProcessError):
        validate_tag_commit("v0.4.0", tmp_path)
