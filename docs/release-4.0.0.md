# KOI 4.0.0 release procedure

KOI 4.0.0 production artifacts must be built from a committed, completely clean Git tree. Local `Report_Template/` files are private user resources and must not be tracked or copied into public artifacts. Portable and NSIS packages seed only the setup instructions from `tauri-ui/src-tauri/resources/report-template-placeholder/`; users supply their own templates in the user data directory, and upgrades preserve existing templates. Automated report tests use synthetic fixtures.

The default `build_release.cmd -Verify` is a local build and accepts pending source edits. It updates `dist-tauri/4.0.0` and preserves the existing `koi-data`; the downloadable ZIP is staged with clean seed data. Use `-StrictRelease` for the clean committed production procedure below.

The current fixes restore the Python Agent's session queue, report and target tools, separate a fresh AI round from old fast-mode report evidence, and preserve both the user's task and file evidence across Continue. Notice processing removes authorization-letter output and verifies and consumes source archives before classification and rewriting. See [Agent tool parity](agent-tool-parity.md) for the execution mapping and verification limits.

## Build from the final commit

`push_workflow.ps1` publishes committed source and the release tag together with an atomic Git push. It checks every Git exit code and verifies both remote references after the push. A failed preflight does not move the local tag; a rejected push restores the previous local tag. No remote release tag is deleted.

Review the working-tree changes, then run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\push_workflow.ps1`. By default the script commits every non-ignored change after the remote preflight; use `-CommitMessage "fix: describe the release changes"` to name the commit, or `-NoCommit` to require a clean tree. Use `-DryRun` to preview operations; it never commits or updates refs. Git connects directly by default; `-UseProxy` restores the configured Git HTTP proxy. An existing release tag is updated to the hotfix commit with an exact lease in the same atomic push as the branch; use `-PreserveTag` for a branch-only build. The final script message confirms the push only; inspect GitHub Actions to confirm that the build and publication succeeded.

If direct access to GitHub is unavailable, restore the network route or pass `-UseProxy` after restoring the proxy. A network failure must not be interpreted as a missing remote tag.

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
        -StrictRelease `
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

短复测计划、运行状态和执行轨迹的正文均可展开/收起，展开后显示完整内容并自动换行，不再根据 80 字阈值取消详情入口。
通报处理断点保存在 koi-data/.koi-runtime/notice-process-state，不再在通报输出目录生成 JSON。旧目录内的断点会在下次处理、分类或清理时迁移。删除过程文件能清理解压后遗留的父目录记录，并保留未完成任务的断点、正式产物和用户 JSON。


The Windows CI workflow prepares its own Microsoft C++ workload and Windows SDK, with installation from the signed Microsoft installer if required. It never imports a developer portable tool directory. npm installs the lockfile dependency tree and Playwright downloads its exact Chromium build. Cargo network fetching remains enabled. Missing CPython/PDFium/NanaZip runtime files are restored from their official hash-locked archives, then the existing publisher-signature and runtime-binding gates verify them. Optional nmap/ffuf audit artifacts use their locked URLs/hashes, bounded download retries and the official GitHub asset API if a release-download connection fails. A runtime repair does not weaken provenance checks.

Packaged self-tests are awaited through Start-Process and their JSON proof is checked, including 97 handlers and runtime results. Native finalize/verify failures stop the job. Concurrent updates of one tag cancel the old build, and publication checks the current remote tag still matches the built source. Artifact upload requires files; failed runs retain browser and self-test diagnostics. Push source validation checks the contract, current behavior matrix and available Rust formatting before any commit/tag mutation. Direct Git requests clear generic, URL-specific and environment proxy values only for the request and restore the caller's environment afterward.

Dependency HTTP requests use the runner-provided Windows curl with a 20-second connection deadline and a 120-second complete-transfer deadline (60 seconds for release metadata). Each failed attempt records its cause and removes partial files before retrying. This avoids PowerShell Invoke-WebRequest requests remaining blocked beyond their configured timeout.
