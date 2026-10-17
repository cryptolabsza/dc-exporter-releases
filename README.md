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

## Publisher preparation status

The prepared manual workflow validates the exact source run and archive with a
read-only release-repository token. It creates, changes and deletes no release
assets. The reusable recipe pin must be replaced with its reviewed immutable
commit before runner admission and rehearsal.

The trusted helper retains explicit `--publish` and `--recover-stage-id` routes.
They require a separately approved protected writable workflow; this prepared
workflow cannot invoke them. Recovery uses only the release repository token and
recorded stage receipts, so an unavailable source-reader App does not prevent
restoration of the complete previous release. Historical assets and their
original metadata/provenance remain preserved. Writable activation, public asset
replacement and stable RTX 5090 promotion remain held for owner review.
