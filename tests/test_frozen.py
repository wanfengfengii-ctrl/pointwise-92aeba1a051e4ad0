import tempfile
import unittest
from pathlib import Path

from delivery.analysis_store import ArtifactStore
from delivery.database import ArchiveDatabase
from delivery.schema import SCHEMA_VERSION, SchemaMismatch, initialize_schema
from exchange.export import export_report
from exchange.import_check import verify_package
from network.revisions import RevisionRepository
from quality.reports import ReportService
from study.cohorts import StudyService
from topology.inclusions import AnalysisService


class FrozenTests(unittest.TestCase):
    def test_correction_reopen_and_object_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'archive.db'
            output = Path(directory) / 'old.zip'
            rim = [(1, 2), (2, 3), (3, 1)]
            with ArchiveDatabase.open(path) as db:
                repo, studies, store = RevisionRepository(db), StudyService(db), ArtifactStore(db)
                ref = repo.save_network('ridge', 1, [1, 2, 3], rim, [])
                study = studies.freeze_study('time', [(700, ref), (800, ref)])
                analysis = AnalysisService(studies, store).analyze_study(study.study_id, 'analysis')
                report = ReportService(store).create_report(analysis.artifact_id, 'report')
                baseline = store.read_artifact(report.artifact_id)
                self.assertEqual(baseline.payload['intervals'], [[0, 2, 1]])
                first = store.read_artifact(report.artifact_id)
                first.payload['intervals'][0][0] = 2
                first.payload['positions'][0]['refs'].clear()
                altered_analysis = store.read_artifact(analysis.artifact_id)
                altered_analysis.payload['maps'][0]['columns'].clear()
                self.assertEqual(store.read_artifact(report.artifact_id), baseline)
                self.assertEqual(store.read_artifact(analysis.artifact_id), analysis)
                new = repo.save_network('ridge', 2, [1, 2, 3], rim, [(1, 2, 3)])
                db.connection.execute('CREATE TABLE user_notes (text TEXT NOT NULL)')
                db.connection.execute('INSERT INTO user_notes VALUES (?)', ('field correction retained',))
                initialize_schema(db.connection)
                self.assertEqual(studies.get_study(study.study_id), study)
            with ArchiveDatabase.open(path) as db:
                store = ArtifactStore(db)
                self.assertEqual(db.connection.execute('SELECT text FROM user_notes').fetchone()[0], 'field correction retained')
                self.assertEqual(RevisionRepository(db).get_revision(new).complex.faces, ((1, 2, 3),))
                statements = []
                db.connection.set_trace_callback(statements.append)
                self.assertEqual(store.read_artifact(report.artifact_id), baseline)
                self.assertEqual(store.find_receipt('report', 'report').receipt, report.receipt)
                second = ReportService(store).create_report(analysis.artifact_id, 'second-review')
                self.assertEqual(second.payload, baseline.payload)
                db.connection.set_trace_callback(None)
                self.assertFalse(any('from revisions' in sql.lower() or 'from studies' in sql.lower()
                                     for sql in statements), statements)
                export_report(store, report.artifact_id, output)
            verified = verify_package(output)
            self.assertEqual(verified.report_id, report.artifact_id)
            self.assertEqual(verified.study, study)
            self.assertEqual(verified.sources[1]['refs'][1]['revision'], 1)

    def test_schema_mismatch_preserves_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'archive.db'
            with ArchiveDatabase.open(path) as db:
                ref = RevisionRepository(db).save_network('ridge', 1, [1], [], [])
                db.connection.execute('PRAGMA user_version = 99')
                with self.assertRaises(SchemaMismatch):
                    ArchiveDatabase.open(path)
                self.assertEqual(db.connection.execute('PRAGMA user_version').fetchone()[0], 99)
                self.assertEqual(RevisionRepository(db).get_revision(ref).complex.vertices, (1,))
                db.connection.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')
            with ArchiveDatabase.open(path) as db:
                self.assertEqual(RevisionRepository(db).get_revision(ref).ref, ref)
