# KOI 4.0.0 release procedure

KOI 4.0.0 production artifacts must be built from a committed, completely clean Git tree. The release gates intentionally do not allow exceptions for local session files, report templates, ignored runtime files, or other user state. A changed template must either be reviewed and included in the final source commit or remain outside the release checkout.

## Build from the final commit

`push_workflow.ps1` publishes committed source and the release tag together with an atomic Git push. It checks every Git exit code and verifies both remote references after the push. A failed preflight does not move the local tag; a rejected push restores the previous local tag. No remote release tag is deleted.

Review and commit intended changes first, then run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\push_workflow.ps1`. To explicitly include every non-ignored working-tree change in the release commit, pass `-CommitChanges -CommitMessage "fix: describe the release changes"`. Use `-DryRun` to preview operations; it never commits or updates refs. Existing remote release tags require `-Force` and are updated with an exact lease, while the branch still requires a normal fast-forward. The final script message confirms the push only; inspect GitHub Actions to confirm that the build and publication succeeded.

If Git reports a refused connection to a local proxy, restore that proxy or configure the repository to use a working connection before publishing. A network failure must not be interpreted as a missing remote tag.

Run these commands from the normal repository after all intended source and locked runtime files have been committed. Do not copy the current working directory into the release directory.

```powershell
$revision = (git rev-parse --verify 'HEAD^{commit}').Trim()
if ($revision -notmatch '^(?:[0-9a-f]{40}|[0-9a-f]{64})$') {
    throw "Git did not return a full commit object ID: $revision"
}

$releaseWorktree = Join-Path (Split-Path -Parent (Get-Location)) "wow-release-$($revision.Substring(0, 12))"
git worktree add --detach $releaseWorktree $revision

Push-Location $releaseWorktree
try {
    $env:KOI_SOURCE_REVISION = $revision
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build_release.ps1 `
        -Verify `
        -ReleaseBase 'dist-tauri\4.0.0' `
        -CargoTargetDir '.cargo-target-release'
}
finally {
    Pop-Location
}
```

The strict preflight fails if the detached worktree is dirty, if `KOI_SOURCE_REVISION` is abbreviated or differs from `HEAD`, if the 97-command contract and Rust handler registry differ, or if the 97-command behavior matrix is incomplete or stale. The matrix verifier requires every command to be `equivalent`, `improved`, or an explicitly reviewed `security-exception`; it rejects missing scenario evidence, unknown evidence files/tests, source-manifest drift, golden-fixture drift, unverified commands, and unexplained differences. It also records a build-source stamp below the Cargo target, removes stale release executables before compilation, and requires the rebuilt executable and NSIS installer to be newer than that stamp.

The v3.1.4 oracle is a capability and workflow baseline, not a requirement to regress Rust safety. DPAPI secret storage, masked configuration responses, token-authenticated loopback WebSockets, generation-based late-result rejection, AppContainer probes, and the built-in bounded SQL validator remain accepted improvements. The external Python oracle is development-only; production and CI consume the checked-in redacted fixtures and never package or launch the legacy business backend.

`finalize-release.mjs` only accepts the exact portable ZIP and NSIS names. It records the same full source revision in `release-manifest.json`, `koi-portable.marker`, and `supply-chain.json`; inventories required build/lock inputs with byte sizes and SHA-256 values; and writes `SHA256SUMS`. `verify-release.mjs` then rehashes every input and artifact, compares the ZIP file inventory and bytes with the staged `koi/` and clean `koi-data/` trees, and rejects Python business artifacts, symbolic links, browser profiles, configuration, DPAPI state, sessions, checkpoints, and logs.

Before tagging, repeat the release verifier in the clean worktree and confirm that the tag is exactly `v4.0.0`. The CI release workflow performs the same checks and only publishes on that exact tag.

## Signed archive runtime

The bundled archive engine is NanaZip 7.0.1832.0 (7-Zip engine 2609.1). KOI validates the exact Microsoft Marketplace signed x64 MSIX with WinVerifyTrust and then requires every executable/runtime DLL to be byte-identical to its entry in that signed package. The extracted PE files are not described as independently signed. Release verification must retain the `publisher-signed-msix-runtime-binding-v1` metadata and fail when either the publisher signature or the package-to-runtime binding is absent.
