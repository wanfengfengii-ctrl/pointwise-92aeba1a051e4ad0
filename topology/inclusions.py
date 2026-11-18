from dataclasses import asdict, dataclass

from network.canonical import valid_digest
from study.timeline import position_sources, timeline_arrows, validate_position_sources
from topology.chains import inclusion_chain_map
from topology.f2 import apply_columns
from topology.homology import StaticSummary, compute_homology, cycle_coordinates, static_summary


class AnalysisError(ValueError):
    pass


@dataclass(frozen=True)
class InducedMap:
    source: int
    target: int
    source_dim: int
    target_dim: int
    columns: tuple[int, ...]


@dataclass(frozen=True)
class FrozenAnalysis:
    study_id: str
    positions: list[dict]
    summaries: tuple[StaticSummary, ...]
    maps: tuple[InducedMap, ...]

    @property
    def dimensions(self):
        return tuple(summary.holes for summary in self.summaries)

    def to_payload(self):
        return {'study_id': self.study_id, 'positions': self.positions,
                'summaries': [asdict(summary) for summary in self.summaries],
                'maps': [dict(asdict(arrow), columns=list(arrow.columns)) for arrow in self.maps]}


def build_induced_map(source_index, target_index, source, target):
    _, transport, _ = inclusion_chain_map(source.chain, target.chain)
    for boundary in source.boundaries:
        if cycle_coordinates(target, apply_columns(transport, boundary)) != 0:
            raise AnalysisError('inclusion does not preserve boundaries')
    columns = tuple(cycle_coordinates(target, apply_columns(transport, cycle))
                    for cycle in source.representatives)
    return InducedMap(source_index, target_index, len(source.representatives), len(target.representatives), columns)


def validate_analysis_relations(payload):
    if not isinstance(payload, dict) or set(payload) != {'study_id', 'positions', 'summaries', 'maps'}:
        raise AnalysisError('incomplete frozen analysis')
    study_id = payload['study_id']
    if not isinstance(study_id, str) or not study_id.startswith('study:') or not valid_digest(study_id[6:]):
        raise AnalysisError('invalid frozen study identity')
    positions = payload['positions']
    try:
        validate_position_sources(positions)
    except ValueError as error:
        raise AnalysisError('invalid frozen position sources') from error
    metrics = payload['summaries']
    if not isinstance(metrics, list) or len(metrics) != len(positions):
        raise AnalysisError('position summaries are incomplete')
    summaries = []
    for item in metrics:
        if not isinstance(item, dict) or set(item) != {'components', 'holes'}:
            raise AnalysisError('invalid position summary')
        if (type(item['components']) is not int or not 0 <= item['components'] <= 12
                or type(item['holes']) is not int or not 0 <= item['holes'] <= 55):
            raise AnalysisError('invalid position dimensions')
        summaries.append(StaticSummary(**item))
    expected = timeline_arrows(len(positions))
    relation_rows = payload['maps']
    if not isinstance(relation_rows, list) or len(relation_rows) != len(expected):
        raise AnalysisError('incomplete frozen maps')
    maps = []
    for item, arrow in zip(relation_rows, expected):
        fields = ('source', 'target', 'source_dim', 'target_dim')
        if not isinstance(item, dict) or set(item) != {*fields, 'columns'}:
            raise AnalysisError('invalid map fields')
        if any(type(item[key]) is not int for key in fields):
            raise AnalysisError('invalid map positions or dimensions')
        if (item['source'], item['target']) != (arrow.source, arrow.target):
            raise AnalysisError('map endpoints or direction mismatch')
        source_dim = summaries[arrow.source].holes
        target_dim = summaries[arrow.target].holes
        if (item['source_dim'], item['target_dim']) != (source_dim, target_dim):
            raise AnalysisError('map dimensions disagree with position summaries')
        columns = item['columns']
        if (not isinstance(columns, list) or len(columns) != source_dim
                or any(type(column) is not int or column < 0 or column.bit_length() > target_dim for column in columns)):
            raise AnalysisError('map columns do not fit the declared dimensions')
        maps.append(InducedMap(arrow.source, arrow.target, source_dim, target_dim, tuple(columns)))
    return FrozenAnalysis(study_id, positions, tuple(summaries), tuple(maps))


class AnalysisService:
    def __init__(self, studies, artifacts):
        self.studies = studies
        self.artifacts = artifacts

    def analyze_study(self, study_id, request_id, *, reverse_pivots=False):
        existing = self.artifacts.find_receipt('analysis', request_id, study_id)
        if existing is not None:
            return existing
        study = self.studies.get_study(study_id)
        spaces = tuple(compute_homology(pos.complex, reverse_pivots=reverse_pivots) for pos in study.positions)
        analysis = FrozenAnalysis(study_id, position_sources(study.positions),
                                  tuple(static_summary(space) for space in spaces),
                                  tuple(build_induced_map(arrow.source, arrow.target, spaces[arrow.source], spaces[arrow.target])
                                        for arrow in study.arrows))
        payload = analysis.to_payload()
        validate_analysis_relations(payload)
        return self.artifacts.publish('analysis', request_id, study_id, payload)
