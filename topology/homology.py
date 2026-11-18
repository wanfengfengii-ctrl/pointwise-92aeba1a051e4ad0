from dataclasses import dataclass

from topology.chains import ChainComplex, build_chain_complex
from topology.f2 import apply_columns, coordinates_in_basis, image_basis, kernel_basis, quotient_basis


@dataclass(frozen=True)
class StaticSummary:
    components: int
    holes: int


@dataclass(frozen=True)
class HomologySpace:
    chain: ChainComplex
    boundaries: tuple[int, ...]
    representatives: tuple[int, ...]
    components: int


def compute_homology(complex_, *, reverse_pivots=False):
    chain = build_chain_complex(complex_)
    edge_count = len(complex_.edges)
    cycles = kernel_basis(chain.cycle_equations(), edge_count, reverse=reverse_pivots)
    boundaries = image_basis(chain.face_boundary)
    representatives = quotient_basis(cycles, boundaries)
    components = len(complex_.vertices) - (edge_count - len(cycles))
    return HomologySpace(chain, boundaries, representatives, components)


def cycle_coordinates(space, cycle):
    if type(cycle) is not int or cycle < 0 or cycle.bit_length() > len(space.chain.edge_boundary):
        raise ValueError('invalid edge-chain coordinates')
    if apply_columns(space.chain.edge_boundary, cycle):
        raise ValueError('edge chain is not a cycle')
    full_coordinates = coordinates_in_basis(cycle, space.boundaries + space.representatives)
    if full_coordinates is None:
        raise ValueError('cycle falls outside the declared homology space')
    return full_coordinates >> len(space.boundaries)


def static_summary(space):
    return StaticSummary(space.components, len(space.representatives))
