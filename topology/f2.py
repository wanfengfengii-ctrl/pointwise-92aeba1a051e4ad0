def iter_bits(vector):
    while vector:
        low = vector & -vector
        yield low.bit_length() - 1
        vector ^= low


def apply_columns(columns, vector):
    result = 0
    for index in iter_bits(vector):
        result ^= columns[index]
    return result


class _ColumnBasis:
    def __init__(self):
        self.pivots = {}

    def reduce(self, vector):
        if type(vector) is not int or vector < 0:
            raise ValueError('F2 vectors are nonnegative integer masks')
        coefficients = 0
        while vector:
            pivot = vector.bit_length() - 1
            entry = self.pivots.get(pivot)
            if entry is None:
                break
            row, combination = entry
            vector ^= row
            coefficients ^= combination
        return vector, coefficients

    def add(self, vector, coordinates=0):
        residual, coefficients = self.reduce(vector)
        if not residual:
            return False
        self.pivots[residual.bit_length() - 1] = (residual, coefficients ^ coordinates)
        return True


def _checked_rows(rows, width):
    if type(width) is not int or width < 0:
        raise ValueError('invalid F2 matrix width')
    copied = list(rows)
    if any(type(row) is not int or row < 0 or row.bit_length() > width for row in copied):
        raise ValueError('row exceeds F2 matrix width')
    return copied


def _eliminate(rows, width, reverse):
    order = range(width - 1, -1, -1) if reverse else range(width)
    pivots = []
    for column in order:
        offset = len(pivots)
        mask = 1 << column
        chosen = next((i for i in range(offset, len(rows)) if rows[i] & mask), None)
        if chosen is None:
            continue
        rows[offset], rows[chosen] = rows[chosen], rows[offset]
        for index, row in enumerate(rows):
            if index != offset and row & mask:
                rows[index] ^= rows[offset]
        pivots.append(column)
    return tuple(pivots)


def rref(rows, width, *, reverse=False):
    reduced = _checked_rows(rows, width)
    pivots = _eliminate(reduced, width, reverse)
    return tuple(reduced[:len(pivots)]), pivots


def matrix_rank(vectors):
    basis = _ColumnBasis()
    for vector in vectors:
        basis.add(vector)
    return len(basis.pivots)


def kernel_basis(rows, width, *, reverse=False):
    reduced, pivots = rref(rows, width, reverse=reverse)
    free_columns = sorted(set(range(width)) - set(pivots))
    return tuple((1 << free) | sum(1 << pivot for row, pivot in zip(reduced, pivots) if row & (1 << free))
                 for free in free_columns)


def image_basis(columns):
    basis = _ColumnBasis()
    return tuple(column for column in columns if basis.add(column))


def solve_linear(rows, width, rhs, *, reverse=False):
    augmented = _checked_rows(rows, width)
    if type(rhs) is not int or rhs < 0 or rhs.bit_length() > len(augmented):
        raise ValueError('invalid F2 right-hand side')
    for index in iter_bits(rhs):
        augmented[index] |= 1 << width
    pivots = _eliminate(augmented, width, reverse)
    if any(augmented[len(pivots):]):
        return None
    return sum(1 << pivot for row, pivot in zip(augmented, pivots) if row & (1 << width))


def coordinates_in_basis(vector, basis_vectors):
    basis = _ColumnBasis()
    for index, column in enumerate(basis_vectors):
        if not basis.add(column, 1 << index):
            raise ValueError('dependent basis vectors')
    residual, coordinates = basis.reduce(vector)
    return None if residual else coordinates


def quotient_basis(generators, subspace):
    basis = _ColumnBasis()
    for vector in subspace:
        basis.add(vector)
    return tuple(vector for vector in generators if basis.add(vector))
