"""Firmware version strings reported by Combustion devices."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, eq=False)
class FirmwareVersion:
    """A device's firmware revision, as reported in its Device Information.

    Combustion firmware reports ``vMAJOR.MINOR.PATCH``, optionally followed by
    ``-COMMIT-SHA`` for development builds and ``_VARIANT`` for a build configuration.
    :attr:`raw` always holds the reported string; the parsed fields are ``None`` when it doesn't
    follow that format.

    Parsed versions compare by major, minor, patch, then commit number, where a release (no
    commit number) sorts before any development build of the same version. Like Combustion's
    Android SDK, comparisons ignore the git SHA and build variant: ``v1.2.3_debug`` equals
    ``v1.2.3_release``. Compare :attr:`raw` to tell such builds apart. Ordering a version that
    couldn't be parsed raises ``TypeError``; it equals only a version with the same :attr:`raw`.

    >>> FirmwareVersion.parse("v1.2.3") < FirmwareVersion.parse("v1.10.0")
    True
    >>> str(FirmwareVersion.parse("v1.2.3-4-abcdef0"))
    'v1.2.3-4-abcdef0'
    """

    raw: str
    """The firmware revision string, as the device reported it."""

    major: int | None = None
    minor: int | None = None
    patch: int | None = None
    commit: int | None = None
    """Commits since the release, for development builds."""

    sha: str | None = None
    """Abbreviated git commit, for development builds."""

    @classmethod
    def parse(cls, raw: str) -> FirmwareVersion:
        """Parse a firmware revision string. Never raises for an unexpected format."""
        raw = raw.strip()
        # Follows FirmwareVersion.fromString in Combustion's Android SDK.
        if not raw.startswith("v") or raw.count(".") != 2:
            return cls(raw)
        version_and_sha = raw[1:].split("_", 1)[0].split("-")
        numbers = version_and_sha[0].split(".")
        if len(numbers) != 3 or not all(number.isdecimal() for number in numbers):
            return cls(raw)
        major, minor, patch = (int(number) for number in numbers)
        commit: int | None = None
        sha: str | None = None
        if len(version_and_sha) == 3:
            commit = int(version_and_sha[1]) if version_and_sha[1].isdecimal() else None
            sha = version_and_sha[2]
        return cls(raw, major, minor, patch, commit, sha)

    @property
    def is_valid(self) -> bool:
        """Whether :attr:`raw` could be parsed into version numbers."""
        return self.major is not None

    def _key(self) -> tuple[int, int, int, int] | None:
        if self.major is None or self.minor is None or self.patch is None:
            return None
        return (self.major, self.minor, self.patch, -1 if self.commit is None else self.commit)

    def _ordering_key(self) -> tuple[int, int, int, int]:
        key = self._key()
        if key is None:
            raise TypeError(f"Can't order unparsed firmware version {self.raw!r}")
        return key

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FirmwareVersion):
            return NotImplemented
        key, other_key = self._key(), other._key()
        if key is None or other_key is None:
            return self.raw == other.raw
        return key == other_key

    def __hash__(self) -> int:
        key = self._key()
        return hash(self.raw if key is None else key)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, FirmwareVersion):
            return NotImplemented
        return self._ordering_key() < other._ordering_key()

    def __le__(self, other: object) -> bool:
        if not isinstance(other, FirmwareVersion):
            return NotImplemented
        return self._ordering_key() <= other._ordering_key()

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, FirmwareVersion):
            return NotImplemented
        return self._ordering_key() > other._ordering_key()

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, FirmwareVersion):
            return NotImplemented
        return self._ordering_key() >= other._ordering_key()

    def __str__(self) -> str:
        return self.raw
