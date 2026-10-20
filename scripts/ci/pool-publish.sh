#!/usr/bin/env bash
# TRACEWEAVER: file-role=bounded-shared-publisher-entrypoint; req=REQ-PUB-003; trace=TRACE-PUB-003; ver=VER-PUB-003
# Trusted release-repository launcher; downloaded artifact data never enters commands.
set -euo pipefail
umask 077
[[ "${GITHUB_REPOSITORY:-}" == cryptolabsza/dc-exporter-releases ]]
[[ "${GITHUB_REPOSITORY_ID:-}" == 1141480624 ]]
[[ "${GITHUB_EVENT_NAME:-}" == workflow_dispatch ]]
[[ "${GITHUB_REF:-}" == refs/heads/main ]]
[[ "${GITHUB_DEFAULT_BRANCH:-}" == main ]]
[[ "${GITHUB_REF_PROTECTED:-}" == true ]]
[[ "${GITHUB_WORKFLOW_REF:-}" == cryptolabsza/dc-exporter-releases/.github/workflows/publish.yml@refs/heads/main ]]
[[ "${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$ ]]
[[ "${GITHUB_RUN_ID:-}" =~ ^[1-9][0-9]*$ ]]
[[ "${GITHUB_RUN_ATTEMPT:-}" =~ ^[1-9][0-9]*$ ]]
mode="${1:-}"
[[ $# == 1 ]]
preflight=false
if [[ "$mode" == preflight ]]; then
  preflight=true
  mode="${INPUT_MODE:-}"
fi
[[ "$mode" == validate || "$mode" == publish || "$mode" == recover ]]
# Validate uncredentialed dispatch/configuration before any container or App mint.
# These same checks run again for the later credentialed operation.
if [[ "$mode" == recover ]]; then
  [[ "${INPUT_RECOVER_STAGE_ID:-}" =~ ^[1-9][0-9]*$ ]]
  [[ -z "${INPUT_RUN_ID:-}${INPUT_RUN_ATTEMPT:-}${INPUT_ARTIFACT_ID:-}${INPUT_SHA:-}${INPUT_BRANCH:-}" ]]
else
  [[ -z "${INPUT_RECOVER_STAGE_ID:-}" ]]
  [[ "${INPUT_RUN_ID:-}" =~ ^[1-9][0-9]*$ ]]
  [[ "${INPUT_RUN_ATTEMPT:-}" =~ ^[1-9][0-9]*$ ]]
  [[ "${INPUT_ARTIFACT_ID:-}" =~ ^[1-9][0-9]*$ ]]
  [[ "${INPUT_SHA:-}" =~ ^[0-9a-f]{40}$ ]]
  [[ "${INPUT_BRANCH:-}" == dev || "${INPUT_BRANCH:-}" == main ]]
  [[ "$mode" != publish || "$INPUT_BRANCH" == dev ]]
  [[ "${SOURCE_WORKFLOW_ID:-}" =~ ^[1-9][0-9]*$ ]]
fi
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
if [[ "$preflight" == true ]]; then
  # No credentials are supplied to this first invocation.
  exec docker run "${common[@]}" --network none "$image" scripts/ci/publish.py --preflight
fi
identity=(--env GITHUB_REPOSITORY --env GITHUB_REPOSITORY_ID
  --env GITHUB_DEFAULT_BRANCH --env GITHUB_REF --env GITHUB_REF_PROTECTED
  --env GITHUB_EVENT_NAME --env GITHUB_WORKFLOW_REF --env GITHUB_SHA
  --env GITHUB_RUN_ID --env GITHUB_RUN_ATTEMPT)
if [[ "$mode" == recover ]]; then
  [[ -n "${GITHUB_TOKEN:-}" ]]
  # Recovery deliberately receives no source configuration or reader credential.
  exec docker run "${common[@]}" --network bridge \
    "${identity[@]}" --env GITHUB_TOKEN \
    "$image" scripts/ci/publish.py --recover-stage-id "$INPUT_RECOVER_STAGE_ID"
fi
[[ -n "${SOURCE_READER_TOKEN:-}" && -n "${GITHUB_TOKEN:-}" ]]
operation=--validate-only
if [[ "$mode" == publish ]]; then operation=--publish; fi
# Only this fixed allowlist crosses into the unprivileged container. Values are
# forwarded from runtime environment, never written into a file or command line.
exec docker run "${common[@]}" --network bridge \
  --env SOURCE_READER_TOKEN --env GITHUB_TOKEN --env SOURCE_WORKFLOW_ID \
  "${identity[@]}" \
  "$image" scripts/ci/publish.py "$operation" \
  --run-id "$INPUT_RUN_ID" --run-attempt "$INPUT_RUN_ATTEMPT" \
  --artifact-id "$INPUT_ARTIFACT_ID" --sha "$INPUT_SHA" --branch "$INPUT_BRANCH"
