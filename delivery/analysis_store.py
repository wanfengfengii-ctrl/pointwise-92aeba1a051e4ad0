import json
from dataclasses import dataclass

from delivery.transactions import TransactionManager
from network.canonical import canonical_json, content_digest
from network.model import valid_text
from study.bindings import binding_fingerprint


KINDS = ('analysis', 'report')


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


@dataclass(frozen=True)
class Acceptance:
    source_id: str
    report_request_id: str
    study_id: str
    analysis_id: str
    report_id: str

    @property
    def receipt(self):
        return (self.source_id, self.report_request_id, self.study_id, self.analysis_id, self.report_id)

    def record(self):
        return {'source_id': self.source_id, 'report_request_id': self.report_request_id,
                'study_id': self.study_id, 'analysis_id': self.analysis_id, 'report_id': self.report_id}


def _identity(kind, request_id, parent_id, payload):
    return kind + ':' + content_digest(canonical_json({
        'kind': kind, 'request_id': request_id, 'parent_id': parent_id, 'payload': payload,
    }))


def decode_artifact_record(record):
    if not isinstance(record, dict) or set(record) != {'id', 'kind', 'request_id', 'parent_id', 'payload'}:
        raise ArtifactIntegrityError('invalid fixed artifact fields')
    kind, request, parent, payload = (record[key] for key in ('kind', 'request_id', 'parent_id', 'payload'))
    if kind not in KINDS or not valid_text(request) or not valid_text(parent) or not isinstance(payload, dict):
        raise ArtifactIntegrityError('invalid fixed artifact record')
    if record['id'] != _identity(kind, request, parent, payload):
        raise ArtifactIntegrityError('artifact identity does not match fixed content')
    return PublishedArtifact(record['id'], kind, request, parent, payload)


def acceptance_from_row(row):
    if row is None:
        return None
    return Acceptance(row['source_id'], row['report_request_id'], row['study_id'], row['analysis_id'],
                      row['report_id'])


class ArtifactStore:
    def __init__(self, database, *, before_commit=None):
        self.database = database
        self.transactions = TransactionManager(database, before_commit=before_commit)

    def find_receipt(self, kind, request_id, parent_id=None):
        if kind not in KINDS or not valid_text(request_id):
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

    def _insert_artifact(self, conn, artifact_id, kind, study_id, analysis_id, body, request_id):
        conn.execute('INSERT INTO artifacts VALUES (?, ?, ?, ?, ?)', (artifact_id, kind, study_id, analysis_id, body))
        conn.execute('INSERT INTO artifact_requests VALUES (?, ?, ?)', (artifact_id, kind, request_id))

    def _ensure_artifact(self, conn, artifact_id, kind, study_id, analysis_id, body, request_id):
        """Keep one fixed artifact per identity; a shared copy must match exactly."""
        existing = conn.execute('SELECT kind, study_id, analysis_id, body FROM artifacts WHERE id=?',
                                (artifact_id,)).fetchone()
        if existing is None:
            self._insert_artifact(conn, artifact_id, kind, study_id, analysis_id, body, request_id)
            return
        if (existing['kind'], existing['study_id'], existing['analysis_id'], existing['body']) != (
                kind, study_id, analysis_id, body):
            raise ArtifactIntegrityError(f'fixed artifact {artifact_id} does not match its stored content')

    def publish(self, kind, request_id, parent_id, payload):
        if kind not in KINDS or not valid_text(request_id) or not valid_text(parent_id):
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
            self._ensure_artifact(conn, artifact_id, kind, *parents, body, request_id)
            conn.execute('INSERT INTO receipts VALUES (?, ?, ?)', (kind, request_id, artifact_id))
        return PublishedArtifact(artifact_id, kind, request_id, parent_id, fixed)

    def read_artifact(self, artifact_id):
        row = self.database.connection.execute(
            '''SELECT a.*, q.kind AS request_kind, q.request_id FROM artifacts a
               JOIN artifact_requests q ON q.artifact_id = a.id WHERE a.id=?''', (artifact_id,)).fetchone()
        if row is None:
            raise UnknownArtifact(artifact_id)
        if row['kind'] != row['request_kind'] or row['kind'] not in KINDS:
            raise ArtifactIntegrityError('request kind disagrees with artifact')
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

    # --- source-scoped acceptance -------------------------------------------------

    def find_acceptance(self, source_id, report_request_id):
        if not valid_text(source_id) or not valid_text(report_request_id):
            raise ValueError('source and report request identities must be nonempty text')
        row = self.database.connection.execute(
            'SELECT * FROM acceptances WHERE source_id=? AND report_request_id=?',
            (source_id, report_request_id)).fetchone()
        acceptance = acceptance_from_row(row)
        if acceptance is None:
            return None
        if (self.database.connection.execute('SELECT 1 FROM studies WHERE id=?', (acceptance.study_id,)).fetchone()
                is None):
            raise ArtifactIntegrityError('accepted study is missing')
        for artifact_id in (acceptance.analysis_id, acceptance.report_id):
            if self.database.connection.execute('SELECT 1 FROM artifacts WHERE id=?',
                                                (artifact_id,)).fetchone() is None:
                raise ArtifactIntegrityError('accepted artifact is missing')
        return acceptance

    def _binding(self, conn, source_id, kind, request_id):
        row = conn.execute('SELECT target_id FROM source_bindings WHERE source_id=? AND kind=? AND request_id=?',
                           (source_id, kind, request_id)).fetchone()
        return None if row is None else row['target_id']

    def _bind(self, conn, source_id, kind, request_id, target_id):
        bound = self._binding(conn, source_id, kind, request_id)
        if bound is not None:
            if bound != target_id:
                raise PublicationConflict(f'{kind} request {request_id!r} from source {source_id!r} differs')
            return
        conn.execute('INSERT INTO source_bindings VALUES (?, ?, ?, ?)', (source_id, kind, request_id, target_id))

    def accept(self, source_id, study, analysis_record, report_record):
        """Store one verified package and its source receipt in a single transaction."""
        if not valid_text(source_id):
            raise ValueError('source identity must be nonempty text')
        study_id, study_request = study.study_id, study.request_id
        analysis_id, analysis_request = analysis_record.artifact_id, analysis_record.request_id
        report_id, report_request = report_record.artifact_id, report_record.request_id

        with self.transactions.atomic('acceptance') as conn:
            previous = self.find_acceptance(source_id, report_request)
            if previous is not None:
                if (previous.study_id, previous.analysis_id, previous.report_id) != (study_id, analysis_id, report_id):
                    raise PublicationConflict(f'report request {report_request!r} from source {source_id!r} differs')
                return previous

            # Every level is bound before any shared row is created, so a conflicting
            # package leaves nothing behind.
            self._bind(conn, source_id, 'study', study_request, study_id)
            self._bind(conn, source_id, 'analysis', analysis_request, analysis_id)
            self._bind(conn, source_id, 'report', report_request, report_id)

            study_existing = conn.execute('SELECT body FROM studies WHERE id=?', (study_id,)).fetchone()
            if study_existing is None:
                fingerprint = binding_fingerprint((sample.time, sample.revision.ref) for sample in study.samples)
                conn.execute('INSERT INTO studies VALUES (?, ?, ?, ?)',
                             (study_id, study_request, fingerprint, canonical_json(study.payload())))
            elif study_existing['body'] != canonical_json(study.payload()):
                raise ArtifactIntegrityError(f'fixed study {study_id} does not match its stored content')
            # A shared study, analysis or report identity keeps the one fixed result.

            self._ensure_artifact(conn, analysis_id, 'analysis', study_id, None,
                                  canonical_json(analysis_record.payload), analysis_request)
            self._ensure_artifact(conn, report_id, 'report', None, analysis_id,
                                  canonical_json(report_record.payload), report_request)

            conn.execute('INSERT INTO acceptances VALUES (?, ?, ?, ?, ?)',
                         (source_id, report_request, study_id, analysis_id, report_id))
        return Acceptance(source_id, report_request, study_id, analysis_id, report_id)
