# Release process

Publishing is manual. The Main GitHub Actions workflow runs checks and builds
package artifacts for pull requests, pushes to main, and version tags. It does
not upload to PyPI or create GitHub releases.

1. Update `combustion_ble/version.py` and review the unreleased changelog.
2. Run `make run-checks`, build with `python -m build`, and validate with
   `twine check --strict dist/*` in a clean Python 3.14.2+ environment with
   `.[dev]` installed.
3. Run `./scripts/release.sh` to prepare the changelog, commit, and push a version
   tag. This triggers validation only. Wait for all Main checks to pass.
4. Download the `package` artifact from that successful tagged Main run and
   extract it. Verify its version and contents before publishing.
5. When ready, manually upload those distributions using `twine upload dist/*`
   with your PyPI credentials, and create the GitHub release for the same tag,
   using the changelog for release notes and attaching the distributions.

If validation fails, fix it before publishing. Do not replace tags for versions
that have already been published to PyPI; prepare a new version instead.
