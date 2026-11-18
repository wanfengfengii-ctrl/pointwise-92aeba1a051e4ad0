import json
import tempfile
from pathlib import Path

from delivery.analysis_store import ArtifactStore
from delivery.database import ArchiveDatabase
from exchange.export import export_report
from exchange.import_check import verify_package
from network.revisions import RevisionRepository
from quality.reports import ReportService
from study.cohorts import StudyService
from topology.inclusions import AnalysisService


def main():
    left_edges = [(1, 2), (2, 3), (1, 3)]
    right_edges = [(1, 2), (2, 4), (1, 4)]
    expected = [[0, 0, 1], [2, 2, 1]]
    with tempfile.TemporaryDirectory(prefix='chengchuan-') as directory:
        root = Path(directory)
        archive = root / 'morning.sqlite'
        delivery = root / 'crew'
        delivery.mkdir()
        with ArchiveDatabase.open(archive) as db:
            revisions = RevisionRepository(db)
            left = revisions.save_network('north', 1, [1, 2, 3, 4], left_edges, [])
            right = revisions.save_network('north', 2, [1, 2, 3, 4], right_edges, [])
            studies = StudyService(db)
            study = studies.freeze_study('morning-selection', [(900, left), (930, right)])
            store = ArtifactStore(db)
            analysis = AnalysisService(studies, store).analyze_study(study.study_id, 'morning-review')
            report = ReportService(store).create_report(analysis.artifact_id, 'morning-crew')
            dimensions = [entry['holes'] for entry in analysis.payload['summaries']]
            actual = report.payload['intervals']
            if dimensions != [1, 0, 1] or actual != expected:
                raise AssertionError('two triangle rims with one shared edge require two single-position lifetimes')
            revisions.save_network('north', 3, [1, 2, 3, 4], right_edges, [(1, 2, 4)])
        with ArchiveDatabase.open(archive) as db:
            store = ArtifactStore(db)
            if store.read_artifact(report.artifact_id) != report:
                raise AssertionError('reopened report differs from its published value')
            package = export_report(store, report.artifact_id, delivery / 'quality.zip')
        archive.unlink()
        checked = verify_package(package)
        downstream = [[item.start, item.end, item.multiplicity] for item in checked.report.intervals]
        if downstream != expected or checked.report_id != report.artifact_id:
            raise AssertionError('offline report disagrees with the verified fixed result')
        print('展开位置孔洞数', dimensions)
        print('补测报告区间及重数', downstream)
        print('离线来源修订', [[ref['revision'] for ref in pos['refs']] for pos in checked.sources])
        event = {'case_id': 'v8', 'input': {'vertices': [1, 2, 3, 4], 'edges': [left_edges, right_edges],
                                         'faces': [[], []], 'sample_times': [900, 930]},
                 'expected': expected, 'actual': actual, 'downstream_expected': expected, 'downstream_actual': downstream,
                 'oracle': 'Each triangle contributes one cycle and their single common edge has no cycle.',
                 'code_paths': ['topology/inclusions.py', 'quality/reports.py', 'exchange/export.py', 'exchange/import_check.py']}
        print('POINTWISE_SCENARIO ' + json.dumps(event, sort_keys=True, separators=(',', ':')))
        demonstrate_acceptance(root / 'intake')


def demonstrate_acceptance(root):
    """Two sources deliver under the same request name; A's follow-up shares parents."""
    from intake_examples import acceptance_scenario

    scenario = acceptance_scenario(root)
    receipts = scenario['accepted']
    if receipts['A/morning']['report_id'] == receipts['B/morning']['report_id']:
        raise AssertionError('same-named reports from different sources collapsed')
    if receipts['A/morning']['analysis_id'] != receipts['A/followup']['analysis_id']:
        raise AssertionError('follow-up delivery lost its shared parent')
    if scenario['reverified']['local'] != scenario['reverified']['original']:
        raise AssertionError('reissued local report does not address the accepted chain')
    print('异源同名回执', {key: value['report_id'] for key, value in receipts.items()})
    print('共享父项', scenario['shared'])
    print('冲突拒绝', sorted(scenario['rejected']))
    print('重开后本地重出', scenario['local_report'])
    print('再导出核验', scenario['reverified'])
    event = {'case_id': 'v9', 'sources': sorted({value['source_id'] for value in receipts.values()}),
             'same_report_request': receipts['A/morning']['report_request_id'],
             'shared_parents': scenario['shared'], 'local_report': scenario['local_report'],
             'reverified': scenario['reverified'], 'rejected': sorted(scenario['rejected']),
             'code_paths': ['exchange/import_check.py', 'delivery/analysis_store.py', 'exchange/export.py',
                            'quality/reports.py']}
    print('POINTWISE_SCENARIO ' + json.dumps(event, sort_keys=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
