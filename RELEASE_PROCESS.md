# Release process

The Main GitHub Actions workflow runs checks and builds package artifacts for
pull requests, pushes to main, and version tags. The Release workflow runs those
same checks, then publishes to PyPI and creates a GitHub release. It only runs
manually, and only publishes when publishing is enabled.

## One-time setup

The Release workflow publishes through
[PyPI trusted publishing](https://docs.pypi.org/trusted-publishers/). PyPI verifies
the workflow's identity, so no API token is stored in the repository. GitHub releases
use the workflow's built-in `GITHUB_TOKEN`; no additional GitHub token is needed.

1. In the repository's **Settings → Environments**, create the `pypi` environment.
   Under **Deployment branches and tags**, allow only the branch `main`; otherwise a
   workflow on any branch of this repository could publish. Requiring a reviewer adds
   an approval step before each upload. GitHub creates a missing environment
   unrestricted on first use, so set it up before publishing.
2. In the `combustion-ble` project's
   [publishing settings](https://pypi.org/manage/project/combustion-ble/settings/publishing/)
   on PyPI, add a GitHub trusted publisher. Use owner `legrego`, repository
   `combustion_ble`, workflow `release.yml` and environment `pypi`.

Renaming the repository, `release.yml`, or the environment breaks publishing until the
PyPI publisher is updated to match.

The workflow must be merged into the default branch before GitHub shows the
**Run workflow** button. The selected branch must contain this workflow and its
`scripts/validate_release.py` helper. Dry runs work from any such branch.

## Prepare and publish

1. Update `combustion_ble/version.py` and review the unreleased changelog.
2. Run `make run-checks`, build with `python -m build`, and validate with
   `twine check --strict dist/*` in a clean Python 3.14.2+ environment set up
   with `pip install --group dev -e .`.
3. Move the unreleased changelog entries into a dated release section (for
   example `## [v0.4.0](https://github.com/legrego/combustion_ble/releases/tag/v0.4.0) - 2026-11-20`),
   then commit and push the release preparation to `main`. No tag is needed yet.
4. In GitHub, open **Actions → Release → Run workflow**. Leave the workflow branch
   set to `main`, enter the desired tag (for example `v0.4.0`), and leave
   **publish** unchecked for a dry run.
5. The run checks out the selected branch's commit, confirms the requested tag
   matches the source version and a dated changelog entry, and runs every check
   against that same resolved commit. If the tag already exists, it must point
   to that commit; tags pointing elsewhere are rejected and never moved.
   It builds packages, validates their metadata and contents, and shows release
   notes in the job summary. Review the `package` artifact and the summary.
   A dry run does not create tags or publish anything.
6. Run it again with the same tag and **publish** checked. After all checks pass, and
   after approval if the environment requires it, the workflow uploads that run's
   validated packages to PyPI with
   [attestations](https://docs.pypi.org/attestations/). It then creates the tag at the
   validated commit (or reuses a matching tag) and the GitHub release, using the
   changelog notes and attaching the packages.

The equivalent commands are:

```bash
# Validate without publishing.
gh workflow run release.yml --ref main -f tag=v0.4.0 -F publish=false

# Validate, publish to PyPI, and create the GitHub release.
gh workflow run release.yml --ref main -f tag=v0.4.0 -F publish=true
```

If validation fails, fix it before publishing. Do not replace tags for versions
that have already been published to PyPI; prepare a new version instead.

If the PyPI upload fails before publishing any files, or the upload succeeds but GitHub
release creation fails, use **Re-run failed jobs** on that run. It repeats only the
failed step onwards, using the same packages and commit even if `main` has since
advanced. Re-running publishing will fail on files already uploaded to PyPI; the
workflow deliberately does not skip or overwrite published files.
