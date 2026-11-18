from quality.encoding import Interval
from topology.f2 import matrix_rank


def subdiagram_rank(dimensions, maps, first, last):
    sizes = dimensions[first:last + 1]
    if not all(sizes):
        return 0
    if first == last:
        return sizes[0]

    offsets = [0]
    for size in sizes:
        offsets.append(offsets[-1] + size)
    width = offsets[-1]
    constraints = [0] * width
    relations = []
    equation = 0
    for arrow in maps:
        if not (first <= arrow.source <= last and first <= arrow.target <= last):
            continue
        source_offset = offsets[arrow.source - first]
        target_offset = offsets[arrow.target - first]
        for index in range(arrow.target_dim):
            constraints[target_offset + index] ^= 1 << (equation + index)
        for index, column in enumerate(arrow.columns):
            source = source_offset + index
            constraints[source] ^= column << equation
            relations.append((1 << source) ^ (column << target_offset))
        equation += arrow.target_dim

    # C imposes arrow compatibility and G generates the colimit identifications.
    # On ker(C), projection to the first position followed by quotienting by
    # im(G) is the limit-to-colimit map. Eliminate the block matrix [G P; 0 C].
    block = [constraint << width for constraint in constraints]
    for index in range(sizes[0]):
        block[index] |= 1 << index
    return matrix_rank(relations + block) - matrix_rank(constraints) - matrix_rank(relations)


def decompose_intervals(dimensions, maps):
    count = len(dimensions)
    ranks = {(start, end): subdiagram_rank(dimensions, maps, start, end)
             for start in range(count) for end in range(start, count)}
    intervals = []
    # A subdiagram rank counts interval summands covering the entire window.
    # Take the difference at both ends to count summands with exact endpoints.
    for (start, end), rank in ranks.items():
        multiplicity = (rank - ranks.get((start - 1, end), 0) - ranks.get((start, end + 1), 0)
                        + ranks.get((start - 1, end + 1), 0))
        if multiplicity < 0:
            raise ValueError('negative interval multiplicity')
        if multiplicity:
            intervals.append(Interval(start, end, multiplicity))
    return tuple(intervals)


def reconstruct_dimensions(intervals, position_count):
    changes = [0] * (position_count + 1)
    for interval in intervals:
        changes[interval.start] += interval.multiplicity
        changes[interval.end + 1] -= interval.multiplicity
    dimension = 0
    dimensions = []
    for change in changes[:-1]:
        dimension += change
        dimensions.append(dimension)
    return tuple(dimensions)
