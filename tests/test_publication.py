import sqlite3
import tempfile
import unittest
from pathlib import Path

from delivery.analysis_store import ArtifactStore, PublicationConflict, UnknownArtifact
from delivery.database import ArchiveDatabase
from network.revisions import RevisionRepository
from quality.reports import ReportService
from study.cohorts import StudyService
from topology.inclusions import AnalysisService


class PublicationTests(unittest.TestCase):
    def test_rollback_and_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'archive.db'
            with ArchiveDatabase.open(path) as db, ArchiveDatabase.open(path) as observer:
                repo = RevisionRepository(db)
                ref = repo.save_network('hill', 1, [1, 2, 3], [(1, 2), (2, 3), (1, 3)], [])
                studies = StudyService(db)
                study = studies.freeze_study('s', [(1, ref)])
                other = studies.freeze_study('t', [(2, ref)])
                observer_store = ArtifactStore(observer)
                attempted = {}
                failed = set()

                def before_commit(kind):
                    if kind in failed:
                        return
                    connection = db.connection
                    artifact_id = connection.execute('SELECT artifact_id FROM receipts WHERE kind=? AND request_id=?',
                                                     (kind, 'publish')).fetchone()[0]
                    attempted[kind] = artifact_id
                    self.assertIsNone(observer_store.find_receipt(kind, 'publish'))
                    with self.assertRaises(UnknownArtifact):
                        observer_store.read_artifact(artifact_id)
                    failed.add(kind)
                    connection.execute('INSERT INTO receipts SELECT * FROM receipts WHERE kind=? AND request_id=?',
                                       (kind, 'publish'))

                store = ArtifactStore(db, before_commit=before_commit)
                analyzer, reports = AnalysisService(studies, store), ReportService(store)
                with self.assertRaises(sqlite3.IntegrityError):
                    analyzer.analyze_study(study.study_id, 'publish')
                self.assertIsNone(store.find_receipt('analysis', 'publish'))
                self.assertEqual(db.connection.execute('SELECT count(*) FROM artifacts').fetchone()[0], 0)
                self.assertFalse(db.connection.in_transaction)
                with self.assertRaises(UnknownArtifact):
                    store.read_artifact(attempted['analysis'])
                analysis = analyzer.analyze_study(study.study_id, 'publish')
                self.assertEqual(analysis.artifact_id, attempted['analysis'])
                self.assertEqual(analyzer.analyze_study(study.study_id, 'publish').receipt, analysis.receipt)
                self.assertEqual(observer_store.read_artifact(analysis.artifact_id), analysis)
                with self.assertRaises(PublicationConflict):
                    analyzer.analyze_study(other.study_id, 'publish')
                with self.assertRaises(sqlite3.IntegrityError):
                    reports.create_report(analysis.artifact_id, 'publish')
                self.assertIsNone(store.find_receipt('report', 'publish'))
                self.assertEqual(db.connection.execute('SELECT count(*) FROM artifacts').fetchone()[0], 1)
                self.assertFalse(db.connection.in_transaction)
                with self.assertRaises(UnknownArtifact):
                    store.read_artifact(attempted['report'])
                report = reports.create_report(analysis.artifact_id, 'publish')
                self.assertEqual(report.artifact_id, attempted['report'])
                self.assertEqual(report.payload['intervals'], [[0, 0, 1]])
                self.assertEqual(reports.create_report(analysis.artifact_id, 'publish').receipt, report.receipt)
                self.assertEqual(observer_store.read_parent_chain(report.artifact_id)[1], analysis)
                plain = ArtifactStore(db)
                newer = AnalysisService(studies, plain).analyze_study(other.study_id, 'other')
                with self.assertRaises(PublicationConflict):
                    reports.create_report(newer.artifact_id, 'publish')
                self.assertEqual(store.read_artifact(report.artifact_id), report)
                with self.assertRaises(PublicationConflict):
                    store.publish('analysis', 'publish', study.study_id, dict(analysis.payload, maps=[{}]))

    def test_receipt_insert_failure_leaves_no_artifact(self):
        with ArchiveDatabase.open(':memory:') as db:
            ref = RevisionRepository(db).save_network('hill', 1, [], [], [])
            studies = StudyService(db)
            study = studies.freeze_study('s', [(0, ref)])
            db.connection.execute('''CREATE TEMP TRIGGER reject_receipt BEFORE INSERT ON receipts
                                     BEGIN SELECT RAISE(ABORT, 'receipt storage refused'); END''')
            store = ArtifactStore(db)
            analyzer = AnalysisService(studies, store)
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'receipt storage refused'):
                analyzer.analyze_study(study.study_id, 'r')
            self.assertEqual(db.connection.execute('SELECT count(*) FROM artifacts').fetchone()[0], 0)
            db.connection.execute('DROP TRIGGER reject_receipt')
            published = analyzer.analyze_study(study.study_id, 'r')
            self.assertEqual(store.find_receipt('analysis', 'r'), published)
