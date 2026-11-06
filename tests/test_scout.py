"""验证侦察结果的证据边界、历史比较和可搬迁执行。"""

import copy
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'micro-saas-scout/scripts/manage_results.py'
spec = importlib.util.spec_from_file_location('scout', SCRIPT)
scout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scout)


def fixture():
    claim = {'text': '虚构测试事实', 'basis': 'fact', 'source_ids': ['s1']}
    product = {
        'name': 'Fixture', 'website': 'https://example.com/tool',
        'decision': 'watch', 'reason': '仅用于脚本测试',
        'evidence_level': 'insufficient',
        'claims': {key: copy.deepcopy(claim) for key in scout.CLAIMS},
        'revenue': {'status': 'unknown', 'text': None, 'as_of': None, 'source_ids': []},
    }
    return {
        'schema_version': 1, 'mode': 'smoke-test', 'observed_on': '2026-11-06',
        'scope': '虚构测试数据，不能作为研究结论', 'shortlist_limit': 5,
        'queries': ['fixture only'], 'limitations': ['无真实商业证据'],
        'sources': [{'id': 's1', 'url': 'https://example.com/pricing',
                     'title': 'Fixture source', 'kind': 'official', 'status': 'ok',
                     'accessed_on': '2026-11-06', 'published_on': None}],
        'products': [product],
    }


class ScoutTests(unittest.TestCase):
    def test_valid_unknown_revenue_remains_unknown(self):
        data = scout.validate(fixture())
        self.assertIsNone(data['products'][0]['revenue']['text'])

    def test_identity_preserves_product_paths_and_meaningful_queries(self):
        self.assertEqual(scout.identity('http://WWW.Example.com/tool/?utm_source=x#top'),
                         scout.identity('https://example.com/tool'))
        self.assertNotEqual(scout.identity('https://example.com/app?id=1'),
                            scout.identity('https://example.com/app?id=2'))
        self.assertNotEqual(scout.identity('https://example.com/tool'),
                            scout.identity('https://example.com/another'))

    def test_duplicate_is_reported_instead_of_losing_conflicting_claims(self):
        data = fixture()
        product = copy.deepcopy(data['products'][0])
        product['website'] = 'http://www.example.com/tool/?utm_campaign=test'
        product['claims']['pricing']['text'] = '冲突价格'
        data['products'].append(product)
        with self.assertRaisesRegex(ValueError, '重复产品'):
            scout.validate(data)

    def test_broken_or_inaccessible_citation_cannot_support_claim(self):
        for variant in ['missing', 'blocked', 'error']:
            data = fixture()
            if variant == 'missing':
                data['products'][0]['claims']['pricing']['source_ids'] = ['no-source']
            else:
                data['sources'][0]['status'] = variant
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                scout.validate(data)

    def test_fact_requires_source_and_unknown_cannot_contain_fact(self):
        for claim in [
            {'text': '$1M', 'basis': 'fact', 'source_ids': []},
            {'text': '$1M', 'basis': 'unknown', 'source_ids': []},
        ]:
            data = fixture()
            data['products'][0]['claims']['pricing'] = claim
            with self.subTest(claim=claim), self.assertRaises(ValueError):
                scout.validate(data)

    def test_revenue_cannot_be_promoted_without_date_and_evidence(self):
        data = fixture()
        data['products'][0]['revenue'].update(status='founder_reported', text='USD 1,000 MRR')
        with self.assertRaises(ValueError):
            scout.validate(data)

    def test_shortlist_requires_demand_evidence_and_respects_limit(self):
        for variant in ['insufficient', 'demand_missing', 'limit']:
            data = fixture()
            product = data['products'][0]
            product['decision'] = 'shortlist'
            if variant != 'insufficient':
                product['evidence_level'] = 'demand'
            if variant == 'demand_missing':
                product['claims']['demand'] = {'text': None, 'basis': 'unknown', 'source_ids': []}
            if variant == 'limit':
                data['shortlist_limit'] = 0
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                scout.validate(data)

    def test_bad_dates_and_credential_urls_rejected(self):
        for change in [lambda d: d.update(observed_on='2026-02-30'),
                       lambda d: d['sources'][0].update(accessed_on='2026-11-07'),
                       lambda d: d['sources'][0].update(url='https://u:p@example.com'),
                       lambda d: d['sources'][0].update(url='https://example.com?api_key=secret')]:
            data = fixture()
            change(data)
            with self.assertRaises(ValueError):
                scout.validate(data)

    def test_deep_dive_requires_executable_analysis(self):
        data = fixture()
        data['mode'] = 'deep-dive'
        with self.assertRaisesRegex(ValueError, 'analysis'):
            scout.validate(data)
        data['products'][0]['analysis'] = {
            key: {'text': '假设及验证步骤', 'basis': 'inference', 'source_ids': []}
            for key in scout.ANALYSIS
        }
        scout.validate(data)

    def test_optional_analysis_is_validated_when_present(self):
        data = fixture()
        data['products'][0]['analysis'] = {'mvp': 'not a claim'}
        with self.assertRaises(ValueError):
            scout.validate(data)

    def test_skill_reference_links_resolve_after_installation(self):
        for path in SCRIPT.parents[1].rglob('*.md'):
            for link in re.findall(r'\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
                if not link.startswith(('https://', 'http://', '#')):
                    with self.subTest(path=path, link=link):
                        self.assertTrue((path.parent / link.split('#')[0]).is_file())

    def test_changes_are_business_changes_not_source_id_churn(self):
        old = fixture()
        new = copy.deepcopy(old)
        new['sources'][0]['id'] = 'fresh-id'
        for claim in new['products'][0]['claims'].values():
            claim['source_ids'] = ['fresh-id']
        result = scout.compare(new, [old])
        self.assertEqual(result['returning'][0]['changed_fields'], [])
        new['products'][0]['claims']['pricing']['text'] = 'USD 29/month'
        result = scout.compare(new, [old])
        self.assertIn('claims.pricing', result['returning'][0]['changed_fields'])

    def test_missing_from_run_is_not_called_closed(self):
        old = fixture()
        new = fixture()
        new['products'] = []
        self.assertEqual(scout.compare(new, [old])['not_rechecked'], ['example.com/tool'])

    def test_snapshot_is_immutable_and_bundle_is_portable(self):
        with tempfile.TemporaryDirectory(prefix='scout test ') as folder:
            root = Path(folder)
            installed = root / 'installed skill'
            shutil.copytree(SCRIPT.parents[1], installed, ignore=shutil.ignore_patterns('__pycache__'))
            source = root / 'input.json'
            source.write_text(json.dumps(fixture()), encoding='utf-8')
            command = [sys.executable, str(installed / 'scripts/manage_results.py'),
                       'save', str(source), '--output', str(root / 'run')]
            first = subprocess.run(command, cwd=folder, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            report = (root / 'run/report.md').read_text(encoding='utf-8')
            self.assertIn('https://example.com/pricing', report)
            self.assertIn('smoke-test', report)
            snapshot = (root / 'run/results.json').read_bytes()
            second = subprocess.run(command, cwd=folder, capture_output=True, text=True)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual((root / 'run/results.json').read_bytes(), snapshot)

    def test_invalid_input_creates_no_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'bad.json'
            source.write_text('{"schema_version": 99}', encoding='utf-8')
            run = subprocess.run([sys.executable, str(SCRIPT), 'save', str(source),
                                  '--output', str(root / 'out')], capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertFalse((root / 'out').exists())


if __name__ == '__main__':
    unittest.main()
