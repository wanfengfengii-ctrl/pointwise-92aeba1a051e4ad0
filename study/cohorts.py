import json
from dataclasses import asdict, dataclass

from delivery.transactions import TransactionManager
from network.canonical import canonical_json, complex_digest, content_digest, reference_from_data, reference_data
from network.model import NetworkRevision, valid_text
from network.revisions import RevisionRepository
from study.bindings import SampleBinding, bind_revisions, binding_fingerprint, sample_request
from study.intersections import adjacent_intersections
from study.timeline import ExpandedPosition, TimelineArrow, build_timeline, decode_positions, encode_positions, timeline_arrows


class InvalidStudy(ValueError):
    pass


class StudyConflict(ValueError):
    pass


class UnknownStudy(LookupError):
    pass


@dataclass(frozen=True)
class FrozenStudy:
    study_id: str
    request_id: str
    samples: tuple[SampleBinding, ...]
    positions: tuple[ExpandedPosition, ...]
    arrows: tuple[TimelineArrow, ...]

    def payload(self):
        return {'request_id': self.request_id,
                'fingerprint': binding_fingerprint((sample.time, sample.revision.ref) for sample in self.samples),
                'positions': encode_positions(self.positions),
                'arrows': [asdict(arrow) for arrow in self.arrows]}


def study_identity(raw):
    return 'study:' + content_digest(raw)


def decode_frozen_study(study_id, payload):
    if not isinstance(payload, dict) or set(payload) != {'request_id', 'fingerprint', 'positions', 'arrows'}:
        raise InvalidStudy('invalid frozen study fields')
    if study_identity(canonical_json(payload)) != study_id or not valid_text(payload['request_id']):
        raise InvalidStudy('frozen study identity mismatch')
    try:
        positions = decode_positions(payload['positions'])
    except ValueError as error:
        raise InvalidStudy('invalid frozen study positions') from error
    arrows = timeline_arrows(len(positions))
    if canonical_json(payload['arrows']) != canonical_json([asdict(arrow) for arrow in arrows]):
        raise InvalidStudy('frozen study arrow mismatch')
    samples = tuple(SampleBinding(pos.time, NetworkRevision(pos.refs[0], pos.complex)) for pos in positions[::2])
    if any(complex_digest(sample.revision.complex) != sample.revision.ref.digest for sample in samples):
        raise InvalidStudy('frozen revision digest mismatch')
    if binding_fingerprint((sample.time, sample.revision.ref) for sample in samples) != payload['fingerprint']:
        raise InvalidStudy('frozen binding fingerprint mismatch')
    return FrozenStudy(study_id, payload['request_id'], samples, positions, arrows)


class StudyService:
    def __init__(self, database):
        self.database = database
        self.revisions = RevisionRepository(database)
        self.transactions = TransactionManager(database)

    def freeze_study(self, request_id, samples):
        if not valid_text(request_id):
            raise InvalidStudy('study request identity is required')
        try:
            pairs = sample_request(samples)
            for _, ref in pairs:
                reference_from_data(reference_data(ref))
            fingerprint = binding_fingerprint(pairs)
        except ValueError as error:
            raise InvalidStudy(str(error)) from error
        with self.transactions.atomic('study') as conn:
            previous = conn.execute(
                '''SELECT s.id, s.fingerprint, s.body FROM study_receipts r
                   JOIN studies s ON s.id = r.study_id WHERE r.request_id=?''', (request_id,)).fetchone()
            if previous is not None:
                if previous['fingerprint'] != fingerprint:
                    raise StudyConflict(request_id)
                return decode_frozen_study(previous['id'], json.loads(previous['body']))
            bindings = bind_revisions(self.revisions, pairs)
            positions, arrows = build_timeline(bindings, adjacent_intersections(bindings))
            frozen = FrozenStudy('', request_id, bindings, positions, arrows)
            body = canonical_json(frozen.payload())
            study_id = study_identity(body)
            existing = conn.execute('SELECT body FROM studies WHERE id=?', (study_id,)).fetchone()
            if existing is None:
                conn.execute('INSERT INTO studies VALUES (?, ?, ?, ?)', (study_id, request_id, fingerprint, body))
            conn.execute('INSERT INTO study_receipts VALUES (?, ?)', (request_id, study_id))
        return FrozenStudy(study_id, request_id, bindings, positions, arrows)

    def get_study(self, study_id):
        row = self.database.connection.execute('SELECT body FROM studies WHERE id=?', (study_id,)).fetchone()
        if row is None:
            raise UnknownStudy(study_id)
        return decode_frozen_study(study_id, json.loads(row['body']))
