from collections.abc import Iterable, Mapping
from itertools import combinations

from network.canonical import identity_key, simplex_key
from network.model import InvalidComplex, NetworkComplex, valid_identifier, valid_text


MAX_VERTICES = 12


def validate_revision_identity(network_id, revision):
    if not valid_text(network_id) or not valid_identifier(revision):
        raise InvalidComplex('network and revision identities are required')


def _items(value, label):
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, Mapping)):
        raise InvalidComplex(f'{label} must be a collection')
    return tuple(value)


def _simplices(rows, size, vertices):
    result = set()
    for row in _items(rows, 'simplices'):
        members = _items(row, 'simplex')
        if len(members) != size or any(not valid_identifier(item) for item in members):
            raise InvalidComplex(f'expected a simplex with {size} sensor IDs')
        if len(set(members)) != size:
            raise InvalidComplex('degenerate simplex')
        if not vertices.issuperset(members):
            raise InvalidComplex('simplex references a missing vertex')
        result.add(tuple(sorted(members, key=identity_key)))
    return result


def validate_complex(vertices, edges, faces):
    supplied_vertices = _items(vertices, 'vertices')
    if any(not valid_identifier(vertex) for vertex in supplied_vertices):
        raise InvalidComplex('invalid sensor ID')
    vertex_set = set(supplied_vertices)
    if len(vertex_set) > MAX_VERTICES:
        raise InvalidComplex('at most 12 vertices per revision')
    edge_set = _simplices(edges, 2, vertex_set)
    face_set = _simplices(faces, 3, vertex_set)
    for face in face_set:
        if not edge_set.issuperset(combinations(face, 2)):
            raise InvalidComplex('triangle is missing a boundary edge')
    return NetworkComplex(tuple(sorted(vertex_set, key=identity_key)),
                          tuple(sorted(edge_set, key=simplex_key)),
                          tuple(sorted(face_set, key=simplex_key)))


def require_canonical_complex(complex_):
    normalized = validate_complex(complex_.vertices, complex_.edges, complex_.faces)
    if normalized != complex_:
        raise InvalidComplex('stored complex is not canonical')
    return normalized
