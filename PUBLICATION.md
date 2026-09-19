# Public-release boundary

Publication is an explicit operator action, never performed by the add-on or
build script. The first public release is version 0.1.0, marked as a beta
pre-release under AngelsClan, licensed GPL version 2 or later.

The installer is built only from `addon/` and LICENSE. It does not read the
user's NVDA profile, passwords, VM images, voice licenses, recordings or logs.
The generic pipe default is not tied to an individual VM. Paths in setup examples
are examples that another user chooses on their own machine.

Before creating the Angels Clan GitHub repository:

1. `python build.py` exports a reviewed source snapshot containing `addon/`, `bridge/`, `tests/`,
   `tools/`, `build.py`, LICENSE, README, PROTOCOL, CHANGELOG and a sanitized
   qualification report and OPERATIONS. Include generic ignore/line-ending configuration.
2. Do not export private continuity notes (`memory.md`), credentials, test logs,
   existing `.git`, app configuration, proprietary voices or VM files.
3. Review the exported file list and contents, build from that snapshot, and
   inspect the resulting archive. The current local Git history contains
   machine-specific continuity notes: excluding their latest file alone does
   not remove historical copies. Use a clean public history, or separately
   review/sanitize history before pushing. Do not rewrite the private repository
   as a shortcut without the user's approval.
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
