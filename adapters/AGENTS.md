# Adapter production contract

When asked to analyze/adapt a future WoTB version, preserve the distinction
between internal production and recipient encryption. Deliver a versioned
`.bcpro` master and its source recipe. Do not require a recipient device config
or publish signing keys to complete analysis or master creation.

Follow `publisher/schema/pro-source-v1.schema.json` and the frozen
`publisher/schema/adapter-api-v1.json`. Create a new recipe directory for each
client build. Use a new release revision whenever code, native components,
notes or verification evidence change; never silently replace an already
issued release with different contents under the same adapter_id/version.

Record the exact game SHA-256, channel, build, architecture, minimum host,
native manifest list and verification evidence. Keep prior recipes/evidence.
Copy the example recipe structure rather than inventing a different layout.
Native code, ABI guards and offsets require version-specific research and
tests; changing version strings alone does not constitute adaptation.

Run the ordinary regression suite and the publisher master/package tests.
Create the master with `python -m publisher.cli make --recipe <adapter.json>
--output <new-file.bcpro>`, then inspect it with `python -m publisher.cli inspect
<new-file.bcpro>`. The tool performs only static inspection, never executes
adapter code. Describe which game tests were actually performed; use
validation level `offline` when no new live-game test was run.

The finished master contains plaintext implementation and is for the
maintainer only. Recipient packages are generated later with Pro Studio or
`publisher.cli issue`. Keep published client `.bcupdate` protocol compatible
with the declared adapter API; changes to the host contract need a host update.

See the repository README section “Pro Studio 与适配母包规范” for the full workflow.
