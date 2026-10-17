# TRACEWEAVER: file-role=public-pool-publisher-contract-fixtures; req=REQ-PUB-006; trace=TRACE-PUB-006; ver=VER-PUB-006
# TRACEWEAVER: verifies=VER-PUB-006; req=REQ-PUB-006; trace=TRACE-PUB-006
"""Public-pool publisher contract: tests are authored before implementation.

Opaque payloads are deliberately non-executable. The producer integration test
will use the actual source producer once its approved implementation exists.
"""
import contextlib
import copy
import hashlib
import io
import importlib.util
import tempfile
import json
import os
import pathlib
import stat
import unittest
import urllib.request
import urllib.parse
import warnings
import zipfile
from unittest import mock
import test_ci_publisher as baseline


VERSION = '0.2.7'
SHA = 'a' * 40
SOURCE = dict(repository='cryptolabsza/dc-exporter-rs-public', repository_id=1416116330,
              sha=SHA, ref='refs/heads/dev', run_id=10, run_attempt=2,
              artifact_name=f'dc-exporter-1416116330-10-2-{SHA}')


def archive(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as output:
        for name, payload in files.items():
            output.writestr(name, payload)
    return stream.getvalue()


def bundle(*, source=None, additions=None, omissions=(), checksum_mutation=None):
    source = copy.deepcopy(SOURCE if source is None else source)
    files = {'dc-exporter-rs': b'NEVER EXECUTE THIS OPAQUE FIXTURE',
             'dc-exporter-rs_amd64.deb': b'OPAQUE DEB; NO PACKAGE HOOK EXECUTION',
             f'dc-exporter-rs_{VERSION}_amd64.deb': b'OPAQUE DEB; NO PACKAGE HOOK EXECUTION',
             'BUILD_INFO.txt': b'fixture only\n', 'VERSION.txt': b'dc-exporter 0.2.7\n',
             'HELP.txt': b'Usage: dc-exporter-rs [--tui]\n', 'SYMBOLS.txt': b'opaque symbols\n',
             'THIRD-PARTY-NOTICES.md': b'# Project and third-party notices\nFixture MIT terms.\n'}
    files.update(additions or {})
    for name in omissions:
        files.pop(name)
    checksums = ''.join(f'{hashlib.sha256(data).hexdigest()}  {name}\n' for name, data in sorted(files.items())).encode()
    files['SHA256SUMS'] = checksums if checksum_mutation is None else checksum_mutation(checksums)
    manifest = dict(schema=1, source=source, cargo_version=VERSION, binary_version=VERSION,
                    files={name: dict(size=len(data), sha256=hashlib.sha256(data).hexdigest()) for name, data in files.items()})
    files['manifest.json'] = json.dumps(manifest, sort_keys=True).encode()
    return files


def historical_bundle(version, sha):
    # Phase1 RED captured this format via the actual preserved native producer.
    # Keep old bytes/provenance fixtures self-contained in the release repo.
    return baseline.LatestHTTPTransitionTests().bundle(version, sha)


class PublicArchiveContractTests(unittest.TestCase):
    def setUp(self):
        self.publisher = baseline.helper()

    def test_exact_ten_entry_archive_is_accepted_as_opaque_bytes(self):
        files = bundle()
        self.assertEqual(len(files), 10)
        self.assertEqual(len(json.loads(files['manifest.json'])['files']), 9)
        self.assertEqual(len(files['SHA256SUMS'].splitlines()), 8)
        checked, manifest = self.publisher.validate_archive(archive(files), SOURCE)
        self.assertEqual(checked, files)
        self.assertEqual(manifest['source'], SOURCE)

    def test_historical_six_entry_format_rejected_for_fresh_publication(self):
        historical = historical_bundle(VERSION, SHA)
        self.assertEqual(len(historical), 6)
        with self.assertRaises(ValueError):
            self.publisher.validate_archive(archive(historical), SOURCE)

    def test_complete_old_set_remains_accepted_as_previous_snapshot(self):
        historical = historical_bundle(VERSION, SHA)
        api = object.__new__(self.publisher.GithubAPI)
        api.verify_previous(historical)

    def test_complete_ten_entry_set_is_accepted_as_previous_snapshot(self):
        api = object.__new__(self.publisher.GithubAPI)
        api.verify_previous(bundle())

    def test_missing_notice_or_extra_asset_rejected_despite_consistent_manifest(self):
        for files in [bundle(omissions=['THIRD-PARTY-NOTICES.md']), bundle(additions={'postinst': b'do not execute'})]:
            with self.subTest(names=sorted(files)), self.assertRaises(ValueError):
                self.publisher.validate_archive(archive(files), SOURCE)

    def test_private_retained_repository_identity_rejected_with_matching_bytes(self):
        private = SOURCE | {'repository': 'cryptolabsza/dc-exporter-rs', 'repository_id': 1141426952,
                            'artifact_name': f'dc-exporter-1141426952-10-2-{SHA}'}
        with self.assertRaises(ValueError):
            self.publisher.validate_archive(archive(bundle(source=private)), private)

    def test_source_hash_attempt_run_and_ref_mismatch_rejected(self):
        for change in [{'sha': 'b' * 40}, {'run_id': 11}, {'run_attempt': 3}, {'ref': 'refs/heads/main'}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.publisher.validate_archive(archive(bundle(source=SOURCE | change)), SOURCE)

    def test_checksums_are_bound_to_every_payload_no_self_hash(self):
        for mutate in [lambda rows: b'0' * 64 + rows[64:], lambda rows: rows.split(b'\n', 1)[1],
                       lambda rows: rows + b'0' * 64 + b'  SHA256SUMS\n', lambda rows: rows + rows.splitlines(keepends=True)[0]]:
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                self.publisher.validate_archive(archive(bundle(checksum_mutation=mutate)), SOURCE)

    def test_version_text_cannot_disagree_with_manifest_even_when_hashes_match(self):
        files = bundle(additions={'VERSION.txt': b'dc-exporter 0.2.8\n'})
        with self.assertRaises(ValueError):
            self.publisher.validate_archive(archive(files), SOURCE)

    def test_consistent_manifest_with_corrupt_notice_hash_is_rejected(self):
        files = bundle()
        manifest = json.loads(files['manifest.json'])
        manifest['files']['THIRD-PARTY-NOTICES.md']['sha256'] = '0' * 64
        files['manifest.json'] = json.dumps(manifest).encode()
        with self.assertRaises(ValueError):
            self.publisher.validate_archive(archive(files), SOURCE)

    def test_new_archive_rejects_duplicate_symlink_traversal_and_oversize(self):
        files = bundle()
        for name, mode in [('dc-exporter-rs', stat.S_IFLNK | 0o777), ('../escape', stat.S_IFREG | 0o644), ('HELP.txt', stat.S_IFREG | 0o644)]:
            stream = io.BytesIO(archive(files))
            with warnings.catch_warnings(), zipfile.ZipFile(stream, 'a') as output:
                warnings.simplefilter('ignore', UserWarning)
                entry = zipfile.ZipInfo(name)
                entry.create_system = 3
                entry.external_attr = mode << 16
                output.writestr(entry, b'bad')
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.publisher.validate_archive(stream.getvalue(), SOURCE)
        with self.assertRaises(ValueError):
            self.publisher.validate_archive(archive(files), SOURCE, max_total=100)
        with mock.patch.object(self.publisher, 'MAX_FILE', 8), self.assertRaises(ValueError):
            self.publisher.validate_archive(archive(files), SOURCE)


class PreparationModeTests(unittest.TestCase):
    def setUp(self):
        self.publisher = baseline.helper()
        self.fixture = baseline.PublisherBoundaryTests()
        self.fixture.setUp()
        self.fixture.files = {name: data for name, data in bundle().items() if name != 'manifest.json'}
        self.fixture.manifest = json.loads(bundle()['manifest.json'])
        self.env = dict(SOURCE_WORKFLOW_ID='7', GITHUB_REPOSITORY='cryptolabsza/dc-exporter-releases',
                        GITHUB_DEFAULT_BRANCH='main', GITHUB_REF='refs/heads/main',
                        GITHUB_EVENT_NAME='workflow_dispatch',
                        GITHUB_WORKFLOW_REF='cryptolabsza/dc-exporter-releases/.github/workflows/publish.yml@refs/heads/main',
                        GITHUB_SHA='c' * 40)
        self.args = ['--run-id', '10', '--run-attempt', '2', '--artifact-id', '90', '--sha', SHA, '--branch', 'dev']

    def api(self):
        fixture = self.fixture
        class API:
            def __init__(self): self.writes = []
            def get_run(self, run_id, attempt): return fixture.run
            def get_artifact(self, artifact_id): return fixture.artifact
            def tip(self, branch): return SHA
            def download_artifact(self, artifact_id): return fixture.archive()
            def list_assets(self, tag): return {}
            def upload(self, tag, name, data): self.writes.append(('upload', tag, name))
            def replace_latest(self, files): self.writes.append(('replace_latest', sorted(files)))
        return API()

    def run_preparation(self, args):
        api = self.api()
        output = io.StringIO()
        with mock.patch.dict(os.environ, self.env, clear=True), contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = self.publisher.main(args, api=api)
        self.assertEqual(result, 0, output.getvalue())
        self.assertEqual(api.writes, [], 'preparation must never create/update/delete release assets')

    def test_default_manual_preparation_validates_without_any_release_writes(self):
        self.run_preparation(self.args)

    def test_explicit_validation_mode_performs_no_release_writes(self):
        self.run_preparation(['--validate-only'] + self.args)

    def test_legacy_archive_default_preparation_cannot_publish_old_format(self):
        historical = historical_bundle(VERSION, SHA)
        self.fixture.files = {n: d for n, d in historical.items() if n != 'manifest.json'}
        self.fixture.manifest = json.loads(historical['manifest.json'])
        api = self.api()
        with mock.patch.dict(os.environ, self.env, clear=True), contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            result = self.publisher.main(self.args, api=api)
        self.assertEqual(result, 1)
        self.assertEqual(api.writes, [])


class FormatTransitionRecoveryTests(baseline.LatestHTTPTransitionTests):
    # Inherited transport/fault tests are run again on new ten-entry bundles.
    def bundle(self, version, sha):
        source = SOURCE | {'sha': sha, 'artifact_name': f'dc-exporter-1416116330-10-2-{sha}'}
        return bundle(source=source)

    def test_old_six_to_new_ten_preserves_whole_previous_release(self):
        self.old = historical_bundle(VERSION, 'a' * 40)
        self.test_real_http_normal_version_transition_preserves_complete_old_and_new()

    def test_reader_unavailable_target_only_recovery_preserves_old_six_and_new_ten(self):
        old_six = historical_bundle(VERSION, 'a' * 40)
        for old in [old_six, self.old]:
            with self.subTest(old_entries=len(old)):
                self.old = old
                api, server = self.server()
                new_source = json.loads(self.new['manifest.json'])['source']
                stage_tag = 'dev-stage-50-1-' + new_source['sha']
                recipe = dict(schema=1, kind='dc-exporter-latest-stage', stage_tag=stage_tag,
                              source=new_source, publisher_sha='c' * 40,
                              previous=dict(id=1, tag='dev-previous-1', files=api.file_receipt(old)),
                              files=api.file_receipt(self.new))
                # Record a durable interrupted transaction; recovery must work
                # independently of both fresh-archive admission and source access.
                server.releases[1]['tag_name'] = 'dev-previous-1'
                server.releases[2] = dict(id=2, tag_name='dev-latest', draft=False,
                                         prerelease=True, body=json.dumps(recipe))
                server.files[2] = self.new.copy()
                server.denied_source = True
                env = dict(GITHUB_TOKEN='synthetic-writer', GITHUB_REPOSITORY='cryptolabsza/dc-exporter-releases',
                           GITHUB_DEFAULT_BRANCH='main', GITHUB_REF='refs/heads/main',
                           GITHUB_EVENT_NAME='workflow_dispatch',
                           GITHUB_WORKFLOW_REF='cryptolabsza/dc-exporter-releases/.github/workflows/publish.yml@refs/heads/main')
                with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(self.publisher, 'preflight'), \
                     mock.patch('urllib.request.build_opener', return_value=server), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(self.publisher.main(['--recover-stage-id', '2']), 0)
                self.assertEqual(server.source_reads, 0)
                self.assertEqual(server.latest()['id'], 1)
                self.assertEqual(server.files[1], old)
                self.assertEqual(server.files[2], self.new)
                self.assertEqual(server.releases[1]['body'], 'previous metadata')


class PreparationWorkflowContractTests(unittest.TestCase):
    def setUp(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        self.text = (root / '.github/workflows/publish.yml').read_text() + '\n' + (root / '.github/workflows/dc-exporter-publish.yml').read_text()

    def test_default_preparation_has_read_only_contents_permission(self):
        import re
        top_level = self.text.split('jobs:', 1)[0]
        self.assertIsNone(re.search(r'^  contents: write$', top_level, re.M))
        self.assertIn('contents: read', top_level)

    def test_trusted_publisher_uses_existing_shared_group_twelve_route(self):
        self.assertIn('ci-publish-ephemeral', self.text)
        self.assertNotIn('group: dc-exporter-publish', self.text)

    def test_preparation_workflow_calls_explicit_validation_without_secrets_inheritance(self):
        self.assertIn('--validate-only', self.text)
        self.assertNotIn('secrets: inherit', self.text)


class SharedRuntimeContractTests(unittest.TestCase):
    def test_effective_cpu_limit_respects_cgroup_quota_without_weakening_bound(self):
        publisher = baseline.helper()
        self.assertEqual(publisher.effective_cpu(4, ['max 100000', '200000 100000']), 2)
        self.assertEqual(publisher.effective_cpu(1, ['200000 100000']), 1)
        for values in [['garbage'], ['0 100000'], ['200000 0'], []]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                publisher.effective_cpu(4, values)
        with self.assertRaises(ValueError):
            publisher.validate_runtime(uid=65534, euid=65534, groups=['nogroup'], devices=[],
                sockets=[], sudo=False, capabilities=0, memory='2147483648', pids='128',
                cpu=publisher.effective_cpu(4, ['400000 100000']))

    def test_default_api_transport_rejects_every_release_mutation(self):
        publisher = baseline.helper()
        api = object.__new__(publisher.GithubAPI)
        api.read_only = True
        api.reader, api.writer = 'reader', 'writer'
        api.latest_expected_sha = None
        api.opener = mock.Mock()
        for method in ['POST', 'PATCH', 'DELETE', 'PUT']:
            with self.subTest(method=method), self.assertRaises(ValueError):
                api.request(method, '/repos/cryptolabsza/dc-exporter-releases/releases')
        api.opener.open.assert_not_called()

    def test_launcher_contains_bounded_known_user_and_no_guest_socket_mount(self):
        launcher = (pathlib.Path(__file__).resolve().parents[1] / 'scripts/ci/pool-publish.sh').read_text()
        for flag in ['--user 65534:65534', '--cap-drop ALL', '--read-only', '--pids-limit 128',
                     '--memory 2g', '--memory-swap 2g', '--cpus 2', 'no-new-privileges',
                     'readonly', 'uid=65534,gid=65534', '--network none']:
            self.assertIn(flag, launcher)
        for forbidden in ['--privileged', 'docker.sock', '--device', '--group-add', '--env-file', 'set -x']:
            self.assertNotIn(forbidden, launcher)


class ActualProducerIntegrationTests(unittest.TestCase):
    def test_actual_producer_manifest_is_accepted_by_trusted_consumer(self):
        # Standalone release tests exercise the strict frozen-format fixture.
        # The root verification run MUST supply PUBLIC_PRODUCER_PATH and records
        # that producer's SHA; this branch invokes its actual manifest API.
        producer_path = os.environ.get('PUBLIC_PRODUCER_PATH')
        if producer_path is None:
            checked, _ = baseline.helper().validate_archive(archive(bundle()), SOURCE)
            self.assertEqual(checked, bundle())
            return
        spec = importlib.util.spec_from_file_location('actual_public_producer', producer_path)
        producer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(producer)
        files = bundle()
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            dist = root / 'dist'
            dist.mkdir()
            for name, data in files.items():
                if name != 'manifest.json':
                    (dist / name).write_bytes(data)
            cargo = root / 'Cargo.toml'
            cargo.write_text('[package]\nname="dc-exporter-rs"\nversion="0.2.7"\n')
            env = dict(GITHUB_REPOSITORY=SOURCE['repository'], GITHUB_REPOSITORY_ID=str(SOURCE['repository_id']),
                       GITHUB_SHA=SHA, GITHUB_REF=SOURCE['ref'], GITHUB_RUN_ID='10', GITHUB_RUN_ATTEMPT='2',
                       GITHUB_EVENT_NAME='push', GITHUB_REF_PROTECTED='true')
            manifest = producer.manifest(dist, cargo, env)
            files['manifest.json'] = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode()
            checked, actual = baseline.helper().validate_archive(archive(files), SOURCE)
        self.assertEqual(actual, manifest)
        self.assertEqual(checked, files)
        self.assertEqual(len(actual['files']), 9)
        self.assertEqual(len(checked), 10)


def recorded_historical_snapshots():
    # Names copied from authenticated target inventory release-assets-before.json.
    # These are opaque preservation fixtures, never new-source provenance.
    return [
        {'dc-exporter-rs': b'oldest historical binary'},
        {'BUILD_INFO.txt': b'original dev provenance; never relabel',
         'dc-exporter-rs': b'original dev binary', 'SHA256SUMS': b'original dev checksums'},
        {'dc-exporter-rs': b'original stable binary',
         'dc-exporter-rs_0.2.8_amd64.deb': b'original stable versioned package',
         'dc-exporter-rs_amd64.deb': b'original stable alias package',
         'SHA256SUMS': b'original stable checksums'}]


class ActualHistoricalReleaseTests(unittest.TestCase):
    def test_recorded_oldest_dev_three_and_stable_four_snapshot_sets_are_preservable(self):
        api = object.__new__(baseline.helper().GithubAPI)
        for files in recorded_historical_snapshots():
            before = copy.deepcopy(files)
            with self.subTest(names=sorted(files)):
                api.verify_previous(files)
                self.assertEqual(files, before)
                self.assertNotIn('manifest.json', files)

    def test_unmanifested_previous_rejects_unknown_names_and_unbounded_bytes(self):
        api = object.__new__(baseline.helper().GithubAPI)
        for files in [{'dc-exporter-rs': b'old', 'postinst': b'bad'},
                      recorded_historical_snapshots()[1] | {'extra': b'bad'},
                      {'dc-exporter-rs': b''}]:
            with self.subTest(names=sorted(files)), self.assertRaises(ValueError):
                api.verify_previous(files)

    def test_actual_recorded_formats_recover_without_reader_and_preserve_metadata(self):
        fixture = FormatTransitionRecoveryTests()
        fixture.setUp()
        # Reuse the real transport recovery oracle, now with exact deployed sets.
        for old in recorded_historical_snapshots():
            with self.subTest(old_entries=len(old)):
                fixture.old = old
                fixture.test_reader_unavailable_target_only_recovery_preserves_old_six_and_new_ten()


class ReadOnlyHTTPPreparationTests(unittest.TestCase):
    def test_actual_entrypoint_transport_only_performs_get_requests(self):
        fixture = baseline.PublisherBoundaryTests()
        fixture.setUp()
        publisher = baseline.helper()
        requests = []
        class Response:
            def __init__(self, data): self.data = data
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, maximum): return self.data[:maximum]
        class Server:
            def open(self, request, timeout):
                requests.append((request.get_method(), request.full_url))
                self.assert_get(request)
                path = urllib.parse.urlsplit(request.full_url).path
                if path == '/repos/cryptolabsza/dc-exporter-rs-public':
                    data = dict(id=1416116330, full_name=SOURCE['repository'])
                elif path == '/repos/cryptolabsza/dc-exporter-releases':
                    data = dict(id=1141480624, full_name='cryptolabsza/dc-exporter-releases')
                elif path.endswith('/attempts/2'):
                    data = fixture.run
                elif path.endswith('/artifacts/90'):
                    data = fixture.artifact
                elif path.endswith('/artifacts/90/zip'):
                    return Response(fixture.archive())
                elif path.endswith('/git/ref/heads/dev'):
                    data = {'object': {'sha': SHA}}
                else:
                    raise AssertionError('Unexpected API request')
                return Response(json.dumps(data).encode())
            def assert_get(self, request):
                if request.get_method() != 'GET':
                    raise AssertionError('Preparation attempted a release mutation')
        env = dict(SOURCE_READER_TOKEN='synthetic-reader', GITHUB_TOKEN='synthetic-read-only',
                   SOURCE_WORKFLOW_ID='7', GITHUB_REPOSITORY='cryptolabsza/dc-exporter-releases',
                   GITHUB_DEFAULT_BRANCH='main', GITHUB_REF='refs/heads/main',
                   GITHUB_EVENT_NAME='workflow_dispatch',
                   GITHUB_WORKFLOW_REF='cryptolabsza/dc-exporter-releases/.github/workflows/publish.yml@refs/heads/main')
        args = ['--validate-only', '--run-id', '10', '--run-attempt', '2', '--artifact-id', '90', '--sha', SHA, '--branch', 'dev']
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(publisher, 'preflight'), \
             mock.patch('urllib.request.build_opener', return_value=Server()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(publisher.main(args), 0)
        self.assertEqual(len(requests), 7)
        self.assertTrue(all(method == 'GET' for method, _ in requests))
