from contextlib import contextmanager


class TransactionError(RuntimeError):
    pass


class TransactionManager:
    def __init__(self, database, *, before_commit=None):
        self.database = database
        self.before_commit = before_commit

    @contextmanager
    def atomic(self, operation):
        connection = self.database.connection
        if connection.in_transaction:
            raise TransactionError('an archive transaction is already active')
        connection.execute('BEGIN IMMEDIATE')
        try:
            yield connection
            if self.before_commit is not None:
                self.before_commit(operation)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
