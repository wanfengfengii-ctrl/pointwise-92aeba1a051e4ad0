import itertools
import json
import unittest
from dataclasses import replace

from delivery.analysis_store import ArtifactStore
from delivery.database import ArchiveDatabase
from network.revisions import RevisionRepository
from network.validation import validate_complex
from quality.decomposition import subdiagram_rank
from quality.lifetimes import InvalidAnalysis
from quality.reports import ReportService
from study.cohorts import StudyService
from topology.f2 import matrix_rank
from topology.homology import compute_homology
from topology.inclusions import AnalysisService, build_induced_map, validate_analysis_relations


A = [(1, 2), (2, 3), (1, 3)]
B = [(1, 2), (2, 4), (1, 4)]


def path(middle):
    return [(1, middle), (middle, 4)]


def chain_group(complex_):
    # Explicitly enumerate chains and cosets using stable edge identities.
    edges = complex_.edges
    cycles = []
    for size in range(len(edges) + 1):
        for chosen in itertools.combinations(edges, size):
            odd = set()
            for edge in chosen:
                odd.symmetric_difference_update(edge)
            if not odd:
                cycles.append(frozenset(chosen))
    boundaries = {frozenset()}
    for face in complex_.faces:
        rim = frozenset(itertools.combinations(face, 2))
        boundaries |= {boundary ^ rim for boundary in boundaries}
    return {cycle: frozenset(cycle ^ boundary for boundary in boundaries) for cycle in cycles}


def brute_subdiagram_ranks(study):
    groups = [chain_group(pos.complex) for pos in study.positions]
    elements = [list(set(group.values())) for group in groups]
    zero = [group[frozenset()] for group in groups]
    ranks = {}
    for first in range(len(groups)):
        for last in range(first, len(groups)):
            nodes = range(first, last + 1)
            arrows = [(a.source, a.target) for a in study.arrows if a.source in nodes and a.target in nodes]

            def push(source_class, target):
                return groups[target][next(iter(source_class))]

            def add(left, right):
                return tuple(groups[node][next(iter(x)) ^ next(iter(y))]
                             for node, x, y in zip(nodes, left, right))

            zero_window = tuple(zero[first:last + 1])
            relation_span = {zero_window}
            for source, target in arrows:
                for element in elements[source]:
                    relation = list(zero_window)
                    relation[source - first] = element
                    relation[target - first] = push(element, target)
                    relation_span |= {add(vector, relation) for vector in relation_span}
            classes = set()
            for values in itertools.product(*(elements[node] for node in nodes)):
                if all(push(values[source - first], target) == values[target - first] for source, target in arrows):
                    projected = (values[0], *zero_window[1:])
                    classes.add(frozenset(add(projected, relation) for relation in relation_span))
            ranks[first, last] = len(classes).bit_length() - 1
    return ranks


class LifetimeTests(unittest.TestCase):
    def setUp(self):
        self.db = ArchiveDatabase.open(':memory:')
        self.addCleanup(self.db.close)
        self.repo, self.studies = RevisionRepository(self.db), StudyService(self.db)
        self.store = ArtifactStore(self.db)
        self.analyzer = AnalysisService(self.studies, self.store)
        self.reports = ReportService(self.store)

    def run_fixture(self, name, networks, *, alternate=False):
        refs = [self.repo.save_network(name, index, vertices, edges, faces)
                for index, (vertices, edges, faces) in enumerate(networks)]
        study = self.studies.freeze_study(name, list(enumerate(refs)))
        analysis = self.analyzer.analyze_study(study.study_id, name, reverse_pivots=alternate)
        report = self.reports.create_report(analysis.artifact_id, name)
        return study, analysis, report

    def test_replaced_hole_and_common_cycle(self):
        networks = [([1, 2, 3, 4], A, []), ([1, 2, 3, 4], B, [])]
        study, analysis, report = self.run_fixture('replacement', networks)
        actual_dims = [item['holes'] for item in analysis.payload['summaries']]
        actual_intervals = report.payload['intervals']
        self.assertEqual(study.positions[1].complex.edges, ((1, 2),))
        self.assertEqual(actual_dims, [1, 0, 1])
        self.assertEqual(actual_intervals, [[0, 0, 1], [2, 2, 1]], 'HOLE_IDENTITY_DRIFT')
        theta = [(list(range(1, 7)), path(2) + path(3) + path(5), []),
                 (list(range(1, 7)), path(2) + path(3) + path(6), [])]
        _, analysis2, report2 = self.run_fixture('common', theta)
        self.assertEqual([item['holes'] for item in analysis2.payload['summaries']], [2, 1, 2])
        self.assertEqual(report2.payload['intervals'], [[0, 0, 1], [0, 2, 1], [2, 2, 1]])
        self.assertTrue(all(matrix_rank(arrow['columns']) == 1 for arrow in analysis2.payload['maps']))
        event = {'case_id': 'v5', 'input': networks, 'expected': [1, 0, 1], 'actual': actual_dims,
                 'downstream_expected': [[0, 0, 1], [2, 2, 1]], 'downstream_actual': actual_intervals,
                 'code_paths': ['study/intersections.py', 'topology/inclusions.py', 'quality/decomposition.py', 'quality/reports.py'],
                 'oracle': 'Two different triangle rims share only edge (1,2), which has no cycle.'}
        print('POINTWISE_SCENARIO ' + json.dumps(event, sort_keys=True, separators=(',', ':')))

    def test_fill_remove_and_intersection_only(self):
        _, analysis, report = self.run_fixture('fill', [([1, 2, 3], A, faces)
                                                        for faces in ([], [(1, 2, 3)], [])])
        self.assertEqual([item['holes'] for item in analysis.payload['summaries']], [1, 1, 0, 1, 1])
        self.assertEqual(report.payload['intervals'], [[0, 1, 1], [3, 4, 1]])
        fans = [([1, 2, 3, apex], A + [(vertex, apex) for vertex in (1, 2, 3)],
                 [(a, b, apex) for a, b in A]) for apex in (4, 5)]
        _, analysis, report = self.run_fixture('fans', fans)
        self.assertEqual([item['holes'] for item in analysis.payload['summaries']], [0, 1, 0])
        self.assertEqual(report.payload['intervals'], [[1, 1, 1]])

    def test_basis_transport_and_input_permutation(self):
        vertices = list(range(1, 7))
        left = path(2) + path(3) + path(5)
        right = path(2) + path(3) + path(6)
        _, _, baseline = self.run_fixture('ordinary', [(vertices, left, []), (vertices, right, [])])
        _, _, alternate = self.run_fixture('alternate', [(vertices[::-1], [edge[::-1] for edge in left[::-1]], []),
                                                         (vertices[::-1], right[::-1], [])], alternate=True)
        self.assertEqual(alternate.payload['intervals'], baseline.payload['intervals'])
        space = compute_homology(validate_complex(vertices, left, []))
        common = compute_homology(validate_complex(vertices, path(2) + path(3), []))
        common_edges = {tuple(sorted(edge)) for edge in path(2) + path(3)}
        shared_cycle = sum(1 << index for index, edge in enumerate(space.chain.complex.edges) if edge in common_edges)
        other = next(cycle for cycle in space.representatives if cycle != shared_cycle)
        changed = replace(space, representatives=(shared_cycle ^ other, other))
        self.assertEqual(build_induced_map(1, 0, common, changed).columns, (0b11,))

    def test_full_diagram_audit(self):
        other = [(4, 5), (5, 6), (4, 6)]
        vertices = list(range(1, 7))
        scenarios = (
            ('different', [A, A + other, other], [[0, 2, 1], [2, 4, 1]]),
            ('same', [A, A + other, A], [[0, 4, 1], [2, 2, 1]]),
            ('repeated', [A + other] * 3, [[0, 4, 2]]),
        )
        for name, edge_lists, expected in scenarios:
            with self.subTest(name=name):
                study, fixed, report = self.run_fixture(name, [(vertices, edges, []) for edges in edge_lists])
                self.assertEqual(report.payload['intervals'], expected)
                analysis = validate_analysis_relations(fixed.payload)
                ranks = brute_subdiagram_ranks(study)
                for (start, end), rank in ranks.items():
                    self.assertEqual(subdiagram_rank(analysis.dimensions, analysis.maps, start, end), rank)
                    represented = sum(count for a, b, count in report.payload['intervals'] if a <= start <= end <= b)
                    self.assertEqual(represented, rank)

    def test_empty_report_and_incomplete_analysis_rejected(self):
        study, analysis, report = self.run_fixture('empty', [([], [], []), ([1], [], [])])
        self.assertEqual(report.payload['intervals'], [])
        damaged = dict(analysis.payload)
        del damaged['maps']
        incomplete = self.store.publish('analysis', 'incomplete', study.study_id, damaged)
        with self.assertRaises(InvalidAnalysis):
            self.reports.create_report(incomplete.artifact_id, 'incomplete')
        self.assertIsNone(self.store.find_receipt('report', 'incomplete'))
