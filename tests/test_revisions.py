import unittest

from delivery.database import ArchiveDatabase
from network.model import InvalidComplex, RevisionConflict, RevisionRef, UnknownRevision
from network.revisions import RevisionRepository
from study.cohorts import StudyService


TRIANGLE = [(1, 2), (2, 3), (1, 3)]


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.db = ArchiveDatabase.open(':memory:')
        self.addCleanup(self.db.close)
        self.repo = RevisionRepository(self.db)

    def test_idempotent_and_correction(self):
        original = self.repo.save_network('north', 1, [1, 2, 3], TRIANGLE, [])
        again = self.repo.save_network('north', 1, [3, 1, 2, 1], [(3, 1), (3, 2), (2, 1), (1, 2)], [])
        self.assertEqual(again, original)
        studies = StudyService(self.db)
        frozen = studies.freeze_study('selection', [(10, original)])
        corrected = self.repo.save_network('north', 2, [1, 2, 3], TRIANGLE, [(1, 2, 3)])
        old_after = studies.get_study(frozen.study_id)
        self.assertNotEqual(corrected.digest, original.digest)
        self.assertEqual(self.repo.get_revision(original).complex.faces, ())
        self.assertEqual(self.repo.get_revision(corrected).complex.faces, ((1, 2, 3),))
        self.assertEqual(old_after, frozen)
        self.assertEqual(old_after.samples[0].revision.ref, original)
        self.assertEqual(self.db.connection.execute('SELECT count(*) FROM revisions').fetchone()[0], 2)

    def test_same_identity_different_faces_conflict(self):
        ref = self.repo.save_network('north', 'reported', [1, 2, 3], TRIANGLE, [])
        with self.assertRaises(RevisionConflict):
            self.repo.save_network('north', 'reported', [1, 2, 3], TRIANGLE, [(3, 1, 2)])
        self.assertEqual(self.repo.get_revision(ref).complex.faces, ())
        self.assertEqual(self.repo.save_network('north', 'reported', [3, 2, 1], reversed(TRIANGLE), []), ref)
        with self.assertRaises(UnknownRevision):
            self.repo.get_revision(RevisionRef('north', 'reported', '0' * 64))

    def test_missing_face_boundary(self):
        valid = self.repo.save_network('north', 1, [1, 2, 3], TRIANGLE, [(1, 2, 3)])
        previous = self.repo.get_revision(valid)
        with self.assertRaisesRegex(InvalidComplex, 'boundary edge'):
            self.repo.save_network('north', 2, [1, 2, 3], TRIANGLE[:2], [(1, 2, 3)])
        with self.assertRaises(UnknownRevision):
            self.repo.get_revision(RevisionRef('north', 2, valid.digest))
        self.assertEqual(self.repo.get_revision(valid), previous)
        self.assertEqual(self.db.connection.execute('SELECT count(*) FROM revisions').fetchone()[0], 1)

    def test_degenerate_simplex_and_missing_identity(self):
        for vertices, edges, faces in (
            ([1, 2], [(1, 1)], []), ([1, 2], [(1, 3)], []), ([1, 2], [(1, 2)], [(1, 2, 2)]),
            ([True], [], []), (list(range(13)), [], []),
        ):
            with self.subTest(vertices=vertices, edges=edges, faces=faces):
                with self.assertRaises(InvalidComplex):
                    self.repo.save_network('north', 1, vertices, edges, faces)
        with self.assertRaises(InvalidComplex):
            self.repo.save_network('', 1, [], [], [])
        mixed = self.repo.save_network('north', 1, ['1', 1], [('1', 1)], [])
        self.assertEqual(self.repo.get_revision(mixed).complex.edges, ((1, '1'),))
