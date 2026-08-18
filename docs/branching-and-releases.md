# Branching & Releases

`main` is the published state: the marketplace and plugin metadata on `main` (`.claude-plugin/marketplace.json`, `.claude-plugin/plugin.json`) are what users install. Do development on branches, never directly on `main`.

## Starting a branch

After creating a branch, make the version bump your first commit — it keeps the manifests in lockstep from the start and avoids a forgotten bump at merge time. If the user hasn't specified a version, ask whether the change is a major, minor, or patch bump and propose the next number.

## Cutting a release

1. Work on a branch (names are free-form).
2. The version in both manifests must be bumped before merging (ideally as the first commit on the branch):
   - `.claude-plugin/plugin.json`
   - `package.json` (the pi-package manifest)
   The merge itself is the release.
3. After merging, tag the release commit `v<version>`.

`pi install git:github.com/jhs/cccp@v<version>` pins on that tag.
