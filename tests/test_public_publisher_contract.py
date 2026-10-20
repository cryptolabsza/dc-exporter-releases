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


class ProtectedActivationWorkflowTests(unittest.TestCase):
    """Inspect the parsed, actual Actions entrypoints, including job boundaries."""
    def setUp(self):
        import yaml
        self.root = pathlib.Path(__file__).resolve().parents[1]
        self.caller = yaml.load((self.root / '.github/workflows/publish.yml').read_text(), Loader=yaml.BaseLoader)
        self.recipe = yaml.load((self.root / '.github/workflows/dc-exporter-publish.yml').read_text(), Loader=yaml.BaseLoader)

    def test_dispatch_defaults_to_validation_and_recovery_has_no_required_source_input(self):
        inputs = self.caller['on']['workflow_dispatch']['inputs']
        self.assertIn('mode', inputs, 'actual dispatch has no activation mode')
        self.assertEqual(inputs['mode']['default'], 'validate')
        self.assertEqual(inputs['mode']['type'], 'choice')
        self.assertEqual(inputs['mode']['options'], ['validate', 'publish', 'recover'])
        self.assertEqual(inputs['recover_stage_id']['required'], 'false')
        for key in ['run_id', 'run_attempt', 'artifact_id', 'sha', 'branch']:
            self.assertEqual(inputs[key]['required'], 'false', key)
            self.assertEqual(self.recipe['on']['workflow_call']['inputs'][key]['required'], 'false', key)
        self.assertEqual(self.recipe['on']['workflow_call']['inputs']['mode']['default'], 'validate')

    def selected_jobs(self, workflow, inputs, context=None):
        import ast
        import re
        values = {'github.repository': 'cryptolabsza/dc-exporter-releases',
                  'github.repository_id': '1141480624', 'github.event_name': 'workflow_dispatch',
                  'github.event.repository.default_branch': 'main', 'github.ref': 'refs/heads/main',
                  'github.ref_protected': True,
                  'github.workflow_ref': 'cryptolabsza/dc-exporter-releases/.github/workflows/publish.yml@refs/heads/main'}
        values.update(context or {})
        values.update({'inputs.' + key: value for key, value in inputs.items()})
        def evaluate(node):
            if isinstance(node, ast.Constant): return node.value
            if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
                return all(evaluate(value) for value in node.values)
            if isinstance(node, ast.Compare) and len(node.ops) == 1:
                left, right = evaluate(node.left), evaluate(node.comparators[0])
                if isinstance(node.ops[0], ast.Eq): return left == right
                if isinstance(node.ops[0], ast.NotEq): return left != right
            raise AssertionError('Unsupported actual workflow predicate')
        selected = []
        for name, job in workflow['jobs'].items():
            expression = re.sub(r'\b(?:github|inputs)\.[A-Za-z_.]+',
                                lambda match: repr(values[match[0]]), job['if']).replace('&&', ' and ')
            if evaluate(ast.parse('(' + expression + ')', mode='eval').body): selected.append(name)
        return selected

    def test_only_explicit_publish_and_recover_jobs_have_minimal_writer_permissions(self):
        for workflow in [self.caller, self.recipe]:
            self.assertEqual(workflow['permissions'], {'contents': 'read'})
            self.assertEqual(set(workflow['jobs']), {'validate', 'publish', 'recover'})
            for mode, job in workflow['jobs'].items():
                self.assertEqual(job['permissions'], {'contents': 'read' if mode == 'validate' else 'write'})
                self.assertIn("inputs.mode == '" + mode + "'", job['if'])
                if mode == 'publish':
                    self.assertIn("inputs.branch == 'dev'", job['if'])
                if workflow is self.caller:
                    self.assertEqual(job['with']['mode'], mode)
                    self.assertRegex(job['uses'], r'^cryptolabsza/dc-exporter-releases/\.github/workflows/dc-exporter-publish\.yml@[0-9a-f]{40}$')
                    self.assertNotIn('inherit', json.dumps(job.get('secrets', {})))
            source = dict(mode='validate', run_id='10', run_attempt='2', artifact_id='90',
                          sha=SHA, branch='dev', recover_stage_id='')
            recovery = dict(mode='recover', run_id='', run_attempt='', artifact_id='',
                            sha='', branch='', recover_stage_id='25')
            for inputs, selected in [(source, ['validate']), (source | {'mode': 'publish'}, ['publish']),
                                     (recovery, ['recover']), (source | {'mode': 'other'}, []),
                                     (source | {'mode': 'publish', 'branch': 'main'}, []),
                                     (source | {'recover_stage_id': '25'}, [])]:
                self.assertEqual(self.selected_jobs(workflow, inputs), selected)
            for key in ['run_id', 'run_attempt', 'artifact_id', 'sha', 'branch']:
                self.assertEqual(self.selected_jobs(workflow, recovery | {key: source[key]}), [])
                self.assertEqual(self.selected_jobs(workflow, source | {key: ''}), [])
            for key, value in [('github.repository', 'wrong/repository'), ('github.repository_id', '9'),
                               ('github.event_name', 'push'), ('github.event.repository.default_branch', 'dev'),
                               ('github.ref', 'refs/heads/dev'), ('github.ref_protected', False),
                               ('github.workflow_ref', 'wrong/workflow')]:
                for inputs in [source, source | {'mode': 'publish'}, recovery]:
                    self.assertEqual(self.selected_jobs(workflow, inputs, {key: value}), [])
            self.assertNotIn('secrets', workflow['jobs']['recover'])
            self.assertEqual(set(workflow['jobs']['recover'].get('with', {})) - {'mode', 'recover_stage_id'}, set())

    def test_every_job_requires_exact_repository_default_main_protection_and_manual_workflow(self):
        required = ["github.repository == 'cryptolabsza/dc-exporter-releases'",
                    "github.repository_id == '1141480624'", "github.event_name == 'workflow_dispatch'",
                    "github.ref == 'refs/heads/main'", 'github.ref_protected',
                    "github.event.repository.default_branch == 'main'",
                    "github.workflow_ref == 'cryptolabsza/dc-exporter-releases/.github/workflows/publish.yml@refs/heads/main'"]
        for workflow in [self.caller, self.recipe]:
            self.assertEqual(set(workflow['jobs']), {'validate', 'publish', 'recover'})
            for mode in ['validate', 'publish', 'recover']:
                for clause in required:
                    with self.subTest(mode=mode, clause=clause):
                        self.assertIn(clause, workflow['jobs'][mode]['if'])

    def test_source_reader_is_fixed_source_only_and_never_minted_in_recovery(self):
        self.assertIn('publish', self.recipe['jobs'])
        self.assertIn('recover', self.recipe['jobs'])
        for mode in ['validate', 'publish']:
            steps = self.recipe['jobs'][mode]['steps']
            readers = [step for step in steps if 'create-github-app-token@' in step.get('uses', '')]
            self.assertEqual(len(readers), 1)
            self.assertEqual(readers[0]['with']['owner'], 'cryptolabsza')
            self.assertEqual(readers[0]['with']['repositories'], 'dc-exporter-rs-public')
            self.assertEqual(readers[0]['with']['permission-actions'], 'read')
            self.assertEqual(readers[0]['with']['permission-contents'], 'read')
            preflight = next(i for i, step in enumerate(steps) if 'pool-publish.sh preflight' in step.get('run', ''))
            self.assertLess(preflight, steps.index(readers[0]))
            for step in steps:
                if 'actions/checkout@' in step.get('uses', ''):
                    self.assertEqual(step['with']['persist-credentials'], 'false')
        encoded = json.dumps(self.recipe['jobs']['recover']['steps'])
        for forbidden in ['create-github-app-token', 'SOURCE_READER', 'SOURCE_WORKFLOW_ID', 'inputs.run_id',
                          'inputs.run_attempt', 'inputs.artifact_id', 'inputs.sha', 'inputs.branch']:
            self.assertNotIn(forbidden, encoded)


class ActualLauncherActivationTests(unittest.TestCase):
    """Execute the real launcher against an inert argv/environment capture binary."""
    def launch(self, mode, *, changes=None, omit=(), extra=()):
        import subprocess
        import sys
        root = pathlib.Path(__file__).resolve().parents[1]
        env = dict(PATH=os.environ['PATH'], GITHUB_REPOSITORY='cryptolabsza/dc-exporter-releases',
                   GITHUB_REPOSITORY_ID='1141480624', GITHUB_DEFAULT_BRANCH='main',
                   GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_REF='refs/heads/main', GITHUB_REF_PROTECTED='true',
                   GITHUB_WORKFLOW_REF='cryptolabsza/dc-exporter-releases/.github/workflows/publish.yml@refs/heads/main',
                   GITHUB_SHA='c' * 40, GITHUB_RUN_ID='50', GITHUB_RUN_ATTEMPT='3',
                   INPUT_RUN_ID='10', INPUT_RUN_ATTEMPT='2', INPUT_ARTIFACT_ID='90', INPUT_SHA=SHA,
                   INPUT_BRANCH='dev', SOURCE_WORKFLOW_ID='7', SOURCE_READER_TOKEN='CANARY-READER',
                   GITHUB_TOKEN='CANARY-WRITER', INPUT_RECOVER_STAGE_ID='25', INPUT_MODE='validate')
        env.update(changes or {})
        for key in omit: env.pop(key, None)
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp)
            capture = path / 'capture.json'
            docker = path / 'docker'
            docker.write_text('#!' + sys.executable + '\nimport json,os,sys\n' +
                              'json.dump({"argv":sys.argv[1:]},open(os.environ["CAPTURE"],"w"))\n')
            docker.chmod(0o755)
            env['PATH'] = str(path) + os.pathsep + env['PATH']
            env['CAPTURE'] = str(capture)
            result = subprocess.run(['bash', str(root / 'scripts/ci/pool-publish.sh'), mode, *extra],
                                    env=env, capture_output=True, text=True, timeout=5)
            args = json.loads(capture.read_text())['argv'] if capture.exists() else None
        self.assertNotIn('CANARY', result.stdout + result.stderr + json.dumps(args))
        return result, args

    def forwarded(self, args):
        return [args[index + 1] for index, value in enumerate(args) if value == '--env']

    def test_validation_forwards_publisher_run_identity_and_explicit_read_only_arguments(self):
        result, args = self.launch('validate', omit=['INPUT_RECOVER_STAGE_ID'])
        self.assertEqual(result.returncode, 0, result.stderr)
        env = self.forwarded(args)
        self.assertIn('GITHUB_RUN_ID', env)
        self.assertIn('GITHUB_RUN_ATTEMPT', env)
        self.assertEqual(args[args.index('scripts/ci/publish.py') + 1:],
                         ['--validate-only', '--run-id', '10', '--run-attempt', '2', '--artifact-id', '90', '--sha', SHA, '--branch', 'dev'])

    def test_explicit_dev_publish_uses_fixed_args_and_only_environment_credentials(self):
        result, args = self.launch('publish', omit=['INPUT_RECOVER_STAGE_ID'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(args[args.index('scripts/ci/publish.py') + 1:],
                         ['--publish', '--run-id', '10', '--run-attempt', '2', '--artifact-id', '90', '--sha', SHA, '--branch', 'dev'])
        self.assertIn('SOURCE_READER_TOKEN', self.forwarded(args))
        self.assertIn('GITHUB_TOKEN', self.forwarded(args))
        self.assertIn('GITHUB_RUN_ID', self.forwarded(args))
        self.assertIn('GITHUB_RUN_ATTEMPT', self.forwarded(args))

    def test_target_only_recovery_needs_no_source_configuration_and_forwards_no_reader(self):
        source = ['SOURCE_READER_TOKEN', 'SOURCE_WORKFLOW_ID', 'INPUT_RUN_ID', 'INPUT_RUN_ATTEMPT',
                  'INPUT_ARTIFACT_ID', 'INPUT_SHA', 'INPUT_BRANCH']
        result, args = self.launch('recover', omit=source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(args[args.index('scripts/ci/publish.py') + 1:], ['--recover-stage-id', '25'])
        self.assertIn('GITHUB_TOKEN', self.forwarded(args))
        self.assertNotIn('SOURCE_READER_TOKEN', self.forwarded(args))
        self.assertNotIn('SOURCE_WORKFLOW_ID', self.forwarded(args))

    def test_preflight_is_networkless_and_receives_no_credentials(self):
        result, args = self.launch('preflight', omit=['SOURCE_READER_TOKEN', 'GITHUB_TOKEN', 'INPUT_RECOVER_STAGE_ID'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(args[args.index('--network') + 1], 'none')
        self.assertNotIn('SOURCE_READER_TOKEN', self.forwarded(args))
        self.assertNotIn('GITHUB_TOKEN', self.forwarded(args))

    def test_invalid_context_modes_and_mixed_source_recovery_inputs_never_launch_container(self):
        changes = [{'GITHUB_REPOSITORY_ID': '9'}, {'GITHUB_DEFAULT_BRANCH': 'dev'},
                   {'GITHUB_EVENT_NAME': 'push'}, {'GITHUB_REF': 'refs/heads/dev'},
                   {'GITHUB_REF_PROTECTED': 'false'}, {'GITHUB_WORKFLOW_REF': 'evil/workflow'},
                   {'GITHUB_RUN_ID': '0'}, {'GITHUB_RUN_ATTEMPT': 'bad'}]
        for change in changes:
            with self.subTest(change=change):
                result, args = self.launch('validate', changes=change, omit=['INPUT_RECOVER_STAGE_ID'])
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(args)
        for mode, changes, omit, extra in [('unknown', {}, (), ()), ('publish', {'INPUT_BRANCH': 'main'}, ('INPUT_RECOVER_STAGE_ID',), ()),
                                           ('recover', {}, (), ()), ('validate', {}, (), ()),
                                           ('validate', {}, ('INPUT_RECOVER_STAGE_ID',), ('--publish',))]:
            with self.subTest(mode=mode, changes=changes):
                result, args = self.launch(mode, changes=changes, omit=omit, extra=extra)
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(args)


class ActualPublishCLITransportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = FormatTransitionRecoveryTests()
        self.fixture.setUp()
        self.publisher = self.fixture.publisher
        self.boundary = baseline.PublisherBoundaryTests()
        self.boundary.setUp()
        self.boundary.sha = 'b' * 40
        self.boundary.source = SOURCE | {'sha': 'b' * 40, 'artifact_name': f'dc-exporter-1416116330-10-2-{"b" * 40}'}
        self.boundary.run['head_sha'] = 'b' * 40
        self.boundary.artifact['name'] = self.boundary.source['artifact_name']
        self.boundary.artifact['workflow_run']['head_sha'] = 'b' * 40
        self.env = dict(SOURCE_READER_TOKEN='CANARY-READER', GITHUB_TOKEN='CANARY-WRITER', SOURCE_WORKFLOW_ID='7',
                        GITHUB_REPOSITORY='cryptolabsza/dc-exporter-releases', GITHUB_DEFAULT_BRANCH='main',
                        GITHUB_REF='refs/heads/main', GITHUB_EVENT_NAME='workflow_dispatch',
                        GITHUB_WORKFLOW_REF='cryptolabsza/dc-exporter-releases/.github/workflows/publish.yml@refs/heads/main',
                        GITHUB_SHA='c' * 40, GITHUB_RUN_ID='50', GITHUB_RUN_ATTEMPT='3')
        self.args = ['--publish', '--run-id', '10', '--run-attempt', '2', '--artifact-id', '90',
                     '--sha', 'b' * 40, '--branch', 'dev']

    def run_cli(self, *, stale=False, run_change=None, artifact_change=None, args=None):
        _, server = self.fixture.server()
        if stale: server.tip = 'd' * 40
        original = server.open
        requests = []
        boundary, files = self.boundary, self.fixture.new
        class Response:
            def __init__(self, data): self.data = data
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, maximum): return self.data[:maximum]
        def routed(request, timeout):
            requests.append((request.get_method(), request.full_url))
            path = urllib.parse.urlsplit(request.full_url).path
            if path.endswith('/actions/runs/10/attempts/2'):
                return Response(json.dumps(boundary.run | (run_change or {})).encode())
            if path.endswith('/actions/artifacts/90'):
                return Response(json.dumps(boundary.artifact | (artifact_change or {})).encode())
            if path.endswith('/actions/artifacts/90/zip'):
                return Response(archive(files))
            return original(request, timeout)
        server.open = routed
        output = io.StringIO()
        with mock.patch.dict(os.environ, self.env, clear=True), mock.patch.object(self.publisher, 'preflight'), \
             mock.patch('urllib.request.build_opener', return_value=server), contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = self.publisher.main(self.args if args is None else args)
        self.assertNotIn('CANARY', output.getvalue())
        return result, server, requests

    def test_actual_publish_cli_uploads_ten_immutable_assets_and_stages_latest_with_recovery(self):
        result, server, _ = self.run_cli()
        self.assertEqual(result, 0)
        immutable = next(r for r in server.releases.values() if r['tag_name'] == 'dev-' + 'b' * 40)
        self.assertEqual(server.files[immutable['id']], self.fixture.new)
        self.assertEqual(len(server.files[immutable['id']]), 10)
        self.assertEqual(server.files[server.latest()['id']], self.fixture.new)
        self.assertEqual(server.files[1], self.fixture.old)
        self.assertTrue(immutable['prerelease'])
        self.assertFalse(immutable['draft'])
        stage = json.loads(server.latest()['body'])
        self.assertEqual(stage['stage_tag'], 'dev-stage-50-3-' + 'b' * 40)

    def test_stale_or_wrong_authoritative_receipt_causes_zero_transport_writes(self):
        cases = [dict(stale=True), dict(run_change={'workflow_id': 8}), dict(run_change={'run_attempt': 1}),
                 dict(run_change={'head_repository': {'id': 9}}), dict(artifact_change={'expired': True}),
                 dict(artifact_change={'workflow_run': {'id': 10, 'head_sha': 'e' * 40}})]
        for case in cases:
            with self.subTest(case=case):
                result, server, requests = self.run_cli(**case)
                self.assertEqual(result, 1)
                self.assertEqual(server.operations, [])
                self.assertTrue(all(method == 'GET' for method, _ in requests))
                self.assertEqual(server.files[1], self.fixture.old)

    def test_default_and_explicit_validation_have_get_only_transport(self):
        for args in [self.args[1:], ['--validate-only'] + self.args[1:]]:
            with self.subTest(args=args):
                result, server, requests = self.run_cli(args=args)
                self.assertEqual(result, 0)
                self.assertEqual(server.operations, [])
                self.assertTrue(all(method == 'GET' for method, _ in requests))

    def test_mutually_exclusive_cli_modes_fail_before_any_transport_write(self):
        for args in [self.args + ['--validate-only'], self.args + ['--recover-stage-id', '2'],
                     ['--validate-only', '--recover-stage-id', '2'], ['--recover-stage-id', '2', '--run-id', '10']]:
            with self.subTest(args=args):
                result, server, requests = self.run_cli(args=args)
                self.assertEqual(result, 1)
                self.assertEqual(server.operations, [])
                self.assertEqual(requests, [])


class RecipePrecredentialIntegrationTests(unittest.TestCase):
    """Execute actual recipe preflight with its declared environment, no credentials."""
    def setUp(self):
        import yaml
        self.root = pathlib.Path(__file__).resolve().parents[1]
        self.recipe = yaml.load((self.root / '.github/workflows/dc-exporter-publish.yml').read_text(), Loader=yaml.BaseLoader)
        self.caller = yaml.load((self.root / '.github/workflows/publish.yml').read_text(), Loader=yaml.BaseLoader)

    def preflight(self, mode, *, changes=None, workflow_id='7', operation_env_control=False):
        import re
        import subprocess
        import sys
        job = self.recipe['jobs'][mode]
        step_index = next(i for i, step in enumerate(job['steps']) if 'pool-publish.sh preflight' in step.get('run', ''))
        step = job['steps'][step_index]
        inputs = dict(mode=mode, run_id='10', run_attempt='2', artifact_id='90', sha=SHA,
                      branch='dev', recover_stage_id='')
        if mode == 'recover':
            inputs.update(run_id='', run_attempt='', artifact_id='', sha='', branch='', recover_stage_id='25')
        inputs.update(changes or {})
        contexts = {'github.event.repository.default_branch': 'main',
                    'vars.DC_EXPORTER_SOURCE_WORKFLOW_ID': workflow_id,
                    **{'inputs.' + key: value for key, value in inputs.items()}}
        # These are GitHub's standard shell variables only. Custom environment
        # comes exclusively from the parsed workflow step(s) below.
        env = dict(PATH=os.environ['PATH'], GITHUB_REPOSITORY='cryptolabsza/dc-exporter-releases',
                   GITHUB_REPOSITORY_ID='1141480624', GITHUB_EVENT_NAME='workflow_dispatch',
                   GITHUB_REF='refs/heads/main', GITHUB_REF_PROTECTED='true',
                   GITHUB_WORKFLOW_REF='cryptolabsza/dc-exporter-releases/.github/workflows/publish.yml@refs/heads/main',
                   GITHUB_SHA='c' * 40, GITHUB_RUN_ID='50', GITHUB_RUN_ATTEMPT='3')
        declarations = dict(step.get('env', {}))
        if operation_env_control:
            # Isolate ADV-002 from ADV-001 using actual operation-step receipt
            # declarations; credential declarations are deliberately excluded.
            operation = next(value for value in job['steps'] if value.get('run') == 'bash scripts/ci/pool-publish.sh ' + mode)
            declarations = {key: value for key, value in operation['env'].items()
                            if key not in {'SOURCE_READER_TOKEN', 'GITHUB_TOKEN'}} | declarations
            # The caller already declares the selected mode as a fixed value.
            declarations.setdefault('INPUT_MODE', self.caller['jobs'][mode]['with']['mode'])
        for name, expression in declarations.items():
            self.assertNotIn(name, {'SOURCE_READER_TOKEN', 'GITHUB_TOKEN'}, 'preflight must have no credential environment')
            match = re.fullmatch(r'\$\{\{\s*([^}]+?)\s*\}\}', expression)
            env[name] = contexts[match[1]] if match else expression
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp)
            capture = path / 'capture.json'
            docker = path / 'docker'
            docker.write_text('#!' + sys.executable + '\nimport json,os,sys\n' +
                              'json.dump({"argv":sys.argv[1:],"env_names":sorted(os.environ)},open(os.environ["CAPTURE"],"w"))\n')
            docker.chmod(0o755)
            env['PATH'] = str(path) + os.pathsep + env['PATH']
            env['CAPTURE'] = str(capture)
            result = subprocess.run(['bash', '-c', step['run']], cwd=self.root, env=env,
                                    capture_output=True, text=True, timeout=5)
            captured = json.loads(capture.read_text()) if capture.exists() else None
        # A normal Actions run stops at failed preflight; it cannot reach the
        # following actual App mint step. No token action is invoked in tests.
        mint_after = any('create-github-app-token@' in value.get('uses', '') for value in job['steps'][step_index + 1:])
        reached_mint = result.returncode == 0 and mint_after
        return result, captured, reached_mint

    def test_actual_recipe_preflight_all_three_modes_reach_networkless_container_without_credentials(self):
        for mode in ['validate', 'publish', 'recover']:
            with self.subTest(mode=mode):
                result, captured, _ = self.preflight(mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIsNotNone(captured)
                args = captured['argv']
                self.assertEqual(args[args.index('--network') + 1], 'none')
                self.assertEqual(args[args.index('scripts/ci/publish.py') + 1:], ['--preflight'])
                self.assertNotIn('SOURCE_READER_TOKEN', captured['env_names'])
                self.assertNotIn('GITHUB_TOKEN', captured['env_names'])

    def test_malformed_source_receipts_and_config_fail_preflight_before_container_or_app_mint(self):
        cases = [({'mode': 'unknown'}, '7'), ({'run_id': 'garbage'}, '7'), ({'run_attempt': '0'}, '7'),
                 ({'artifact_id': '-1'}, '7'), ({'sha': 'bad-sha'}, '7'),
                 ({'branch': 'untrusted'}, '7'), ({'recover_stage_id': '25'}, '7'),
                 ({}, ''), ({}, 'not-a-workflow')]
        for mode in ['validate', 'publish']:
            for changes, workflow_id in cases:
                with self.subTest(mode=mode, changes=changes, workflow_id=workflow_id):
                    result, captured, reached_mint = self.preflight(mode, changes=changes, workflow_id=workflow_id,
                                                                   operation_env_control=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIsNone(captured)
                    self.assertFalse(reached_mint)

    def test_recovery_preflight_rejects_bad_stage_and_recipe_blocks_source_conflicts_without_source_configuration(self):
        for changes in [{'recover_stage_id': 'garbage'}, {'recover_stage_id': '0'}]:
            with self.subTest(changes=changes):
                result, captured, reached_mint = self.preflight('recover', changes=changes, workflow_id='', operation_env_control=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(captured)
                self.assertFalse(reached_mint)
        recovery = dict(mode='recover', run_id='', run_attempt='', artifact_id='', sha='', branch='', recover_stage_id='25')
        selector = ProtectedActivationWorkflowTests()
        for key, value in [('run_id', '10'), ('run_attempt', '2'), ('artifact_id', '90'), ('sha', SHA), ('branch', 'dev')]:
            for workflow in [self.caller, self.recipe]:
                with self.subTest(field=key):
                    self.assertEqual(selector.selected_jobs(workflow, recovery | {key: value}), [])
