from dataclasses import dataclass

from network.canonical import identity_key, simplex_key
from network.model import NetworkComplex, RevisionRef


@dataclass(frozen=True)
class CommonSubcomplex:
    left: RevisionRef
    right: RevisionRef
    complex: NetworkComplex


def intersect_complexes(left, right):
    return NetworkComplex(
        tuple(sorted(set(left.vertices) & set(right.vertices), key=identity_key)),
        tuple(sorted(set(left.edges) & set(right.edges), key=simplex_key)),
        tuple(sorted(set(left.faces) & set(right.faces), key=simplex_key)),
    )


def adjacent_intersections(bindings):
    return tuple(CommonSubcomplex(left.revision.ref, right.revision.ref,
                                  intersect_complexes(left.revision.complex, right.revision.complex))
                 for left, right in zip(bindings, bindings[1:]))
