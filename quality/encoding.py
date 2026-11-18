from collections import Counter
from dataclasses import dataclass

from network.canonical import canonical_json, valid_digest
from study.timeline import validate_position_sources


@dataclass(frozen=True, order=True)
class Interval:
    start: int
    end: int
    multiplicity: int = 1


@dataclass(frozen=True)
class QualityReport:
    analysis_id: str
    positions: list[dict]
    intervals: tuple[Interval, ...]


def canonical_intervals(intervals, position_count):
    counts = Counter()
    for interval in intervals:
        start, end, multiplicity = interval.start, interval.end, interval.multiplicity
        if type(start) is not int or type(end) is not int or not 0 <= start <= end < position_count:
            raise ValueError('interval endpoints fall outside the timeline')
        if type(multiplicity) is not int or multiplicity <= 0:
            raise ValueError('interval multiplicity must be a positive integer')
        counts[start, end] += multiplicity
    return tuple(Interval(a, b, counts[a, b]) for a, b in sorted(counts))


def _interval_data(intervals):
    return [[item.start, item.end, item.multiplicity] for item in intervals]


def _check_analysis_id(value):
    if not isinstance(value, str) or not value.startswith('analysis:') or not valid_digest(value[9:]):
        raise ValueError('invalid report analysis identity')


def encode_report(report):
    _check_analysis_id(report.analysis_id)
    validate_position_sources(report.positions)
    intervals = canonical_intervals(report.intervals, len(report.positions))
    return {'analysis_id': report.analysis_id, 'positions': report.positions,
            'intervals': _interval_data(intervals)}


def decode_report(payload):
    if not isinstance(payload, dict) or set(payload) != {'analysis_id', 'positions', 'intervals'}:
        raise ValueError('invalid report fields')
    rows = payload['intervals']
    if not isinstance(rows, list) or any(not isinstance(row, list) or len(row) != 3 for row in rows):
        raise ValueError('invalid report interval encoding')
    report = QualityReport(payload['analysis_id'], payload['positions'], tuple(Interval(*row) for row in rows))
    if canonical_json(encode_report(report)) != canonical_json(payload):
        raise ValueError('report intervals are not canonical')
    return report
