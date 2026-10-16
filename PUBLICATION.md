# Public-release boundary

This checklist is for maintainers preparing a release. Users looking for
installation steps should start with the [README](README.md). The current
development build has no public installer release; this checklist does not
announce one.

Publication is an explicit operator action, never performed by the add-on or
build script. The repository already exists under AngelsClan and is licensed GPL version 2
or later. The published beta releases are separate from the current development
source; version 0.1.1 remains the latest uploaded beta at this maintenance pass.

The installer is built only from `addon/` and LICENSE. It does not read the
user's NVDA profile, passwords, VM images, voice licenses, recordings or logs.
The generic pipe default is not tied to an individual VM. Paths in setup examples
are examples that another user chooses on their own machine.

Before publishing a source update or creating another release:

1. `python build.py` exports a reviewed source snapshot containing `addon/`, `bridge/`, `tests/`,
   `tools/`, `build.py`, LICENSE, README, PROTOCOL, CHANGELOG and a sanitized
   qualification report and OPERATIONS. Include generic ignore/line-ending configuration.
2. Do not export private continuity notes (`memory.md`), credentials, test logs,
   existing `.git`, app configuration, proprietary voices or VM files.
3. Review the exported file list and contents, build from that snapshot, and
   inspect the resulting archive. The historical private checkout is distinct from this public repository.
   Export only reviewed project files, inspect the staged diff, and preserve
   private continuity notes outside public history. Never rewrite pushed history
   as part of routine maintenance.
4. Confirm the Git author/email chosen for public commits. GitHub naturally
   displays account/organization and commit metadata; those are separate from
   private machine configuration and are not automatically anonymized.
5. Keep test claims precise: user reports good listening results on the tested
   setup, not universal compatibility. VMware, separate XP service packs and
   headless audio require their own qualification.

Upload the exact tested `.nvda-addon`, XP helper EXE, curated source ZIP and their
SHA-256 sidecars. Mark the GitHub release as a pre-release. Verify the assets
after upload. Do not submit to the NVDA Add-on Store or claim additional platform
qualification merely because the GitHub release exists.
