# Release process

The Main GitHub Actions workflow runs checks and builds package artifacts for
pull requests, pushes to main, and version tags. Publishing to PyPI and creating
a GitHub release requires a manual workflow run with publishing enabled.

## One-time setup

Add a PyPI API token scoped to the `combustion_ble` project as the repository
Actions secret `PYPI_API_KEY`. GitHub releases use the workflow's built-in
`GITHUB_TOKEN`; no additional GitHub token is needed.

The workflow must be merged into the default branch before GitHub shows the
**Run workflow** button. Release tags must include this workflow and its
`scripts/validate_release.py` helper.

## Prepare and publish

1. Update `combustion_ble/version.py` and review the unreleased changelog.
2. Run `make run-checks`, build with `python -m build`, and validate with
   `twine check --strict dist/*` in a clean Python 3.14.2+ environment with
   `.[dev]` installed.
3. Run `./scripts/release.sh` to prepare the changelog, commit, and push a version
   tag. This triggers validation only. Wait for all Main checks to pass.
4. In GitHub, open **Actions → Main → Run workflow**. Leave the workflow branch
   set to `main`, enter the existing tag (for example `v0.4.0`), and leave
   **publish** unchecked for a dry run.
5. The run checks out the tag, confirms it matches the source version and a
   dated changelog entry, and runs every check against the same resolved commit.
   It builds packages, validates their metadata and contents, and shows release
   notes in the job summary. Review the `package` artifact and the summary.
6. Run it again with the same tag and **publish** checked. After all checks
   pass, the workflow validates and uploads that run's packages to PyPI, then
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

If the PyPI upload succeeds but GitHub release creation fails, create the GitHub
release manually for the same tag using the run's release notes and package
artifact. Re-running publishing will fail on files already uploaded to PyPI;
the workflow deliberately does not skip or overwrite published files.
