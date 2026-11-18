from dataclasses import dataclass


Identifier = int | str


class InvalidComplex(ValueError):
    pass


class RevisionConflict(ValueError):
    pass


class UnknownRevision(LookupError):
    pass


def valid_text(value):
    return (isinstance(value, str) and bool(value.strip())
            and all(not 0xD800 <= ord(char) <= 0xDFFF for char in value))


def valid_identifier(value):
    return type(value) is int or valid_text(value)


@dataclass(frozen=True)
class RevisionRef:
    network_id: str
    revision: Identifier
    digest: str


@dataclass(frozen=True)
class NetworkComplex:
    vertices: tuple[Identifier, ...]
    edges: tuple[tuple[Identifier, Identifier], ...]
    faces: tuple[tuple[Identifier, Identifier, Identifier], ...]


@dataclass(frozen=True)
class NetworkRevision:
    ref: RevisionRef
    complex: NetworkComplex
