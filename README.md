# CryptoLabs DC Exporter releases

Linux GPU monitoring binaries and DEB packages from [CryptoLabs](https://www.cryptolabs.co.za/).

[DC Exporter source](https://github.com/cryptolabsza/dc-exporter-rs-public) contains
the implementation, tests, thermal compatibility records and contribution guide.
This repository distributes release assets. For GPU server failure investigation,
explore [CryptoLabs AI SRE](https://www.cryptolabs.co.za/services/).

## Choose an artifact

- [Stable releases](https://github.com/cryptolabsza/dc-exporter-releases/releases)
- [Development channel](https://github.com/cryptolabsza/dc-exporter-releases/releases/tag/dev-latest)

Existing stable **0.2.8** assets retain their original source/build provenance.
They are not retroactively builds from the fresh open-source history. The current
development source remains **0.2.7**; its version alone does not identify the newer
candidate. Check the release's source repository, commit, build record and SHA-256.

Development output is experimental. The mutable `dev-latest` name is a channel,
not an immutable identity. Retain the exact artifact hash and corresponding build
manifest when testing or deploying a candidate.

For versioned **0.3.0** artifacts, the manifest identifies the exact protected
source `main` commit and successful build. The source tag `v0.3.0` identifies
that commit; the tag in this distribution repository identifies the trusted
publisher commit. The fixed `v0.3.0-limited-qualification` policy is a normal
software release with the experimental feature limits below. It does not
establish full hardware acceptance. Historical stable **0.2.8** assets and
development releases keep their original provenance.

## Verify and install

Download from the intended release, verify the published SHA-256 and source/build
provenance, then review the package contents and service permissions before use.
The release executable is `dc-exporter-rs`; the DEB package is `dc-exporter-rs` and
the service is `dc-exporter.service`.

```sh
sha256sum dc-exporter-rs_VERSION_amd64.deb
sudo dpkg -i dc-exporter-rs_VERSION_amd64.deb
sudo systemctl status dc-exporter
curl http://localhost:9835/metrics
```

Compare the displayed digest with the accepted release manifest. Installation and
service activation should follow the operator's own maintenance and rollback plan.
The default HTTP listener binds all interfaces on **9835**; restrict access to
trusted monitoring systems.

## Compatibility and diagnostics

Experimental RTX 5090 RUSD memory collection is opt-in and limited to Linux
x86-64, PCI device `0x2b85`, and exact drivers `590.48.01`, `595.99.02` or
`615.71.09`. Unknown versions fail closed. Limited functional reads have been
observed on 590 and 615; this publication record does not verify loaded-driver
595 behavior or establish full accuracy, GPU Burn/NCCL qualification or universal
hardware support. Read the source repository's compatibility record before use.

The exporter reports numeric recovery/error diagnostics. A reset-required GPU can
have readable basic telemetry and still report `GPU_ERROR_STATE=2`; that state
does not itself prove permanent hardware damage. The exporter performs no GPU
resets, reboots or workload changes.

Use `DCXP_FI_DEV_VRAM_TEMP_VALID` and backend/status metrics alongside temperature
values. Unsupported or failed measurements must not be interpreted as measured
zero. A successful scrape alone does not establish collection freshness.

## Build provenance and reporting

New official artifacts must originate from reviewed protected source refs built
through CryptoLabs' shared runner pool. Publication validates artifact identity
and exact bytes; public fork or unreviewed PR code must not receive trusted runner
or publication access.

Report ordinary defects in the [source issue tracker](https://github.com/cryptolabsza/dc-exporter-rs-public/issues).
Use the source repository's security policy for vulnerabilities. Include the
artifact SHA-256, source commit, driver version and sanitized diagnostic samples;
remove credentials, client data and private infrastructure identifiers.

Project and third-party license notices must accompany each new binary/package
release. Historical assets keep their original provenance and are identified
separately from new-source builds.

## Protected publisher workflow

Manual dispatch defaults to `mode=validate`. Its separate
`dc-exporter-validate.yml` recipe contains only the read-only validation job.
The `dc-exporter-publish.yml` recipe contains only explicit publish and recovery
jobs. GitHub checks every nested job permission before evaluating job conditions;
this split keeps the default caller within its read-only permission ceiling. Validation uses a read-only release
repository token and checks the exact protected source run, attempt, artifact,
commit and branch without changing release assets. Supply `run_id`,
`run_attempt`, `artifact_id`, `sha` and `branch` (`dev` or `main`). Leave
`recover_stage_id` empty.

`mode=publish` with `branch=dev` is an explicit development publication request. Supply the same
exact source receipt with `branch=dev`; the protected job alone receives release
repository `contents: write`. The trusted helper verifies all ten
archive entries, uploads the immutable `dev-<source SHA>` set without clobbering
existing bytes, then stages the `dev-latest` replacement with recorded recovery
receipts. The previous complete release and its original metadata remain
available. Downloaded artifact content is never executed.

The reviewed versioned route uses `branch=main`, `tag=v0.3.0` and
`release_policy=v0.3.0-limited-qualification` with the exact source receipt.
Both `mode=validate` and `mode=publish` check this fixed policy, artifact version,
current source main, peeled source tag, ancestry, target tag and existing release
metadata/assets. Validation performs GET requests only. An ordinary main
validation without tag/policy remains an artifact-only check.

Versioned publication creates a private draft containing fixed qualification
disclosures, exact source/run/attempt/artifact/publisher provenance and every asset
hash. It resumes only a matching draft with identical existing bytes. After all
ten assets are read back, one final transition publishes `v0.3.0` as a normal
release and selects it as latest. Main and source tag are checked before every
mutation and after completion; these observations do not make two repositories
an atomic transaction. An exact complete published retry performs no writes.
Conflicting metadata/bytes, duplicate releases or a partial public release stop
publication. Before final publication, a failed operation leaves a private draft
for an exact-input retry. An empty or incomplete asset left by a failed upload
also causes HOLD; recovery requires a separately reviewed, scoped action.
If the final response is lost, authenticated readback
must establish the result; this route never deletes history or rotates dev aliases.
RTX 5090 remains opt-in and experimental, full GPU Burn/NCCL qualification is
pending, and operational live VM passthrough acceptance is pending.

`mode=recover` requires only the recorded target release `recover_stage_id`.
Leave every source receipt field, including `branch`, empty. This separate job
receives only the release repository writer token: it neither mints a
source-reader App token nor requires source workflow configuration or source
network access. Recovery verifies the recorded stage and restores a complete
asset set after an interrupted replacement. Mixed source/recovery inputs fail
closed before the workflow provides credentials.
Leave `tag` and `release_policy` empty for both development publication and recovery.

All modes require this repository's exact identity, protected `main`, default
branch `main`, manual dispatch and the protected caller workflow. Source-reading
jobs mint a dedicated App token limited to `dc-exporter-rs-public` with Actions
and contents read permissions. The bounded nonroot publisher container forwards
credentials by environment name and retains its resource limits and read-only
mounts. Full-hardware-qualification publication remains disabled
(`HARDWARE_ACCEPTED=False`); only the separately reviewed v0.3.0 policy enables
the bounded versioned software release described above.

Both recipe paths are pinned to reviewed commit
`410a8b15b15f1959314c5b47248987fd5587ae9d`. Read-only validation uses its
separate recipe; publishing and recovery use explicit modes in the writer
recipe. Runtime validation does not establish hardware qualification.

Before container preflight or source-reader token minting, each recipe supplies
the actual default branch, selected mode and applicable receipt/configuration
through explicit credential-free environment mappings. The launcher validates
that same input family and syntax again before the final operation. Recovery
preflight receives only target identity, mode and stage ID.

## Offline publisher checks

Tests use Python 3 and the test-only PyYAML dependency (verified locally with
PyYAML 6.0.3); the publisher runtime requires only the Python standard library.
The launcher tests substitute an inert argument capture executable for Docker.
Transport tests use opaque fixture bytes and a synthetic GitHub transport.
They perform no network requests, container launches or artifact execution.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
bash -n scripts/ci/pool-publish.sh
```
