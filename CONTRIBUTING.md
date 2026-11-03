# Contributing

## Keep game files out of the repo

Don't upload game files, keys, firmware, saves, extracted assets, generated game code or built game executables. That includes issues and PRs. Technical notes, hashes, addresses and code written for the port are fine.

The content check runs in CI. You can enable the local commit hook too:

```sh
git config core.hooksPath .githooks
```

Don't skip a failed check with `--no-verify`. If the check is wrong, fix it in a separate PR and explain why. Links to game downloads, keys or firmware will be removed.

## Reporting a bug

Use an issue form and include:

- Your port and game version.
- Your GPU and driver.
- What happened and how to reproduce it.
- The relevant log, after checking it for personal paths.

The F1 menu shows version details and has a **Copy system info** option in Advanced. Logs are in `logs/engage.log` next to `engage.exe`. After a crash, copy the log before starting the game again. A screenshot can help, but you don't need to record a long playthrough.

## Pull requests

**Open contributor PRs against `dev`, not `main`.** Start your feature or fix branch from the latest `dev`. Link the issue if there is one, explain what changed, and say how you tested it.

Code fixes and features go through an issue/PR. Small documentation or wording edits by maintainers don't need a PR.

The workflow is:

1. Record the bug or planned change in an issue.
2. Work on a feature/fix branch and open a PR into `dev`.
3. Run the relevant local tests and let the GitHub checks pass before merging.
4. When it's ready for a release, maintainers open a separate `dev` → `main` PR.
5. Tag the reviewed source and build the release from it. Keep `dev` synced with `main` after the merge.

Keep each PR focused on one topic. For game testing, include the version, scene and roughly how long you played. Changes to the lifter or CPU headers also need the differential tests in [the engine build guide](docs/building.md#checks).

Use plain English commit messages, without prefixes like `feat:`. Please read and test what you submit.

## Reusing code

Code copied from another project must be MIT, BSD, ISC, zlib or Apache-2.0. Keep its copyright header and add the source, commit and license to [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

GPL projects can be read to understand behavior, but their code isn't copied here. Unicorn is fine as a separate test tool, not as part of the game executable.

## Code and docs

Write in English. Don't edit generated game code by hand—fix the generator instead.
