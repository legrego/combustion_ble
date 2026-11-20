"""Validate a stable release and extract its changelog notes before publishing."""

import argparse
import re
import runpy
import subprocess
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path


def release_notes(tag: str, changelog: str) -> str:
    """Return the notes under the exact release heading, excluding later releases."""
    heading = re.search(
        rf"^## \[{re.escape(tag)}\]\([^\n]+\) - \d{{4}}-\d{{2}}-\d{{2}}$", changelog, re.M
    )
    if heading is None:
        raise ValueError(f"Missing dated changelog entry for {tag}")
    notes = re.split(r"^## ", changelog[heading.end() :], maxsplit=1, flags=re.M)[0].strip()
    if not notes:
        raise ValueError(f"Empty changelog entry for {tag}")
    return notes + "\n"


def validate_release(tag: str, root: Path, dist: Path | None = None) -> str:
    """Check the tag, source version, changelog, and optionally built metadata."""
    if re.fullmatch(r"v\d+\.\d+\.\d+", tag) is None:
        raise ValueError("Use a stable release tag such as v0.4.0")
    version = runpy.run_path(str(root / "combustion_ble/version.py"))["VERSION"]
    if tag != f"v{version}":
        raise ValueError(f"Tag {tag} does not match source version {version}")
    notes = release_notes(tag, (root / "CHANGELOG.md").read_text())
    if dist is None:
        return notes

    wheel_name = f"combustion_ble-{version}-py3-none-any.whl"
    sdist_name = f"combustion_ble-{version}.tar.gz"
    if {path.name for path in dist.iterdir()} != {wheel_name, sdist_name}:
        raise ValueError("Expected exactly one release wheel and one source distribution")
    with zipfile.ZipFile(dist / wheel_name) as wheel:
        wheel_metadata = wheel.read(f"combustion_ble-{version}.dist-info/METADATA")
        for name in ("py.typed", "meatnet.py", "advertising.py"):
            if f"combustion_ble/{name}" not in wheel.namelist():
                raise ValueError(f"Wheel is missing {name}")
    with tarfile.open(dist / sdist_name) as sdist:
        member = sdist.extractfile(f"combustion_ble-{version}/PKG-INFO")
        if member is None:
            raise ValueError("Source distribution is missing metadata")
        sdist_metadata = member.read()
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    for metadata in (wheel_metadata, sdist_metadata):
        parsed = BytesParser().parsebytes(metadata)
        if parsed["Name"] != project["name"] or parsed["Version"] != version:
            raise ValueError("Distribution name or version does not match source")
        if parsed["Requires-Python"] != project["requires-python"]:
            raise ValueError("Distribution Python requirement does not match source")
    return notes


def main() -> None:
    """Write release notes only after all requested validation succeeds."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    parser.add_argument("--dist", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    notes = validate_release(args.tag, root, args.dist)
    validate_tag_commit(args.tag, root)
    if args.dist is not None:
        Path("RELEASE_NOTES.md").write_text(notes)


def validate_tag_commit(tag: str, root: Path) -> None:
    """Allow a missing tag, but never reuse a tag pointing at another commit."""
    ref = f"refs/tags/{tag}"
    existing = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", ref], cwd=root, check=False
    )
    if existing.returncode == 1:
        return
    existing.check_returncode()

    def resolve(revision: str) -> str:
        return subprocess.check_output(["git", "rev-parse", revision], cwd=root, text=True).strip()

    if resolve(f"{ref}^{{commit}}") != resolve("HEAD"):
        raise ValueError(f"Tag {tag} already exists at a different commit; refusing to move it")


if __name__ == "__main__":
    main()
