import hashlib
import json
from dataclasses import asdict

from network.model import InvalidComplex, NetworkComplex, RevisionRef, valid_identifier, valid_text


def identity_key(value):
    return (0, value) if type(value) is int else (1, value)


def simplex_key(simplex):
    return tuple(identity_key(vertex) for vertex in simplex)


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def content_digest(data):
    return hashlib.sha256(data).hexdigest()


def valid_digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def complex_data(complex_):
    return {
        'vertices': list(complex_.vertices),
        'edges': [list(edge) for edge in complex_.edges],
        'faces': [list(face) for face in complex_.faces],
    }


def canonical_complex_bytes(complex_):
    return canonical_json(complex_data(complex_))


def decode_complex(data):
    try:
        value = json.loads(data) if isinstance(data, (bytes, str)) else data
        if not isinstance(value, dict) or set(value) != {'vertices', 'edges', 'faces'}:
            raise InvalidComplex('expected vertices, edges and faces')
        if any(not isinstance(value[key], list) for key in value):
            raise InvalidComplex('complex members must be arrays')
        for key, size in (('edges', 2), ('faces', 3)):
            if any(not isinstance(row, list) or len(row) != size for row in value[key]):
                raise InvalidComplex(f'invalid {key} encoding')
        return NetworkComplex(tuple(value['vertices']), tuple(map(tuple, value['edges'])),
                              tuple(map(tuple, value['faces'])))
    except (json.JSONDecodeError, UnicodeError) as error:
        raise InvalidComplex('invalid complex encoding') from error


def complex_digest(complex_):
    return content_digest(canonical_complex_bytes(complex_))


def reference_data(ref):
    return asdict(ref)


def reference_from_data(value):
    if not isinstance(value, dict) or set(value) != {'network_id', 'revision', 'digest'}:
        raise ValueError('invalid revision reference')
    if not (valid_text(value['network_id']) and valid_identifier(value['revision'])
            and valid_digest(value['digest'])):
        raise ValueError('invalid revision reference')
    return RevisionRef(**value)
