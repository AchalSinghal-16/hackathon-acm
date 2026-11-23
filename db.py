import os, re, sqlite3, urllib.parse
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

try:
    import psycopg2
    from psycopg2 import extras
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

class RowProxy:
    """A row wrapper that supports dict-like access, index access, and formats datetime objects as strings."""
    def __init__(self, d, col_names):
        clean_d = {}
        for k, v in d.items():
            if hasattr(v, 'strftime'):
                clean_d[k] = v.strftime('%Y-%m-%d %H:%M:%S')
            else:
                clean_d[k] = v
        self._dict = clean_d
        self._list = [clean_d.get(col) for col in col_names]
        self._col_names = col_names

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._list[key]
        if key in self._dict:
            return self._dict[key]
        k_lower = str(key).lower()
        for k, v in self._dict.items():
            if str(k).lower() == k_lower:
                return v
        raise KeyError(key)

    def get(self, key, default=None):
        try:
            return self[key]
        except (KeyError, IndexError):
            return default

    def keys(self):
        return self._dict.keys()

    def values(self):
        return self._dict.values()

    def items(self):
        return self._dict.items()

    def __iter__(self):
        return iter(self._dict)

    def __len__(self):
        return len(self._dict)

    def __repr__(self):
        return repr(self._dict)

class PostgresCursorWrapper:
    def __init__(self, cursor):
        self._cursor = cursor
        self.lastrowid = None

    def _convert_sql(self, sql):
        sql = sql.replace("?", "%s")
        if sql.strip().upper().startswith("PRAGMA"):
            return None
        return sql

    def execute(self, sql, params=None):
        clean_sql = self._convert_sql(sql)
        if clean_sql is None:
            return self

        is_insert = clean_sql.strip().upper().startswith("INSERT INTO")
        has_returning = "RETURNING" in clean_sql.upper()

        if is_insert and not has_returning:
            clean_sql = clean_sql.rstrip(";\n ") + " RETURNING id"

        try:
            if params is not None:
                self._cursor.execute(clean_sql, params)
            else:
                self._cursor.execute(clean_sql)
        except Exception:
            if is_insert and not has_returning:
                base_sql = self._convert_sql(sql)
                if params is not None:
                    self._cursor.execute(base_sql, params)
                else:
                    self._cursor.execute(base_sql)
            else:
                raise

        if is_insert and not has_returning:
            try:
                ret = self._cursor.fetchone()
                if ret and len(ret) > 0:
                    self.lastrowid = ret[0]
            except Exception:
                self.lastrowid = None

        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        col_names = [desc[0] for desc in self._cursor.description]
        return RowProxy(row, col_names)

    def fetchall(self):
        rows = self._cursor.fetchall()
        if not rows:
            return []
        col_names = [desc[0] for desc in self._cursor.description]
        return [RowProxy(r, col_names) for r in rows]

    def fetchmany(self, size=None):
        rows = self._cursor.fetchmany(size) if size else self._cursor.fetchmany()
        if not rows:
            return []
        col_names = [desc[0] for desc in self._cursor.description]
        return [RowProxy(r, col_names) for r in rows]

    def __iter__(self):
        while True:
            row = self.fetchone()
            if row is None:
                break
            yield row

    def executescript(self, script):
        statements = [s.strip() for s in script.split(";") if s.strip()]
        for stmt in statements:
            self.execute(stmt)
        return self

    @property
    def rowcount(self):
        return self._cursor.rowcount

    def close(self):
        self._cursor.close()

class PostgresConnectionWrapper:
    def __init__(self, conn):
        self._conn = conn

    def cursor(self):
        return PostgresCursorWrapper(self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor))

    def execute(self, sql, params=None):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def executescript(self, script):
        cur = self.cursor()
        cur.executescript(script)
        return cur

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    @property
    def row_factory(self):
        return None

    @row_factory.setter
    def row_factory(self, val):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()

def get_connection(instance_path=None):
    """
    Returns unified DB connection.
    Uses PostgreSQL if DATABASE_URL is set, otherwise falls back to SQLite.
    """
    db_url = os.environ.get("DATABASE_URL", "").strip()
    if db_url and HAS_POSTGRES:
        clean_url = db_url.split("&channel_binding")[0]
        if clean_url.startswith("postgresql://") or clean_url.startswith("postgres://"):
            p = urllib.parse.urlparse(clean_url)
            try:
                raw_conn = psycopg2.connect(
                    host=p.hostname,
                    port=p.port or 5432,
                    user=p.username,
                    password=p.password,
                    dbname=p.path.lstrip('/'),
                    sslmode='require',
                    connect_timeout=10
                )
                return PostgresConnectionWrapper(raw_conn)
            except Exception as e:
                err_str = str(e).lower()
                if "could not translate host name" in err_str or "name or service not known" in err_str:
                    for ip in ["13.228.184.177", "13.228.46.236", "52.220.170.93"]:
                        try:
                            raw_conn = psycopg2.connect(
                                host=p.hostname,
                                hostaddr=ip,
                                port=p.port or 5432,
                                user=p.username,
                                password=p.password,
                                dbname=p.path.lstrip('/'),
                                sslmode='require',
                                connect_timeout=10
                            )
                            return PostgresConnectionWrapper(raw_conn)
                        except Exception:
                            continue
                print("PostgreSQL connection error, falling back to SQLite:", e)
        else:
            try:
                raw_conn = psycopg2.connect(clean_url)
                return PostgresConnectionWrapper(raw_conn)
            except Exception as e:
                print("PostgreSQL connection error, falling back to SQLite:", e)

    # SQLite Fallback
    if instance_path is None:
        instance_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance")
    os.makedirs(instance_path, exist_ok=True)
    sqlite_db = os.path.join(instance_path, "hackathon.db")
    conn = sqlite3.connect(sqlite_db)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
    except Exception:
        pass
    return conn
