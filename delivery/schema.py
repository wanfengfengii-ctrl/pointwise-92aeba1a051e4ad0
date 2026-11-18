SCHEMA_VERSION = 1


class SchemaMismatch(ValueError):
    pass


_TABLES = {
    'revisions': ('network_id', 'revision', 'digest', 'body'),
    'studies': ('id', 'request_id', 'fingerprint', 'body'),
    'artifacts': ('id', 'kind', 'study_id', 'analysis_id', 'body'),
    'receipts': ('kind', 'request_id', 'artifact_id'),
}


_DDL = (
    '''CREATE TABLE revisions (
        network_id TEXT NOT NULL, revision TEXT NOT NULL, digest TEXT NOT NULL, body BLOB NOT NULL,
        PRIMARY KEY (network_id, revision)
    )''',
    '''CREATE TABLE studies (
        id TEXT PRIMARY KEY NOT NULL, request_id TEXT NOT NULL,
        fingerprint TEXT NOT NULL, body BLOB NOT NULL
    )''',
    '''CREATE TABLE artifacts (
        id TEXT PRIMARY KEY NOT NULL, kind TEXT NOT NULL,
        study_id TEXT REFERENCES studies(id), analysis_id TEXT REFERENCES artifacts(id), body BLOB NOT NULL,
        CHECK ((kind = 'analysis' AND study_id IS NOT NULL AND analysis_id IS NULL)
            OR (kind = 'report' AND study_id IS NULL AND analysis_id IS NOT NULL))
    )''',
    '''CREATE TABLE receipts (
        kind TEXT NOT NULL, request_id TEXT NOT NULL,
        artifact_id TEXT NOT NULL UNIQUE REFERENCES artifacts(id),
        PRIMARY KEY (kind, request_id), CHECK (kind IN ('analysis', 'report'))
    )''',
)


# Local study request identities stay separate from accepted deliveries, just as
# artifact receipts do.  Accepted artifacts carry their original request identity
# in ``artifact_requests`` because their request space belongs to a source.
_AUX_DDL = (
    '''CREATE TABLE IF NOT EXISTS study_receipts (
        request_id TEXT PRIMARY KEY NOT NULL,
        study_id TEXT NOT NULL REFERENCES studies(id)
    )''',
    '''CREATE TABLE IF NOT EXISTS artifact_requests (
        artifact_id TEXT PRIMARY KEY NOT NULL REFERENCES artifacts(id),
        kind TEXT NOT NULL, request_id TEXT NOT NULL,
        CHECK (kind IN ('analysis', 'report'))
    )''',
    '''CREATE TABLE IF NOT EXISTS source_bindings (
        source_id TEXT NOT NULL, kind TEXT NOT NULL, request_id TEXT NOT NULL, target_id TEXT NOT NULL,
        PRIMARY KEY (source_id, kind, request_id),
        CHECK (kind IN ('study', 'analysis', 'report'))
    )''',
    '''CREATE TABLE IF NOT EXISTS acceptances (
        source_id TEXT NOT NULL, report_request_id TEXT NOT NULL,
        study_id TEXT NOT NULL, analysis_id TEXT NOT NULL, report_id TEXT NOT NULL,
        PRIMARY KEY (source_id, report_request_id)
    )''',
)


def check_schema(connection):
    version = connection.execute('PRAGMA user_version').fetchone()[0]
    if version != SCHEMA_VERSION:
        raise SchemaMismatch(f'archive schema version {version} is incompatible with {SCHEMA_VERSION}')
    for table, expected in _TABLES.items():
        actual = tuple(row[1] for row in connection.execute(f'PRAGMA table_info({table})'))
        if actual != expected:
            raise SchemaMismatch(f'archive table {table} has incompatible columns')


def _study_request_is_unique(connection):
    if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='studies'").fetchone() is None:
        return False
    for index in connection.execute('PRAGMA index_list(studies)'):
        if not index[2]:
            continue
        columns = tuple(row[2] for row in connection.execute(f'PRAGMA index_info("{index[1]}")'))
        if columns == ('request_id',):
            return True
    return False


def _rebuild_studies(connection):
    # Version 1 archives used to key local study requests with UNIQUE(request_id).
    # Accepted deliveries bring their own request space, so the column stays
    # indexed by identity only and local requests live in ``study_receipts``.
    connection.execute('''CREATE TABLE studies_rebuild (
        id TEXT PRIMARY KEY NOT NULL, request_id TEXT NOT NULL,
        fingerprint TEXT NOT NULL, body BLOB NOT NULL
    )''')
    connection.execute('INSERT INTO studies_rebuild SELECT id, request_id, fingerprint, body FROM studies')
    connection.execute('DROP TABLE studies')
    connection.execute('ALTER TABLE studies_rebuild RENAME TO studies')


def _initialize_acceptance_tables(connection, rebuild):
    if rebuild:
        _rebuild_studies(connection)
    existing = {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    for statement in _AUX_DDL:
        connection.execute(statement)
    if 'study_receipts' not in existing:
        # Everything stored by the pre-acceptance schema was locally frozen.
        connection.execute('INSERT OR IGNORE INTO study_receipts SELECT request_id, id FROM studies')
    if 'artifact_requests' not in existing:
        # Pre-acceptance archives keyed every artifact's request in ``receipts``.
        connection.execute('''INSERT OR IGNORE INTO artifact_requests
                              SELECT artifact_id, kind, request_id FROM receipts''')


def initialize_schema(connection):
    rebuild = _study_request_is_unique(connection)
    if rebuild:
        connection.execute('PRAGMA foreign_keys = OFF')
    try:
        connection.execute('BEGIN IMMEDIATE')
        version = connection.execute('PRAGMA user_version').fetchone()[0]
        if version == 0:
            existing = connection.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchone()
            if existing is not None:
                raise SchemaMismatch('unversioned archive already contains stored objects')
            for statement in _DDL:
                connection.execute(statement)
            connection.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')
        check_schema(connection)
        _initialize_acceptance_tables(connection, rebuild)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        if rebuild:
            connection.execute('PRAGMA foreign_keys = ON')
