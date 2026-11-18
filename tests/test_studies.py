import unittest

from delivery.database import ArchiveDatabase
from network.model import RevisionRef, UnknownRevision
from network.revisions import RevisionRepository
from study.cohorts import InvalidStudy, StudyConflict, StudyService
from study.timeline import position_sources


class StudyTests(unittest.TestCase):
    def setUp(self):
        self.db = ArchiveDatabase.open(':memory:')
        self.addCleanup(self.db.close)
        self.repo = RevisionRepository(self.db)
        self.studies = StudyService(self.db)

    def test_invalid_and_stable_intersection(self):
        left = self.repo.save_network('line', 1, [4, 3, 2, 1], [(3, 1), (3, 2), (2, 1)], [])
        right = self.repo.save_network('line', 2, [2, 1, 4, 5], [(5, 2), (4, 1), (1, 2)], [])
        unknown = RevisionRef('line', 3, left.digest)
        with self.assertRaises(UnknownRevision):
            self.studies.freeze_study('study', [(10, left), (11, unknown)])
        with self.assertRaises(InvalidStudy):
            self.studies.freeze_study('study', [(10, left), (10, right)])
        self.assertEqual(self.db.connection.execute('SELECT count(*) FROM studies').fetchone()[0], 0)
        study = self.studies.freeze_study('study', [(10, left), (11, right)])
        self.assertEqual(study.positions[1].complex.vertices, (1, 2, 4))
        self.assertEqual(study.positions[1].complex.edges, ((1, 2),))
        self.assertEqual(study.positions[1].refs, (left, right))
        self.assertIsNone(study.positions[1].time)
        self.assertEqual([(arrow.source, arrow.target) for arrow in study.arrows], [(1, 0), (1, 2)])
        self.assertEqual(self.studies.get_study(study.study_id), study)
        self.assertEqual(position_sources(study.positions)[2]['time'], 11)

    def test_freeze_request_identity_and_time_validation(self):
        ref = self.repo.save_network('line', 1, [1], [], [])
        for times in ([], [1, '2'], [float('nan')], [float('inf')], [True], [2, 1], list(range(17))):
            with self.subTest(times=times):
                with self.assertRaises(InvalidStudy):
                    self.studies.freeze_study('s', [(time, ref) for time in times])
        samples = [('09:00', ref), ('10:00', ref)]
        original = self.studies.freeze_study('s', samples)
        self.assertEqual(self.studies.freeze_study('s', iter(samples)), original)
        with self.assertRaises(StudyConflict):
            self.studies.freeze_study('s', [('09:15', ref)])
        self.assertEqual(self.db.connection.execute('SELECT count(*) FROM studies').fetchone()[0], 1)
        self.assertEqual(self.studies.get_study(original.study_id).samples[0].time, '09:00')

    def test_single_sample_and_empty_intersection(self):
        left = self.repo.save_network('line', 1, [1, 2], [(1, 2)], [])
        right = self.repo.save_network('line', 2, [3, 4], [(4, 3)], [])
        single = self.studies.freeze_study('single', [(1.5, left)])
        self.assertEqual(len(single.positions), 1)
        self.assertEqual(single.arrows, ())
        self.assertEqual(single.positions[0].time, 1.5)
        pair = self.studies.freeze_study('pair', [(1.5, left), (3, right)])
        self.assertEqual(pair.positions[1].complex.vertices, ())
        self.assertEqual(pair.positions[1].complex.edges, ())
        self.assertEqual(pair.positions[1].refs, (left, right))
        self.assertEqual(len(pair.arrows), 2)
