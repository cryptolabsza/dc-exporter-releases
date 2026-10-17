#!/usr/bin/env bash
# TRACEWEAVER: file-role=bounded-shared-publisher-entrypoint; req=REQ-PUB-003; trace=TRACE-PUB-003; ver=VER-PUB-003
# Trusted release-repository launcher; downloaded artifact data never enters commands.
set -euo pipefail
umask 077
[[ "${GITHUB_REPOSITORY:-}" == cryptolabsza/dc-exporter-releases ]]
[[ "${GITHUB_REPOSITORY_ID:-}" == 1141480624 ]]
[[ "${GITHUB_EVENT_NAME:-}" == workflow_dispatch ]]
[[ "${GITHUB_REF:-}" == refs/heads/main ]]
[[ "${GITHUB_REF_PROTECTED:-}" == true ]]
[[ "${GITHUB_WORKFLOW_REF:-}" == cryptolabsza/dc-exporter-releases/.github/workflows/publish.yml@refs/heads/main ]]
[[ "${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$ ]]
[[ "${GITHUB_RUN_ID:-}" =~ ^[1-9][0-9]*$ ]]
[[ "${GITHUB_RUN_ATTEMPT:-}" =~ ^[1-9][0-9]*$ ]]
mode="${1:-}"
[[ "$mode" == preflight || "$mode" == validate ]]
[[ $# == 1 ]]
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
[[ ! -L "$root/scripts/ci/publish.py" && -f "$root/scripts/ci/publish.py" ]]
image='rust:1.88.0-bookworm@sha256:4727898c104ecd2e22d780925832502faee9fe4e70581b8572af081370b315a0'
common=(--rm --pull never --user 65534:65534 --cap-drop ALL
  --security-opt no-new-privileges:true --read-only --pids-limit 128
  --memory 2g --memory-swap 2g --cpus 2 --ulimit core=0 --ulimit nofile=256:256
  --mount "type=bind,src=$root,dst=/publisher,readonly"
  --tmpfs /tmp:rw,nosuid,nodev,noexec,uid=65534,gid=65534,mode=0700,size=16m
  --workdir /publisher --env PYTHONDONTWRITEBYTECODE=1 --env PYTHONUNBUFFERED=1
  --entrypoint /usr/bin/python3)
if [[ "$mode" == preflight ]]; then
  # No credentials are supplied to this first invocation.
  exec docker run "${common[@]}" --network none "$image" scripts/ci/publish.py --preflight
fi
[[ "${INPUT_RUN_ID:-}" =~ ^[1-9][0-9]*$ ]]
[[ "${INPUT_RUN_ATTEMPT:-}" =~ ^[1-9][0-9]*$ ]]
[[ "${INPUT_ARTIFACT_ID:-}" =~ ^[1-9][0-9]*$ ]]
[[ "${INPUT_SHA:-}" =~ ^[0-9a-f]{40}$ ]]
[[ "${INPUT_BRANCH:-}" == dev || "${INPUT_BRANCH:-}" == main ]]
[[ -n "${SOURCE_READER_TOKEN:-}" && -n "${GITHUB_TOKEN:-}" ]]
# Only this fixed allowlist crosses into the unprivileged container. Values are
# forwarded from runtime environment, never written into a file or command line.
exec docker run "${common[@]}" --network bridge \
  --env SOURCE_READER_TOKEN --env GITHUB_TOKEN --env SOURCE_WORKFLOW_ID \
  --env GITHUB_REPOSITORY --env GITHUB_DEFAULT_BRANCH --env GITHUB_REF \
  --env GITHUB_EVENT_NAME --env GITHUB_WORKFLOW_REF --env GITHUB_SHA \
  "$image" scripts/ci/publish.py --validate-only \
  --run-id "$INPUT_RUN_ID" --run-attempt "$INPUT_RUN_ATTEMPT" \
  --artifact-id "$INPUT_ARTIFACT_ID" --sha "$INPUT_SHA" --branch "$INPUT_BRANCH"
