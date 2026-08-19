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
3. Merge to `main` with a fast-forward whenever one is possible:

   ```
   git checkout main && git merge --ff-only <branch>
   ```

   This is the normal case, not the lucky one. `main` only moves when a release
   lands, so unless one landed while you were working, `main` is still the commit
   you branched from and the branch's own commits become the release exactly as
   written.

4. Make a real merge commit only when a fast-forward genuinely cannot happen —
   `main` moved ahead while the branch was open. Then either rebase onto `main`
   and fast-forward as above, or `git merge --no-ff` if the branch is worth
   keeping as a distinguishable unit of history. Reaching for `--no-ff` when
   `--ff-only` would have worked adds a merge commit that records nothing.

5. After merging, tag the release commit `v<version>`.

`pi install git:github.com/jhs/cccp@v<version>` pins on that tag.
