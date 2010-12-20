# -*- coding: utf-8 -*-
# vi: sts=4 et sw=4

from logging import info
from sqlite3 import connect, OperationalError, PARSE_DECLTYPES, PARSE_COLNAMES

class SQL(object):
    '''
    This class makes easy access to the SQL database. Each time you call
    SQL(url) using the same value for url, the same connection is reused.
    If you simply call SQL(), any connection will be used.
    Obviously, you need to provide an URL on the first call at least. If
    you don't, None will be returned.
    '''
    cache = {}

    def __new__(cls, url=None):
        '''The first time a given URL is given, the connection is made and
           stored in a cache. On subsequent calls (with the same URL), it
           will be reused.
           If no URL is given, assume we can use any cached connection (if
           there's no cached connection, return None).
        '''
        if url is None:
            try:
                url = cls.cache.keys()[0]
            except IndexError:
                return None
        if (url not in cls.cache):
            cls.cache[url] = object.__new__(cls)
            cls.cache[url].conn = connect(url, isolation_level=None, detect_types=PARSE_DECLTYPES|PARSE_COLNAMES)
            cls.cache[url].cursor = cls.cache[url].conn.cursor()
            cls.cache[url].execute = cls.cache[url].cursor.execute
            cls.cache[url].commit = cls.cache[url].conn.commit
            cls.cache[url].close = cls.cache[url].conn.close
            cls.cache[url].fetchone = cls.cache[url].cursor.fetchone
            cls.cache[url].fetchall = cls.cache[url].cursor.fetchall
            cls.cache[url].lastrowid = cls.cache[url].cursor.lastrowid
        return cls.cache[url]

    @classmethod
    def close(cls, url=None):
        try:
            if url is None:
                url = cls.cache.keys()[0]
            cls.cache[url].close()
            del cls.cache[url]
        except IndexError:
            pass # No cached connection, or URL not in cache: nothing to close.


class Database(object):
    '''This class represents the bitcoIM database.'''

    def __init__(self, url=None):
        self.url = url

    def upgrade(self, new_version):
        try:
            SQL(self.url).execute("select value from meta where name='db_version'")
            row = SQL(self.url).fetchone()
        except OperationalError:
            row = None
        if row is not None:
            current_version = int(row[0])
        else:
            current_version = 0
        while current_version < new_version:
            if 0 == current_version:
                req = '''CREATE TABLE IF NOT EXISTS meta (
                         id INTEGER NOT NULL,
                         name varchar(256) NOT NULL,
                         value varchar(256) NOT NULL,
                         PRIMARY KEY (id)
                         )'''
                SQL(self.url).execute(req)
                req = 'insert into meta (name, value) values (?, ?)'
                SQL(self.url).execute(req, ('db_version', '0'))
                req = '''CREATE TABLE IF NOT EXISTS registrations (
                         id INTEGER NOT NULL,
                         registered_jid varchar(256) NOT NULL,
                         username varchar(256) NOT NULL,
                         PRIMARY KEY (id)
                         )'''
                SQL(self.url).execute(req)
                req = '''CREATE TABLE IF NOT EXISTS payments (
                         id INTEGER NOT NULL,
                         from_jid varchar(256) NOT NULL,
                         date timestamp NOT NULL,
                         recipient varchar(256) NOT NULL,
                         amount real NOT NULL,
                         comment varchar(256) NOT NULL,
                         confirmation_code varchar(256) NOT NULL,
                         fee real NOT NULL,
                         PRIMARY KEY (id)
                         )'''
                SQL(self.url).execute(req)
            current_version += 1
            req = 'update meta set value=? where name=?'
            SQL(self.url).execute(req, (current_version, 'db_version'))
            info("Upgraded to DB version %s" % current_version)
