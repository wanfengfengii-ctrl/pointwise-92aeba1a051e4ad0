from dataclasses import dataclass
from itertools import combinations

from network.model import NetworkComplex
from topology.f2 import apply_columns, iter_bits


@dataclass(frozen=True)
class ChainComplex:
    complex: NetworkComplex
    edge_boundary: tuple[int, ...]
    face_boundary: tuple[int, ...]

    def cycle_equations(self):
        rows = [0] * len(self.complex.vertices)
        for edge_index, column in enumerate(self.edge_boundary):
            for vertex_index in iter_bits(column):
                rows[vertex_index] |= 1 << edge_index
        return tuple(rows)


def build_chain_complex(complex_):
    vertices = {vertex: index for index, vertex in enumerate(complex_.vertices)}
    edges = {edge: index for index, edge in enumerate(complex_.edges)}
    chain = ChainComplex(complex_,
                         tuple((1 << vertices[a]) ^ (1 << vertices[b]) for a, b in complex_.edges),
                         tuple(sum(1 << edges[edge] for edge in combinations(face, 2)) for face in complex_.faces))
    if not boundary_squared_is_zero(chain):
        raise ValueError('edge and face boundaries do not compose to zero')
    return chain


def boundary_squared_is_zero(chain):
    return all(apply_columns(chain.edge_boundary, face) == 0 for face in chain.face_boundary)


def inclusion_chain_map(source, target):
    domain = (source.complex.vertices, source.complex.edges, source.complex.faces)
    codomain = (target.complex.vertices, target.complex.edges, target.complex.faces)
    transport = []
    for source_order, target_order in zip(domain, codomain):
        indexes = {identity: index for index, identity in enumerate(target_order)}
        try:
            transport.append(tuple(1 << indexes[identity] for identity in source_order))
        except KeyError as error:
            raise ValueError('expected inclusion of source simplices in target') from error
    return tuple(transport)
