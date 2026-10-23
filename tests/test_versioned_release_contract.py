# TRACEWEAVER: file-role=versioned-release-contract; req=REQ-VERSIONED-001; trace=TRACE-VERSIONED-001; ver=VER-VERSIONED-001
"""Exact v0.3.0 publication, using opaque bytes and an in-memory HTTP transport."""
import ast
import contextlib
import copy
import hashlib
import io
import json
import os
import pathlib
import re
import unittest
import urllib.error
import urllib.parse
from unittest import mock

import test_ci_publisher as baseline
import test_public_publisher_contract as public

POLICY = 'v0.3.0-limited-qualification'
SHA = 'a' * 40
PUBLISHER_SHA = 'c' * 40
TAG = 'v0.3.0'


def versioned_bundle():
    source = public.SOURCE | {'ref': 'refs/heads/main'}
    files = public.bundle(source=source)
    files.pop('manifest.json')
    files.pop('SHA256SUMS')
    files['dc-exporter-rs_0.3.0_amd64.deb'] = files.pop('dc-exporter-rs_0.2.7_amd64.deb')
    files['VERSION.txt'] = b'dc-exporter 0.3.0\n'
    files['SHA256SUMS'] = ''.join(hashlib.sha256(data).hexdigest() + '  ' + name + '\n'
                                    for name, data in sorted(files.items())).encode()
    manifest = dict(schema=1, source=source, cargo_version='0.3.0', binary_version='0.3.0',
                    files={name: dict(size=len(data), sha256=hashlib.sha256(data).hexdigest())
                           for name, data in files.items()})
    files['manifest.json'] = json.dumps(manifest, sort_keys=True).encode()
    return files


class Response:
    def __init__(self, data): self.data = data
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, maximum): return self.data[:maximum]


class VersionedServer:
    """Behaves like GitHub for these exact routes; unexpected HTTP is a failure."""
    def __init__(self, files):
        self.files = files
        self.requests = []
        self.mutations = []
        self.main = self.tag_sha = SHA
        self.ancestor = True
        self.target_tag = None
        self.fault = None
        self.advance = None
        self.advance_tag = False
        self.releases = {
            1: dict(id=1, tag_name='v0.2.8', name='old stable', body='old provenance',
                    draft=False, prerelease=False, target_commitish='d' * 40),
            2: dict(id=2, tag_name='dev-latest', name='old dev', body='old dev provenance',
                    draft=False, prerelease=True, target_commitish='e' * 40)}
        self.assets = {1: {'dc-exporter-rs': b'old stable bytes'}, 2: {'dc-exporter-rs': b'old dev bytes'}}
        self.old = copy.deepcopy((self.releases, self.assets))
        self.next_id = 3

    def error(self, request, code):
        error = urllib.error.HTTPError(request.full_url, code, 'CANARY HTTP body', {}, io.BytesIO(b'CANARY'))
        error.close()
        raise error

    def current(self):
        return next((release for release in self.releases.values() if release['tag_name'] == TAG), None)

    def open(self, request, timeout):
        method = request.get_method()
        path = urllib.parse.urlsplit(request.full_url).path
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)
        self.requests.append((method, path))
        source_root = '/repos/cryptolabsza/dc-exporter-rs-public'
        target_root = '/repos/cryptolabsza/dc-exporter-releases'
        data = json.loads(request.data) if request.data and request.headers.get('Content-type') != 'application/octet-stream' else request.data
        operation = ('create' if method == 'POST' and path == target_root + '/releases' else
                     'upload' if method == 'POST' else 'publish' if method == 'PATCH' else None)
        if operation:
            self.mutations.append((operation, path, copy.deepcopy(data)))
            if self.fault == operation + '-before':
                self.fault = None
                self.error(request, 503)
        if method == 'GET':
            if path == source_root:
                result = dict(id=1416116330, full_name='cryptolabsza/dc-exporter-rs-public')
            elif path == target_root:
                result = dict(id=1141480624, full_name='cryptolabsza/dc-exporter-releases')
            elif path.endswith('/actions/runs/10/attempts/2'):
                result = dict(id=10, run_attempt=2, workflow_id=7, path='.github/workflows/build.yml',
                              repository=dict(id=1416116330, full_name='cryptolabsza/dc-exporter-rs-public'),
                              head_repository=dict(id=1416116330, full_name='cryptolabsza/dc-exporter-rs-public'),
                              head_sha=SHA, head_branch='main', event='workflow_dispatch', status='completed', conclusion='success')
            elif path.endswith('/actions/artifacts/90/zip'):
                return Response(public.archive(self.files))
            elif path.endswith('/actions/artifacts/90'):
                result = dict(id=90, name=public.SOURCE['artifact_name'], expired=False,
                              workflow_run=dict(id=10, head_sha=SHA))
            elif path == source_root + '/git/ref/heads/main': result = {'object': {'sha': self.main}}
            elif path == source_root + '/git/ref/tags/' + TAG:
                result = {'object': {'type': 'commit', 'sha': self.tag_sha}}
            elif path.startswith(source_root + '/compare/'):
                result = dict(status='identical' if self.ancestor else 'behind', merge_base_commit={'sha': SHA if self.ancestor else 'b' * 40})
            elif path == target_root + '/git/ref/tags/' + TAG:
                if self.target_tag is None: self.error(request, 404)
                result = {'object': {'type': 'commit', 'sha': self.target_tag}}
            elif path == target_root + '/releases': result = list(self.releases.values())
            elif path.startswith(target_root + '/releases/tags/'):
                tag = path.rsplit('/', 1)[1]
                result = next((release for release in self.releases.values() if release['tag_name'] == tag and not release['draft']), None)
                if result is None: self.error(request, 404)
            elif re.fullmatch(target_root + r'/releases/\d+/assets', path):
                rid = int(path.split('/')[-2])
                result = [dict(id=rid * 100 + index, name=name, size=len(payload))
                          for index, (name, payload) in enumerate(sorted(self.assets[rid].items()), 1)]
            elif re.fullmatch(target_root + r'/releases/assets/\d+', path):
                aid = int(path.rsplit('/', 1)[1])
                rid, index = divmod(aid, 100)
                return Response(sorted(self.assets[rid].items())[index - 1][1])
            elif re.fullmatch(target_root + r'/releases/\d+', path):
                result = self.releases[int(path.rsplit('/', 1)[1])]
            else: raise AssertionError('Unexpected GET ' + path)
        elif operation == 'create':
            rid = self.next_id
            self.next_id += 1
            result = dict(id=rid, **data)
            self.releases[rid] = result
            self.assets[rid] = {}
        elif operation == 'upload':
            rid = int(path.split('/')[-2])
            name = query['name'][0]
            if name in self.assets[rid]: self.error(request, 422)
            self.assets[rid][name] = data
            result = dict(id=rid * 100 + len(self.assets[rid]), name=name, size=len(data))
        elif operation == 'publish':
            rid = int(path.rsplit('/', 1)[1])
            self.releases[rid].update(data)
            self.target_tag = PUBLISHER_SHA
            result = self.releases[rid]
        else: raise AssertionError('Unexpected mutation ' + method + ' ' + path)
        if operation:
            if self.advance == operation:
                self.advance = None
                if self.advance_tag: self.tag_sha = 'b' * 40
                else: self.main = 'b' * 40
            if self.fault == operation + '-after':
                self.fault = None
                self.error(request, 503)
        return Response(json.dumps(result).encode())


class VersionedPublicationTests(unittest.TestCase):
    def setUp(self):
        self.publisher = baseline.helper()
        self.files = versioned_bundle()
        self.server = VersionedServer(self.files)
        self.env = dict(SOURCE_READER_TOKEN='CANARY-READER', GITHUB_TOKEN='CANARY-WRITER', SOURCE_WORKFLOW_ID='7',
                        GITHUB_REPOSITORY='cryptolabsza/dc-exporter-releases', GITHUB_REPOSITORY_ID='1141480624',
                        GITHUB_DEFAULT_BRANCH='main', GITHUB_REF='refs/heads/main', GITHUB_REF_PROTECTED='true',
                        GITHUB_EVENT_NAME='workflow_dispatch',
                        GITHUB_WORKFLOW_REF='cryptolabsza/dc-exporter-releases/.github/workflows/publish.yml@refs/heads/main',
                        GITHUB_SHA=PUBLISHER_SHA, GITHUB_RUN_ID='50', GITHUB_RUN_ATTEMPT='3')
        self.args = ['--run-id', '10', '--run-attempt', '2', '--artifact-id', '90', '--sha', SHA,
                     '--branch', 'main', '--tag', TAG, '--release-policy', POLICY]

    def invoke(self, mode='--publish', args=None):
        output = io.StringIO()
        with mock.patch.dict(os.environ, self.env, clear=True), mock.patch.object(self.publisher, 'preflight'), \
             mock.patch('urllib.request.build_opener', return_value=self.server), \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = self.publisher.main([mode] + (self.args if args is None else args))
        self.assertNotIn('CANARY', output.getvalue())
        self.assertNotIn('Traceback', output.getvalue())
        for rid in [1, 2]:
            self.assertEqual(self.server.releases[rid], self.server.old[0][rid])
            self.assertEqual(self.server.assets[rid], self.server.old[1][rid])
        return result

    def seed(self, *, published=False, partial=False):
        self.assertEqual(self.invoke(), 0)
        release = self.server.current()
        release['draft'] = not published
        if partial: self.server.assets[release['id']].pop('HELP.txt')
        if not published: self.server.target_tag = None
        self.server.mutations.clear()
        return release

    def test_exact_main_policy_publishes_complete_draft_then_one_final_patch(self):
        self.assertEqual(self.invoke(), 0)
        release = self.server.current()
        self.assertFalse(self.publisher.HARDWARE_ACCEPTED)
        self.assertEqual(self.server.assets[release['id']], self.files)
        self.assertFalse(release['draft'])
        self.assertFalse(release['prerelease'])
        self.assertEqual(release['target_commitish'], PUBLISHER_SHA)
        self.assertEqual([operation for operation, _, _ in self.server.mutations], ['create'] + ['upload'] * 10 + ['publish'])
        created = self.server.mutations[0][2]
        self.assertTrue(created['draft'])
        self.assertFalse(created['prerelease'])
        self.assertEqual(self.server.mutations[-1][2]['make_latest'], 'true')
        prefix, provenance = release['body'].split('```json\n', 1)
        self.assertIn('GPU health', prefix)
        self.assertIn('error codes', prefix)
        self.assertIn('TUI', prefix)
        self.assertIn('telemetry', prefix)
        self.assertIn('experimental', prefix)
        self.assertIn('pending', prefix)
        self.assertIn('https://github.com/cryptolabsza/dc-exporter-rs-public/tree/v0.3.0', prefix)
        recipe = json.loads(provenance.removesuffix('\n```'))
        self.assertEqual(recipe['policy']['id'], POLICY)
        self.assertIs(recipe['policy']['hardware_accepted'], False)
        self.assertEqual(recipe['source'], json.loads(self.files['manifest.json'])['source'])
        self.assertEqual(recipe['source_tag'], TAG)
        self.assertEqual(recipe['artifact_id'], 90)
        self.assertEqual(recipe['publisher_sha'], PUBLISHER_SHA)
        self.assertEqual(recipe['files'], self.publisher.GithubAPI.file_receipt(self.files))
        disclosure = recipe['disclosure'].lower()
        for text in ['experimental', 'opt-in', 'burn', 'nccl', 'pending', 'vm']:
            self.assertIn(text, disclosure)

    def test_get_only_validation_checks_tag_ancestry_and_target_collisions(self):
        self.assertEqual(self.invoke('--validate-only'), 0)
        self.assertEqual(self.server.mutations, [])
        paths = [path for _, path in self.server.requests]
        self.assertTrue(any('/git/ref/tags/v0.3.0' in path for path in paths))
        self.assertTrue(any('/compare/' in path for path in paths))
        self.assertTrue(any(path.endswith('/releases') for path in paths))
        self.assertTrue(all(method == 'GET' for method, _ in self.server.requests))

    def test_invalid_policy_tag_branch_and_mixed_recovery_fail_without_writes(self):
        for flag, value in [('--release-policy', ''), ('--release-policy', 'waive-hardware'),
                            ('--tag', 'v0.2.8'), ('--tag', 'v0.3.1'), ('--tag', ''), ('--branch', 'dev')]:
            args = list(self.args)
            args[args.index(flag) + 1] = value
            with self.subTest(flag=flag, value=value):
                self.assertEqual(self.invoke(args=args), 1)
                self.assertEqual(self.server.mutations, [])
        self.assertEqual(self.invoke('--recover-stage-id', ['3', '--release-policy', POLICY]), 1)

    def test_main_tag_or_ancestry_mismatch_denies_validate_and_publish(self):
        for field, value in [('main', 'b' * 40), ('tag_sha', 'b' * 40), ('ancestor', False), ('target_tag', 'f' * 40)]:
            for mode in ['--validate-only', '--publish']:
                self.server = VersionedServer(self.files)
                setattr(self.server, field, value)
                with self.subTest(field=field, mode=mode):
                    self.assertEqual(self.invoke(mode), 1)
                    self.assertEqual(self.server.mutations, [])

    def test_versioned_helper_requires_exact_repository_id_default_main_and_protection(self):
        for name, value in [('GITHUB_REPOSITORY_ID', '9'), ('GITHUB_DEFAULT_BRANCH', 'dev'),
                            ('GITHUB_REF_PROTECTED', 'false')]:
            previous = self.env[name]
            self.env[name] = value
            with self.subTest(name=name):
                self.assertEqual(self.invoke(), 1)
                self.assertEqual(self.server.mutations, [])
            self.env[name] = previous

    def test_matching_draft_subset_resumes_missing_only(self):
        release = self.seed(partial=True)
        self.assertEqual(self.invoke(), 0)
        self.assertEqual(self.server.assets[release['id']], self.files)
        self.assertEqual([operation for operation, _, _ in self.server.mutations], ['upload', 'publish'])

    def test_complete_published_exact_retry_is_noop(self):
        self.seed(published=True)
        self.assertEqual(self.invoke(), 0)
        self.assertEqual(self.server.mutations, [])

    def test_partial_published_release_is_hold_even_with_matching_bytes(self):
        self.seed(published=True, partial=True)
        self.assertEqual(self.invoke(), 1)
        self.assertEqual(self.server.mutations, [])

    def test_conflicting_body_tag_target_metadata_or_asset_denies_both_modes(self):
        for field in ['body', 'target_commitish', 'name', 'prerelease', 'asset', 'extra']:
            for mode in ['--validate-only', '--publish']:
                self.server = VersionedServer(self.files)
                release = self.seed(partial=True)
                if field == 'asset': self.server.assets[release['id']]['dc-exporter-rs'] = b'foreign'
                elif field == 'extra': self.server.assets[release['id']]['foreign'] = b'foreign'
                else: release[field] = True if field == 'prerelease' else 'foreign metadata'
                with self.subTest(field=field, mode=mode):
                    self.assertEqual(self.invoke(mode), 1)
                    self.assertEqual(self.server.mutations, [])

    def test_failed_draft_upload_keeps_private_subset_then_identical_retry_finishes(self):
        self.server.fault = 'upload-after'
        self.assertEqual(self.invoke(), 1)
        self.assertIsNotNone(self.server.current())
        self.assertTrue(self.server.current()['draft'])
        self.assertLess(len(self.server.assets[self.server.current()['id']]), 10)
        self.assertEqual(self.invoke(), 0)
        self.assertFalse(self.server.current()['draft'])

    def test_create_or_final_patch_response_loss_reconciles_exact_retry(self):
        for fault in ['create-before', 'create-after', 'publish-before', 'publish-after']:
            self.server = VersionedServer(self.files)
            self.server.fault = fault
            self.invoke()
            with self.subTest(fault=fault):
                self.assertEqual(self.invoke(), 0)
                self.assertEqual(sum(release['tag_name'] == TAG for release in self.server.releases.values()), 1)
                self.assertFalse(self.server.current()['draft'])
                self.assertEqual(self.server.assets[self.server.current()['id']], self.files)

    def test_source_drift_after_creation_or_upload_stops_next_mutation(self):
        for operation, count in [('create', 1), ('upload', 2)]:
            self.server = VersionedServer(self.files)
            self.server.advance = operation
            with self.subTest(operation=operation):
                self.assertEqual(self.invoke(), 1)
                self.assertEqual(len(self.server.mutations), count)
                self.assertTrue(self.server.current()['draft'])

    def test_source_drift_after_final_patch_prevents_success_claim(self):
        self.server.advance = 'publish'
        self.assertEqual(self.invoke(), 1)
        self.assertIsNotNone(self.server.current())
        self.assertFalse(self.server.current()['draft'])

    def test_source_tag_drift_after_upload_stops_before_next_mutation(self):
        self.server.advance, self.server.advance_tag = 'upload', True
        self.assertEqual(self.invoke(), 1)
        self.assertEqual(len(self.server.mutations), 2)
        self.assertTrue(self.server.current()['draft'])

    def test_published_release_requires_actual_exact_target_tag(self):
        self.seed(published=True)
        self.server.target_tag = None
        self.assertEqual(self.invoke(), 1)
        self.assertEqual(self.server.mutations, [])

    def test_duplicate_matching_release_records_hold_without_mutation(self):
        release = self.seed(partial=True)
        self.server.releases[4] = release | {'id': 4}
        self.server.assets[4] = {}
        self.assertEqual(self.invoke(), 1)
        self.assertEqual(self.server.mutations, [])


class VersionedWorkflowTests(unittest.TestCase):
    def setUp(self):
        import yaml
        self.root = pathlib.Path(__file__).resolve().parents[1]
        self.caller = yaml.load((self.root / '.github/workflows/publish.yml').read_text(), Loader=yaml.BaseLoader)
        self.read = public.called_recipe(self.root, self.caller, 'validate')
        self.write = public.called_recipe(self.root, self.caller, 'publish')

    def selected(self, workflow, inputs):
        values = {'github.repository': 'cryptolabsza/dc-exporter-releases', 'github.repository_id': '1141480624',
                  'github.event_name': 'workflow_dispatch', 'github.event.repository.default_branch': 'main',
                  'github.ref': 'refs/heads/main', 'github.ref_protected': True,
                  'github.workflow_ref': 'cryptolabsza/dc-exporter-releases/.github/workflows/publish.yml@refs/heads/main'}
        values.update({'inputs.' + key: value for key, value in inputs.items()})
        def evaluate(node):
            if isinstance(node, ast.Constant): return node.value
            if isinstance(node, ast.BoolOp):
                return (all if isinstance(node.op, ast.And) else any)(evaluate(value) for value in node.values)
            if isinstance(node, ast.Compare) and len(node.ops) == 1:
                left, right = evaluate(node.left), evaluate(node.comparators[0])
                if isinstance(node.ops[0], ast.Eq): return left == right
                if isinstance(node.ops[0], ast.NotEq): return left != right
            raise AssertionError('Unexpected workflow predicate')
        return [name for name, job in workflow['jobs'].items()
                if evaluate(ast.parse('(' + re.sub(r'\b(?:github|inputs)\.[A-Za-z_.]+',
                   lambda match: repr(values[match[0]]), job['if']).replace('&&', ' and ').replace('||', ' or ') + ')', mode='eval').body)]

    def inputs(self, mode='publish'):
        return dict(mode=mode, run_id='10', run_attempt='2', artifact_id='90', sha=SHA,
                    branch='main', tag=TAG, release_policy=POLICY, recover_stage_id='')

    def test_actual_caller_and_reusable_inputs_and_both_step_mappings(self):
        for key in ['tag', 'release_policy']:
            self.assertIn(key, self.caller['on']['workflow_dispatch']['inputs'])
            for mode, recipe in [('validate', self.read), ('publish', self.write)]:
                self.assertIn(key, recipe['on']['workflow_call']['inputs'])
                self.assertEqual(self.caller['jobs'][mode]['with'][key], '${{ inputs.' + key + ' }}')
                steps = recipe['jobs'][mode]['steps']
                for suffix in ['preflight', mode]:
                    step = next(step for step in steps if step.get('run') == 'bash scripts/ci/pool-publish.sh ' + suffix)
                    self.assertEqual(step['env']['INPUT_' + key.upper()], '${{ inputs.' + key + ' }}')

    def test_exact_tuple_selects_only_correct_job_invalid_tuples_select_none(self):
        for mode, recipe in [('validate', self.read), ('publish', self.write)]:
            for workflow in [self.caller, recipe]:
                self.assertEqual(self.selected(workflow, self.inputs(mode)), [mode])
                for change in [{'tag': 'v0.2.8'}, {'tag': ''}, {'release_policy': ''},
                               {'release_policy': 'hardware-waiver'}, {'branch': 'dev'}, {'recover_stage_id': '25'}]:
                    with self.subTest(mode=mode, change=change):
                        self.assertEqual(self.selected(workflow, self.inputs(mode) | change), [])
                dev = self.inputs(mode) | {'branch': 'dev', 'tag': '', 'release_policy': ''}
                self.assertEqual(self.selected(workflow, dev), [mode])
        recover = self.inputs('recover') | dict(run_id='', run_attempt='', artifact_id='', sha='', branch='', recover_stage_id='25')
        for workflow in [self.caller, self.write]:
            self.assertEqual(self.selected(workflow, recover), [])
            self.assertEqual(self.selected(workflow, recover | {'tag': '', 'release_policy': ''}), ['recover'])

    def test_real_launcher_forwards_exact_tag_policy_and_preflight_has_no_credentials(self):
        launcher = public.ActualLauncherActivationTests()
        changes = dict(INPUT_BRANCH='main', INPUT_TAG=TAG, INPUT_RELEASE_POLICY=POLICY)
        for mode in ['validate', 'publish']:
            result, args = launcher.launch(mode, changes=changes, omit=['INPUT_RECOVER_STAGE_ID'])
            self.assertEqual(result.returncode, 0, result.stderr)
            forwarded = args[args.index('scripts/ci/publish.py') + 1:]
            self.assertEqual(forwarded[-4:], ['--tag', TAG, '--release-policy', POLICY])
        result, args = launcher.launch('preflight', changes=changes | {'INPUT_MODE': 'publish'},
                                       omit=['INPUT_RECOVER_STAGE_ID', 'SOURCE_READER_TOKEN', 'GITHUB_TOKEN'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(args[args.index('--network') + 1], 'none')
        self.assertNotIn('GITHUB_TOKEN', launcher.forwarded(args))
        self.assertNotIn('SOURCE_READER_TOKEN', launcher.forwarded(args))

    def test_real_launcher_rejects_invalid_tuple_before_inert_container(self):
        launcher = public.ActualLauncherActivationTests()
        valid = dict(INPUT_BRANCH='main', INPUT_TAG=TAG, INPUT_RELEASE_POLICY=POLICY)
        for mode in ['validate', 'publish', 'preflight']:
            for change in [{'INPUT_TAG': ''}, {'INPUT_TAG': 'v0.3.1'}, {'INPUT_RELEASE_POLICY': ''},
                           {'INPUT_RELEASE_POLICY': 'waiver'}, {'INPUT_BRANCH': 'dev'},
                           {'INPUT_TAG': '$(touch /tmp/publisher-invalid)'}]:
                result, args = launcher.launch(mode, changes=valid | {'INPUT_MODE': 'publish'} | change,
                                               omit=['INPUT_RECOVER_STAGE_ID'])
                with self.subTest(mode=mode, change=change):
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIsNone(args)

    def test_actual_recipe_preflight_passes_valid_tuple_and_rejects_wrong_policy_before_mint(self):
        fixture = public.RecipePrecredentialIntegrationTests()
        fixture.setUp()
        for mode in ['validate', 'publish']:
            for policy, valid in [(POLICY, True), ('waiver', False)]:
                result, capture, reached_mint = fixture.preflight(mode, changes=dict(branch='main', tag=TAG, release_policy=policy))
                with self.subTest(mode=mode, policy=policy):
                    self.assertEqual(result.returncode == 0, valid)
                    self.assertEqual(capture is not None, valid)
                    self.assertEqual(reached_mint, valid)


if __name__ == '__main__':
    unittest.main()
