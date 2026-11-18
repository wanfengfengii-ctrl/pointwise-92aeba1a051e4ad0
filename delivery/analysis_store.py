import json
from dataclasses import dataclass

from delivery.transactions import TransactionManager
from network.canonical import canonical_json, content_digest
from network.model import valid_text


class UnknownArtifact(LookupError):
    pass


class PublicationConflict(ValueError):
    pass


class ArtifactIntegrityError(ValueError):
    pass


@dataclass(frozen=True)
class PublishedArtifact:
    artifact_id: str
    kind: str
    request_id: str
    parent_id: str
    payload: dict

    @property
    def receipt(self):
        return self.kind, self.request_id, self.artifact_id

    def record(self):
        return {'id': self.artifact_id, 'kind': self.kind, 'request_id': self.request_id,
                'parent_id': self.parent_id, 'payload': self.payload}


def _identity(kind, request_id, parent_id, payload):
    return kind + ':' + content_digest(canonical_json({
        'kind': kind, 'request_id': request_id, 'parent_id': parent_id, 'payload': payload,
    }))


def decode_artifact_record(record):
    if not isinstance(record, dict) or set(record) != {'id', 'kind', 'request_id', 'parent_id', 'payload'}:
        raise ArtifactIntegrityError('invalid fixed artifact fields')
    kind, request, parent, payload = (record[key] for key in ('kind', 'request_id', 'parent_id', 'payload'))
    if kind not in ('analysis', 'report') or not valid_text(request) or not valid_text(parent) or not isinstance(payload, dict):
        raise ArtifactIntegrityError('invalid fixed artifact record')
    if record['id'] != _identity(kind, request, parent, payload):
        raise ArtifactIntegrityError('artifact identity does not match fixed content')
    return PublishedArtifact(record['id'], kind, request, parent, payload)


class ArtifactStore:
    def __init__(self, database, *, before_commit=None):
        self.database = database
        self.transactions = TransactionManager(database, before_commit=before_commit)

    def find_receipt(self, kind, request_id, parent_id=None):
        if kind not in ('analysis', 'report') or not valid_text(request_id):
            raise PublicationConflict('invalid publication request identity')
        row = self.database.connection.execute(
            'SELECT artifact_id FROM receipts WHERE kind=? AND request_id=?', (kind, request_id)).fetchone()
        if row is None:
            return None
        artifact = self.read_artifact(row['artifact_id'])
        if artifact.kind != kind or artifact.request_id != request_id:
            raise ArtifactIntegrityError('receipt does not match artifact')
        if parent_id is not None and artifact.parent_id != parent_id:
            raise PublicationConflict(f'{kind} request has a different fixed parent')
        return artifact

    def publish(self, kind, request_id, parent_id, payload):
        if kind not in ('analysis', 'report') or not valid_text(request_id) or not valid_text(parent_id):
            raise PublicationConflict('invalid publication request or parent identity')
        if not isinstance(payload, dict):
            raise ArtifactIntegrityError('artifact payload must be an object')
        body = canonical_json(payload)
        fixed = json.loads(body)
        artifact_id = _identity(kind, request_id, parent_id, fixed)
        with self.transactions.atomic(kind) as conn:
            existing = self.find_receipt(kind, request_id, parent_id)
            if existing is not None:
                if existing.artifact_id != artifact_id:
                    raise PublicationConflict(f'{kind} request has different fixed content')
                return existing
            if kind == 'analysis':
                if conn.execute('SELECT 1 FROM studies WHERE id=?', (parent_id,)).fetchone() is None:
                    raise UnknownArtifact(parent_id)
                parents = (parent_id, None)
            else:
                if self.read_artifact(parent_id).kind != 'analysis':
                    raise ArtifactIntegrityError('report parent must be an analysis')
                parents = (None, parent_id)
            conn.execute('INSERT INTO artifacts VALUES (?, ?, ?, ?, ?)', (artifact_id, kind, *parents, body))
            conn.execute('INSERT INTO receipts VALUES (?, ?, ?)', (kind, request_id, artifact_id))
        return PublishedArtifact(artifact_id, kind, request_id, parent_id, fixed)

    def read_artifact(self, artifact_id):
        row = self.database.connection.execute(
            '''SELECT a.*, r.kind AS receipt_kind, r.request_id FROM artifacts a
               JOIN receipts r ON r.artifact_id = a.id WHERE a.id=?''', (artifact_id,)).fetchone()
        if row is None:
            raise UnknownArtifact(artifact_id)
        if row['kind'] != row['receipt_kind']:
            raise ArtifactIntegrityError('receipt kind disagrees with artifact')
        try:
            payload = json.loads(row['body'])
            if canonical_json(payload) != row['body']:
                raise ArtifactIntegrityError('stored artifact is not canonical')
            return decode_artifact_record({'id': row['id'], 'kind': row['kind'], 'request_id': row['request_id'],
                                           'parent_id': row['study_id'] or row['analysis_id'], 'payload': payload})
        except (ValueError, TypeError) as error:
            raise ArtifactIntegrityError('invalid stored artifact payload') from error

    def read_parent_chain(self, report_id):
        report = self.read_artifact(report_id)
        if report.kind != 'report':
            raise ArtifactIntegrityError('export requires a report')
        analysis = self.read_artifact(report.parent_id)
        if analysis.kind != 'analysis':
            raise ArtifactIntegrityError('report parent is not an analysis')
        row = self.database.connection.execute('SELECT body FROM studies WHERE id=?', (analysis.parent_id,)).fetchone()
        if row is None:
            raise ArtifactIntegrityError('analysis study is missing')
        study = json.loads(row['body'])
        if canonical_json(study) != row['body'] or 'study:' + content_digest(row['body']) != analysis.parent_id:
            raise ArtifactIntegrityError('study identity does not match fixed content')
        return report, analysis, study
