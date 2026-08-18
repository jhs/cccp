# Branching & Releases

`main` is the published state: the marketplace and plugin metadata on `main` (`.claude-plugin/marketplace.json`, `.claude-plugin/plugin.json`) are what users install. Do development on branches, never directly on `main`.

## Cutting a release

1. Work on a branch (names are free-form).
2. Before merging back to `main`, bump the version and metadata in all three manifests, kept in lockstep:
   - `.claude-plugin/marketplace.json`
   - `.claude-plugin/plugin.json`
   - `package.json` (the pi-package manifest)
   The merge itself is the release, so the version must be bumped before you merge.
3. After merging, tag the release commit `v<version>`.

`pi install git:github.com/jhs/cccp@v<version>` pins on that tag.
