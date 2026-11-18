import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from delivery.analysis_store import ArtifactStore, PublicationConflict, UnknownArtifact
from delivery.database import ArchiveDatabase
from exchange.export import export_report
from exchange.import_check import PackageVerificationError, accept_package, verify_package
from intake_examples import write_fixtures
from network.revisions import RevisionRepository
from quality.reports import ReportService
from study.cohorts import StudyService
from study.timeline import position_sources
from topology.inclusions import AnalysisService


def counts(db):
    return {table: db.connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
            for table in ('studies', 'artifacts', 'receipts', 'acceptances', 'source_bindings')}


def compare(path):
    with ZipFile(path) as package:
        return {name: package.read(name) for name in package.namelist()}


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix='chengchuan-intake-test-'))
        self.addCleanup(lambda: shutil.rmtree(self.directory, ignore_errors=True))
        self.paths = write_fixtures(self.directory / 'packages')
        self.archive = self.directory / 'receiver.sqlite'

    def test_accept_receipts_idempotence_and_conflicts(self):
        with ArchiveDatabase.open(self.archive) as db:
            store = ArtifactStore(db)
            a = accept_package(store, 'A', self.paths['a'])
            b = accept_package(store, 'B', self.paths['b'])
            followup = accept_package(store, 'A', self.paths['followup'])
            self.assertEqual((a.source_id, a.report_request_id), ('A', 'morning'))
            self.assertEqual(a.report_request_id, b.report_request_id)
            self.assertEqual(a.study_id, followup.study_id)
            self.assertEqual(a.analysis_id, followup.analysis_id)
            self.assertNotEqual(a.analysis_id, b.analysis_id)
            self.assertNotEqual(a.report_id, followup.report_id)
            self.assertEqual(store.find_acceptance('A', 'morning'), a)
            self.assertEqual(store.find_acceptance('B', 'morning'), b)
            self.assertEqual(store.find_acceptance('A', 'followup'), followup)
            self.assertIsNone(store.find_acceptance('A', 'unseen'))
            self.assertIsNone(store.find_acceptance('C', 'morning'))

            before = counts(db)
            self.assertEqual(accept_package(store, 'A', self.paths['a']), a)
            self.assertEqual(counts(db), before)

            for name in ('study_conflict', 'analysis_conflict', 'report_conflict', 'damaged'):
                with self.subTest(package=name):
                    if name == 'damaged':
                        with self.assertRaises(PackageVerificationError):
                            accept_package(store, 'A', self.paths[name])
                    else:
                        with self.assertRaises(PublicationConflict):
                            accept_package(store, 'A', self.paths[name])
                    self.assertEqual(counts(db), before)

            # An identical delivery may arrive from another source and keeps its own receipt.
            twin = accept_package(store, 'C', self.paths['a'])
            self.assertEqual(twin.study_id, a.study_id)
            self.assertEqual(twin.report_id, a.report_id)
            self.assertEqual(store.find_acceptance('C', 'morning'), twin)
            self.assertEqual(store.find_acceptance('A', 'morning'), a)
            self.assertEqual(counts(db)['artifacts'], before['artifacts'])
            bindings = db.connection.execute(
                'SELECT source_id FROM source_bindings WHERE kind=? AND request_id=? ORDER BY source_id',
                ('report', 'morning')).fetchall()
            self.assertEqual([row[0] for row in bindings], ['A', 'B', 'C'])

    def test_invalid_text_and_missing_receipt(self):
        with ArchiveDatabase.open(self.archive) as db:
            store = ArtifactStore(db)
            for source_id in ('', '   ', 7, None, '\ud800'):
                with self.subTest(source=source_id):
                    with self.assertRaises(ValueError):
                        accept_package(store, source_id, self.paths['a'])
            for source_id, request in (('A', ''), ('A', 3), ('  ', 'morning'), ('A', '\udfff')):
                with self.subTest(source=source_id, request=request):
                    with self.assertRaises(ValueError):
                        store.find_acceptance(source_id, request)
            self.assertEqual(counts(db)['acceptances'], 0)

    def test_reopen_fixed_chain_local_report_and_export(self):
        with ArchiveDatabase.open(self.archive) as db:
            store = ArtifactStore(db)
            a = accept_package(store, 'A', self.paths['a'])
            b = accept_package(store, 'B', self.paths['b'])
            accept_package(store, 'A', self.paths['followup'])
            analysis = store.read_artifact(a.analysis_id)
            report = store.read_artifact(a.report_id)
        verified_original = verify_package(self.paths['a'])
        with ArchiveDatabase.open(self.archive) as db:
            store = ArtifactStore(db)
            self.assertEqual(store.find_acceptance('A', 'morning'), a)
            study = StudyService(db).get_study(a.study_id)
            self.assertEqual(study.request_id, 'morning')
            self.assertEqual(position_sources(study.positions), analysis.payload['positions'])
            self.assertEqual(store.read_artifact(a.analysis_id), analysis)
            self.assertEqual(store.read_artifact(a.report_id), report)
            local = ReportService(store).create_report(a.analysis_id, 'morning')
            self.assertEqual(local.payload['intervals'], [[0, 0, 1]])
            self.assertEqual(store.find_receipt('report', 'morning'), local)
            # Same parent, request and payload address the same fixed artifact.
            self.assertEqual(local.artifact_id, a.report_id)
            self.assertEqual(store.read_artifact(a.report_id), local)
            original_path = export_report(store, a.report_id, self.directory / 'original.zip')
            local_path = export_report(store, local.artifact_id, self.directory / 'local.zip')
            second = ReportService(store).create_report(a.analysis_id, 'second-local')
            self.assertEqual(second.payload, local.payload)
            self.assertEqual(export_report(store, b.report_id, self.directory / 'b.zip').is_file(), True)

        self.assertEqual(verify_package(original_path).report_id, a.report_id)
        checked_local = verify_package(local_path)
        self.assertEqual(checked_local.analysis.study_id, a.study_id)
        self.assertEqual([[item.start, item.end, item.multiplicity] for item in checked_local.report.intervals],
                         local.payload['intervals'])
        # The original package keeps its exact three canonical members.
        self.assertEqual(compare(original_path), compare(self.paths['a']))
        with ZipFile(local_path) as package:
            local_analysis = json.loads(package.read('analysis.json'))
            local_report = json.loads(package.read('report.json'))
        self.assertEqual(local_analysis['id'], a.analysis_id)
        self.assertEqual(local_report['payload']['analysis_id'], a.analysis_id)
        self.assertEqual(local_report['request_id'], 'morning')
        self.assertEqual(verify_package(original_path).report_id, a.report_id)

    def test_local_same_request_coexists_with_accepted_source(self):
        with ArchiveDatabase.open(self.archive) as db:
            store = ArtifactStore(db)
            a = accept_package(store, 'A', self.paths['a'])
            studies = StudyService(db)
            repository = RevisionRepository(db)
            ref = repository.save_network('local', 1, [1, 2, 3], [(1, 2), (2, 3), (3, 1)], [])
            local_study = studies.freeze_study('morning', [(900, ref)])
            self.assertNotEqual(local_study.study_id, a.study_id)
            analysis = AnalysisService(studies, store).analyze_study(local_study.study_id, 'morning')
            self.assertNotEqual(analysis.artifact_id, a.analysis_id)
            local_report = ReportService(store).create_report(analysis.artifact_id, 'morning')
            self.assertNotEqual(local_report.artifact_id, a.report_id)
            self.assertEqual(store.find_receipt('report', 'morning'), local_report)
            self.assertEqual(store.find_acceptance('A', 'morning'), a)
            self.assertEqual(store.read_artifact(a.report_id).payload['intervals'], [[0, 0, 1]])
            self.assertEqual(store.read_artifact(local_report.artifact_id), local_report)
            export_report(store, a.report_id, self.directory / 'accepted.zip')
            export_report(store, local_report.artifact_id, self.directory / 'local.zip')
        self.assertEqual(verify_package(self.directory / 'accepted.zip').report_id, a.report_id)
        self.assertEqual(verify_package(self.directory / 'local.zip').report_id, local_report.artifact_id)

    def test_local_freeze_with_accepted_identity_reuses_fixed_result(self):
        with ArchiveDatabase.open(self.archive) as db:
            store = ArtifactStore(db)
            a = accept_package(store, 'A', self.paths['a'])
            repository = RevisionRepository(db)
            ref = repository.save_network('ridge', 1, [1, 2, 3], [(1, 2), (2, 3), (1, 3)], [])
            local_study = StudyService(db).freeze_study('morning', [(900, ref)])
            # The exact same content under the same request addresses the fixed study.
            self.assertEqual(local_study.study_id, a.study_id)
            self.assertEqual(StudyService(db).get_study(a.study_id).request_id, 'morning')
            self.assertEqual(db.connection.execute('SELECT count(*) FROM studies').fetchone()[0], 1)
            self.assertEqual(db.connection.execute(
                'SELECT count(*) FROM study_receipts WHERE request_id=?', ('morning',)).fetchone()[0], 1)
            self.assertEqual(store.find_acceptance('A', 'morning'), a)

    def test_commit_failure_leaves_no_state_and_retries(self):
        with ArchiveDatabase.open(self.archive) as db, ArchiveDatabase.open(self.archive) as reader:
            observer = ArtifactStore(reader)

            def fail(operation):
                self.assertEqual(operation, 'acceptance')
                with self.assertRaises(UnknownArtifact):
                    observer.read_artifact(verify_package(self.paths['a']).report_id)
                self.assertIsNone(observer.find_acceptance('A', 'morning'))
                raise sqlite3.IntegrityError('acceptance storage refused')

            failing = ArtifactStore(db, before_commit=fail)
            with self.assertRaises(sqlite3.IntegrityError):
                accept_package(failing, 'A', self.paths['a'])
            self.assertEqual(counts(db), {table: 0 for table in
                                          ('studies', 'artifacts', 'receipts', 'acceptances', 'source_bindings')})
            self.assertFalse(db.connection.in_transaction)
            self.assertIsNone(observer.find_acceptance('A', 'morning'))
            retried = accept_package(observer, 'A', self.paths['a'])
            self.assertEqual(observer.find_acceptance('A', 'morning'), retried)

    def test_schema_migration_preserves_existing_v1_archive(self):
        legacy = self.directory / 'legacy.sqlite'
        with ArchiveDatabase.open(legacy) as db:
            ref = RevisionRepository(db).save_network('old', 1, [1, 2, 3], [(1, 2), (2, 3), (3, 1)], [])
            study = StudyService(db).freeze_study('legacy', [(10, ref)])
            store = ArtifactStore(db)
            analysis = AnalysisService(StudyService(db), store).analyze_study(study.study_id, 'legacy')
            report = ReportService(store).create_report(analysis.artifact_id, 'legacy')
        # Rewind the file to the shape version 1 archives had before acceptance.
        connection = sqlite3.connect(legacy)
        try:
            connection.execute('PRAGMA foreign_keys = OFF')
            for table in ('source_bindings', 'acceptances', 'artifact_requests', 'study_receipts'):
                connection.execute(f'DROP TABLE {table}')
            connection.execute('''CREATE TABLE old_studies (
                id TEXT PRIMARY KEY NOT NULL, request_id TEXT UNIQUE NOT NULL,
                fingerprint TEXT NOT NULL, body BLOB NOT NULL)''')
            connection.execute('INSERT INTO old_studies SELECT * FROM studies')
            connection.execute('DROP TABLE studies')
            connection.execute('ALTER TABLE old_studies RENAME TO studies')
            connection.commit()
        finally:
            connection.close()
        with ArchiveDatabase.open(legacy) as db:
            self.assertEqual(db.connection.execute(
                'SELECT count(*) FROM studies WHERE request_id=?', ('legacy',)).fetchone()[0], 1)
        with ArchiveDatabase.open(legacy) as db:
            store = ArtifactStore(db)
            self.assertEqual(store.read_artifact(report.artifact_id), report)
            self.assertEqual(store.read_artifact(analysis.artifact_id), analysis)
            self.assertEqual(store.find_receipt('analysis', 'legacy'), analysis)
            self.assertEqual(StudyService(db).get_study(study.study_id), study)
            ref = RevisionRepository(db).save_network('old', 1, [1, 2, 3], [(1, 2), (2, 3), (3, 1)], [])
            self.assertEqual(StudyService(db).freeze_study('legacy', [(10, ref)]).study_id, study.study_id)
            accepted = accept_package(store, 'A', self.paths['a'])
            self.assertEqual(store.find_acceptance('A', 'morning'), accepted)
            local = ReportService(store).create_report(accepted.analysis_id, 'morning')
            self.assertEqual(local.payload['intervals'], [[0, 0, 1]])
            self.assertEqual(store.read_artifact(report.artifact_id), report)
            exported = export_report(store, report.artifact_id, self.directory / 'legacy.zip')
            self.assertEqual(verify_package(exported).report_id, report.artifact_id)


if __name__ == '__main__':
    unittest.main()
