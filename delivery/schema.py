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
        id TEXT PRIMARY KEY NOT NULL, request_id TEXT UNIQUE NOT NULL,
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


def check_schema(connection):
    version = connection.execute('PRAGMA user_version').fetchone()[0]
    if version != SCHEMA_VERSION:
        raise SchemaMismatch(f'archive schema version {version} is incompatible with {SCHEMA_VERSION}')
    for table, expected in _TABLES.items():
        actual = tuple(row[1] for row in connection.execute(f'PRAGMA table_info({table})'))
        if actual != expected:
            raise SchemaMismatch(f'archive table {table} has incompatible columns')


def initialize_schema(connection):
    connection.execute('BEGIN IMMEDIATE')
    try:
        version = connection.execute('PRAGMA user_version').fetchone()[0]
        if version == 0:
            existing = connection.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchone()
            if existing is not None:
                raise SchemaMismatch('unversioned archive already contains stored objects')
            for statement in _DDL:
                connection.execute(statement)
            connection.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')
        check_schema(connection)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
