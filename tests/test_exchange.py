import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from delivery.analysis_store import ArtifactStore
from delivery.database import ArchiveDatabase
from exchange.export import ExportError, export_report
from exchange.import_check import PackageVerificationError, verify_package
from network.revisions import RevisionRepository
from quality.encoding import Interval
from quality.reports import ReportService
from study.cohorts import StudyService
from topology.inclusions import AnalysisService


def fixture(db):
    repo, studies, store = RevisionRepository(db), StudyService(db), ArtifactStore(db)
    ref = repo.save_network('slope', 1, [1, 2, 3], [(1, 2), (2, 3), (1, 3)], [])
    study = studies.freeze_study('sampling', [(5, ref), (8, ref)])
    analysis = AnalysisService(studies, store).analyze_study(study.study_id, 'analysis')
    report = ReportService(store).create_report(analysis.artifact_id, 'report')
    return store, ref, report


def zip_members(path):
    with ZipFile(path) as container:
        return {name: container.read(name) for name in container.namelist()}


def write_zip(path, members):
    with ZipFile(path, 'w') as container:
        for name, body in members.items():
            container.writestr(name, body)


def pack_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def restamp(record):
    body = {key: value for key, value in record.items() if key != 'id'}
    record['id'] = record['kind'] + ':' + hashlib.sha256(pack_json(body)).hexdigest()


def replace_members(members, updates):
    result = dict(members)
    manifest = json.loads(result['manifest.json'])
    for name, record in updates.items():
        result[name] = pack_json(record)
        manifest['members'][name] = {'id': record['id'], 'sha256': hashlib.sha256(result[name]).hexdigest()}
    result['manifest.json'] = pack_json(manifest)
    return result


class ExchangeTests(unittest.TestCase):
    def test_offline_roundtrip_and_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'source.db'
            offline = root / 'offline'
            offline.mkdir()
            package = offline / 'report.zip'
            with ArchiveDatabase.open(archive) as db:
                store, ref, report = fixture(db)
                export_report(store, report.artifact_id, package)
                export_report(store, report.artifact_id, offline / 'repeat.zip')
                self.assertEqual(package.read_bytes(), (offline / 'repeat.zip').read_bytes())
            archive.unlink()
            verified = verify_package(package)
            self.assertEqual(verified.report_id, report.artifact_id)
            self.assertEqual(verified.report.intervals, (Interval(0, 2, 1),))
            self.assertEqual([position['time'] for position in verified.sources], [5, None, 8])
            self.assertEqual([entry['digest'] for entry in verified.sources[1]['refs']], [ref.digest, ref.digest])
            members = zip_members(package)
            damaged = json.loads(members['analysis.json'])
            damaged['payload']['maps'][0]['columns'][0] = 0
            write_zip(offline / 'damaged.zip', dict(members, **{'analysis.json': pack_json(damaged)}))
            with self.assertRaisesRegex(PackageVerificationError, 'digest mismatch'):
                verify_package(offline / 'damaged.zip')
            missing = dict(members)
            del missing['analysis.json']
            write_zip(offline / 'missing.zip', missing)
            with self.assertRaisesRegex(PackageVerificationError, 'missing'):
                verify_package(offline / 'missing.zip')

    def test_digest_valid_relation_and_parent_mismatches(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report.zip'
            with ArchiveDatabase.open(':memory:') as db:
                store, _, report = fixture(db)
                export_report(store, report.artifact_id, path)
            original = zip_members(path)
            altered_report = json.loads(original['report.json'])
            altered_report['parent_id'] = 'analysis:' + 'a' * 64
            altered_report['payload']['analysis_id'] = altered_report['parent_id']
            restamp(altered_report)
            write_zip(path, replace_members(original, {'report.json': altered_report}))
            with self.assertRaisesRegex(PackageVerificationError, 'parent chain mismatch'):
                verify_package(path)
            for field, replacement, reason in (('target_dim', 2, 'map dimensions'), ('target', 2, 'map endpoints'),
                                               ('columns', [2], 'map columns')):
                with self.subTest(field=field):
                    altered_analysis = json.loads(original['analysis.json'])
                    altered_analysis['payload']['maps'][0][field] = replacement
                    restamp(altered_analysis)
                    updated_report = json.loads(original['report.json'])
                    updated_report['payload']['analysis_id'] = updated_report['parent_id'] = altered_analysis['id']
                    restamp(updated_report)
                    write_zip(path, replace_members(original, {'analysis.json': altered_analysis, 'report.json': updated_report}))
                    with self.assertRaisesRegex(PackageVerificationError, reason):
                        verify_package(path)

    def test_export_failure_cleans_up(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'source.db'
            occupied = root / 'existing-directory'
            occupied.mkdir()
            with ArchiveDatabase.open(archive) as db:
                store, _, report = fixture(db)
                existing_files = sorted(root.iterdir())
                with self.assertRaises(ExportError):
                    export_report(store, report.artifact_id, occupied)
                with self.assertRaisesRegex(ExportError, 'source archive'):
                    export_report(store, report.artifact_id, archive)
                self.assertEqual(sorted(root.iterdir()), existing_files)
                self.assertTrue(occupied.is_dir())
                self.assertEqual(store.read_artifact(report.artifact_id), report)
