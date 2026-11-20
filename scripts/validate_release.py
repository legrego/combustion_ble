"""Validate a stable release and extract its changelog notes before publishing."""

import argparse
import re
import runpy
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
    notes = validate_release(args.tag, Path(__file__).resolve().parent.parent, args.dist)
    if args.dist is not None:
        Path("RELEASE_NOTES.md").write_text(notes)


if __name__ == "__main__":
    main()
