# Release process

The Main GitHub Actions workflow runs checks and builds package artifacts for
pull requests, pushes to main, and version tags. Publishing to PyPI and creating
a GitHub release requires a manual workflow run with publishing enabled.

## One-time setup

Add a PyPI API token scoped to the `combustion_ble` project as the repository
Actions secret `PYPI_API_KEY`. GitHub releases use the workflow's built-in
`GITHUB_TOKEN`; no additional GitHub token is needed.

The workflow must be merged into the default branch before GitHub shows the
**Run workflow** button. The selected branch must contain this workflow and its
`scripts/validate_release.py` helper.

## Prepare and publish

1. Update `combustion_ble/version.py` and review the unreleased changelog.
2. Run `make run-checks`, build with `python -m build`, and validate with
   `twine check --strict dist/*` in a clean Python 3.14.2+ environment set up
   with `pip install --group dev -e .`.
3. Move the unreleased changelog entries into a dated release section (for
   example `## [v0.4.0](https://github.com/legrego/combustion_ble/releases/tag/v0.4.0) - 2026-11-20`),
   then commit and push the release preparation to `main`. No tag is needed yet.
4. In GitHub, open **Actions → Main → Run workflow**. Leave the workflow branch
   set to `main`, enter the desired tag (for example `v0.4.0`), and leave
   **publish** unchecked for a dry run.
5. The run checks out the selected branch's commit, confirms the requested tag
   matches the source version and a dated changelog entry, and runs every check
   against that same resolved commit. If the tag already exists, it must point
   to that commit; tags pointing elsewhere are rejected and never moved.
   It builds packages, validates their metadata and contents, and shows release
   notes in the job summary. Review the `package` artifact and the summary.
   A dry run does not create tags or publish anything.
6. Run it again with the same tag and **publish** checked. After all checks
   pass and publishing credentials are present, the workflow creates the tag
   at the validated commit (or reuses a matching tag). It uploads that run's
   validated packages to PyPI, then
   creates the GitHub release using the changelog notes and attaches the packages.

The equivalent commands are:

```bash
# Validate without publishing.
gh workflow run main.yml --ref main -f tag=v0.4.0 -F publish=false

# Validate, publish to PyPI, and create the GitHub release.
gh workflow run main.yml --ref main -f tag=v0.4.0 -F publish=true
```

If validation fails, fix it before publishing. Do not replace tags for versions
that have already been published to PyPI; prepare a new version instead.
If a tag was created but the upload failed before publishing any files, retry
from the same commit. When retrying from GitHub CLI, `--ref v0.4.0` selects that
commit even if `main` has since advanced.

If the PyPI upload succeeds but GitHub release creation fails, create the GitHub
release manually for the same tag using the run's release notes and package
artifact. Re-running publishing will fail on files already uploaded to PyPI;
the workflow deliberately does not skip or overwrite published files.
