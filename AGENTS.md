# Release coordination

For versioning, packaging, release summaries, and trial-feedback work, first read
`research/notes/release-1.0.0.md` and keep that single checklist current.

The user's confirmed release target is **1.0.0 final**, after their own trial.
The issued **1.0.1-beta** package is an interim verification build for that target,
not a separate 1.0.1 final-release plan. Preserve issued package identities and
contents for traceability. Do not infer a new final version from an interim patch.

Keep development verification separate from user/game confirmation. Consolidate
new feedback into the checklist; the user has not yet ended the trial or requested
the final release. Adapter work also follows `adapters/AGENTS.md`.

Before delivering replay-related updates, run `tools.test_packaged_replay_source`
against the final built package and the issued Pro master, without `--source-host`.
Import-only adapter checks do not verify host/adapter replay association. Also
verify each distributed app delta through `tools.test_offline_update_runtime`
with its exact baseline and signed package. Record the evidence in the checklist.
Pro activation/restart changes additionally require `tools.test_pro_restart_runtime`
on the built desktop, proving automatic restart, completed first intro, and a
subsequent daily launch without repeating it.
