from network.canonical import canonical_complex_bytes, canonical_json, complex_digest, decode_complex
from network.model import NetworkRevision, RevisionConflict, RevisionRef, UnknownRevision
from network.validation import require_canonical_complex, validate_complex, validate_revision_identity
from delivery.transactions import TransactionManager


class RevisionRepository:
    def __init__(self, database):
        self.database = database
        self.transactions = TransactionManager(database)

    def save_network(self, network_id, revision, vertices, edges, faces):
        validate_revision_identity(network_id, revision)
        complex_ = validate_complex(vertices, edges, faces)
        raw = canonical_complex_bytes(complex_)
        digest = complex_digest(complex_)
        key = (network_id, canonical_json(revision).decode('ascii'))
        with self.transactions.atomic('revision') as conn:
            previous = conn.execute('SELECT digest, body FROM revisions WHERE network_id=? AND revision=?', key).fetchone()
            if previous is None:
                conn.execute('INSERT INTO revisions VALUES (?, ?, ?, ?)', (*key, digest, raw))
            elif (previous['digest'], previous['body']) != (digest, raw):
                raise RevisionConflict(f'conflicting content for {network_id!r} revision {revision!r}')
        return RevisionRef(network_id, revision, digest)

    def get_revision(self, ref):
        if not isinstance(ref, RevisionRef):
            raise UnknownRevision('expected a revision reference')
        validate_revision_identity(ref.network_id, ref.revision)
        key = (ref.network_id, canonical_json(ref.revision).decode('ascii'))
        row = self.database.connection.execute(
            'SELECT digest, body FROM revisions WHERE network_id=? AND revision=?', key).fetchone()
        if row is None or row['digest'] != ref.digest:
            raise UnknownRevision(ref)
        complex_ = require_canonical_complex(decode_complex(row['body']))
        if complex_digest(complex_) != ref.digest:
            raise UnknownRevision('revision payload does not match its reference')
        return NetworkRevision(ref, complex_)
