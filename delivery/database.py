import sqlite3
from pathlib import Path

from delivery.schema import initialize_schema


class ArchiveDatabase:
    def __init__(self, connection, path):
        self._connection = connection
        self.path = path

    @classmethod
    def open(cls, path):
        target = None if str(path) == ':memory:' else Path(path).resolve()
        connection = sqlite3.connect(target if target is not None else ':memory:', isolation_level=None)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys = ON')
            initialize_schema(connection)
        except BaseException:
            connection.close()
            raise
        return cls(connection, target)

    @property
    def connection(self):
        if self._connection is None:
            raise sqlite3.ProgrammingError('archive is closed')
        return self._connection

    def archive_paths(self):
        if self.path is None:
            return ()
        return (self.path, *(self.path.with_name(self.path.name + suffix) for suffix in ('-journal', '-wal', '-shm')))

    def close(self):
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
