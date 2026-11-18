from dataclasses import dataclass

from network.canonical import complex_data, decode_complex, reference_data, reference_from_data
from network.model import NetworkComplex, RevisionRef
from network.validation import require_canonical_complex
from study.bindings import validate_sample_order


@dataclass(frozen=True)
class ExpandedPosition:
    index: int
    kind: str
    time: int | float | str | None
    refs: tuple[RevisionRef, ...]
    complex: NetworkComplex


@dataclass(frozen=True)
class TimelineArrow:
    source: int
    target: int


def timeline_arrows(size):
    return tuple(TimelineArrow(source, target)
                 for source in range(1, size, 2) for target in (source - 1, source + 1))


def build_timeline(bindings, intersections):
    positions = []
    for index, binding in enumerate(bindings):
        revision = binding.revision
        positions.append(ExpandedPosition(2 * index, 'sample', binding.time, (revision.ref,), revision.complex))
        if index < len(intersections):
            common = intersections[index]
            positions.append(ExpandedPosition(2 * index + 1, 'intersection', None,
                                              (common.left, common.right), common.complex))
    return tuple(positions), timeline_arrows(len(positions))


def _source(position):
    return {'index': position.index, 'kind': position.kind, 'time': position.time,
            'refs': [reference_data(ref) for ref in position.refs]}


def position_sources(positions):
    return [_source(position) for position in positions]


def encode_positions(positions):
    return [dict(_source(position), complex=complex_data(position.complex)) for position in positions]


def validate_position_sources(rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 31 or len(rows) % 2 != 1:
        raise ValueError('expected an odd, nonempty timeline')
    references = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {'index', 'kind', 'time', 'refs'}:
            raise ValueError('invalid position source fields')
        if type(row['index']) is not int or row['index'] != index:
            raise ValueError('position index mismatch')
        common = index % 2 == 1
        if row['kind'] != ('intersection' if common else 'sample') or (common and row['time'] is not None):
            raise ValueError('invalid position kind or time')
        if not isinstance(row['refs'], list) or len(row['refs']) != (2 if common else 1):
            raise ValueError('invalid position references')
        references.append(tuple(reference_from_data(value) for value in row['refs']))
    validate_sample_order(row['time'] for row in rows[::2])
    for index in range(1, len(rows), 2):
        if references[index] != references[index - 1] + references[index + 1]:
            raise ValueError('intersection source does not match adjacent samples')
    return tuple(references)


def decode_positions(rows):
    if not isinstance(rows, list) or any(not isinstance(row, dict) or 'complex' not in row for row in rows):
        raise ValueError('missing frozen position complexes')
    sources = [{key: value for key, value in row.items() if key != 'complex'} for row in rows]
    references = validate_position_sources(sources)
    return tuple(ExpandedPosition(row['index'], row['kind'], row['time'], refs,
                                  require_canonical_complex(decode_complex(row['complex'])))
                 for row, refs in zip(rows, references))
