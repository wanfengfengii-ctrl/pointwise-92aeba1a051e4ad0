import unittest

from delivery.analysis_store import ArtifactStore
from delivery.database import ArchiveDatabase
from network.revisions import RevisionRepository
from network.validation import validate_complex
from study.cohorts import StudyService
from topology.chains import boundary_squared_is_zero, build_chain_complex
from topology.f2 import coordinates_in_basis, kernel_basis, rref, solve_linear
from topology.homology import compute_homology, cycle_coordinates, static_summary
from topology.inclusions import AnalysisService


class TopologyTests(unittest.TestCase):
    def test_tree_boundary_and_filled_triangle(self):
        with ArchiveDatabase.open(':memory:') as db:
            repo, studies = RevisionRepository(db), StudyService(db)
            analyzer = AnalysisService(studies, ArtifactStore(db))
            triangle = [(1, 2), (2, 3), (3, 1)]
            for index, (edges, faces, holes) in enumerate((
                (triangle[:2], [], 0), (triangle, [], 1), (triangle, [(1, 2, 3)], 0),
            )):
                with self.subTest(case=index):
                    original = repo.save_network('front', index, [1, 2, 3], edges, faces)
                    permuted = repo.save_network('front', index, [3, 1, 2],
                                                 [edge[::-1] for edge in reversed(edges)], [face[::-1] for face in faces])
                    self.assertEqual(original, permuted)
                    study = studies.freeze_study(f's{index}', [(0, original)])
                    normal = analyzer.analyze_study(study.study_id, f'a{index}')
                    reversed_ = analyzer.analyze_study(study.study_id, f'r{index}', reverse_pivots=True)
                    expected = [{'components': 1, 'holes': holes}]
                    self.assertEqual(normal.payload['summaries'], expected)
                    self.assertEqual(reversed_.payload['summaries'], expected)

    def test_empty_isolated_and_boundary_quotient(self):
        empty = static_summary(compute_homology(validate_complex([], [], [])))
        self.assertEqual((empty.components, empty.holes), (0, 0))
        full = validate_complex([1, 2, 3, 4], [(1, 2), (2, 3), (1, 3)], [(1, 2, 3)])
        chain = build_chain_complex(full)
        self.assertTrue(boundary_squared_is_zero(chain))
        self.assertEqual(chain.face_boundary, (0b111,))
        homology = compute_homology(full)
        self.assertEqual((static_summary(homology).components, static_summary(homology).holes), (2, 0))
        self.assertEqual(cycle_coordinates(homology, 0b111), 0)

    def test_f2_zero_shapes_and_pivots(self):
        self.assertEqual(rref([], 0), ((), ()))
        self.assertEqual(kernel_basis([], 3), (1, 2, 4))
        self.assertIsNone(solve_linear([0], 0, 1))
        self.assertEqual(solve_linear([0b11], 2, 1), 0b01)
        self.assertEqual(solve_linear([0b11], 2, 1, reverse=True), 0b10)
        self.assertEqual(coordinates_in_basis(0b101, [0b110, 0b011]), 0b11)
        self.assertIsNone(coordinates_in_basis(0b001, [0b110, 0b011]))
