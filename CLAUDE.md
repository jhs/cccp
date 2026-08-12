# Branching & Releases

- `main` is the published state: the marketplace and plugin metadata on `main` (`.claude-plugin/marketplace.json`, `.claude-plugin/plugin.json`) are what users install. Do development on branches, never directly on `main`.
- Branch names are free-form. Before merging back to `main`, bump the version and metadata in both `.claude-plugin/*.json` files AND the root `package.json` (the pi-package manifest; all three stay in lockstep) so the merge itself is the release.
- After merging, tag the release commit (`v<version>`) — `pi install git:github.com/jhs/cccp@v<version>` pins on that tag.
