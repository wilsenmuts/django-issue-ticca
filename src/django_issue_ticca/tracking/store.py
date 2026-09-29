import atexit
import logging
import os
import queue
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager

logger = logging.getLogger(__name__)

_STOP = object()


class TrackingStore:
    """
    Isolated SQLite store for active-user tracking.

    - Own file, own connection, no Django ORM involvement.
    - Writes go through a background thread + queue so requests never block.
    - WAL mode keeps reads non-blocking while writes happen.
    """

    SCHEMA = """
    PRAGMA journal_mode=WAL;
    PRAGMA synchronous=NORMAL;
    PRAGMA busy_timeout=5000;

    CREATE TABLE IF NOT EXISTS app_instance (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        app_name     TEXT    NOT NULL,
        domain       TEXT    NOT NULL,
        counter      TEXT    NOT NULL,   -- random per-process id
        pid          INTEGER NOT NULL,
        started_at   REAL    NOT NULL,
        last_seen    REAL    NOT NULL,
        alive        INTEGER NOT NULL DEFAULT 1,
        UNIQUE(app_name, domain, counter)
    );

    CREATE TABLE IF NOT EXISTS active_users (
        instance_id  INTEGER NOT NULL,
        user_id      INTEGER,            -- NULL for anonymous
        session_key  TEXT,               -- used when user_id IS NULL
        entered_at   REAL    NOT NULL,
        last_seen    REAL    NOT NULL,
        PRIMARY KEY (instance_id, user_id, session_key)
    ) WITHOUT ROWID;

    CREATE INDEX IF NOT EXISTS ix_active_user ON active_users(user_id);
    CREATE INDEX IF NOT EXISTS ix_active_sess ON active_users(session_key);
    """

    def __init__(self, path, app_name, domain, batch_size=100, flush_interval=0.5,
                 max_queue_size=20_000):
        self.path = path
        self.app_name = app_name
        self.domain = domain
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.max_queue_size = max_queue_size
        self.queue: queue.Queue = queue.Queue(maxsize=max_queue_size)
        self._instance_id: int | None = None
        self._thread: threading.Thread | None = None
        self._running = False

    # ---------------------------------------------------------------- public
    def start(self):
        if self._running:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        # Initialize schema synchronously so the first writes don't race.
        with self._connect() as conn:
            conn.executescript(self.SCHEMA)
            counter = uuid.uuid4().hex[:12]
            cur = conn.execute(
                "INSERT INTO app_instance(app_name,domain,counter,pid,"
                "started_at,last_seen,alive) VALUES(?,?,?,?,?,?,1)",
                (self.app_name, self.domain, counter, os.getpid(),
                 time.time(), time.time()),
            )
            self._instance_id = cur.lastrowid
            conn.commit()

        self._running = True
        self._thread = threading.Thread(target=self._loop, name='track-writer', daemon=True)
        self._thread.start()
        atexit.register(self.stop)
        logger.info("TrackingStore started file=%s instance=%s", self.path, self._instance_id)

    def stop(self):
        if not self._running:
            return
        self._running = False
        try:
            self.queue.put_nowait(_STOP)
        except queue.Full:
            pass
        if self._thread:
            self._thread.join(timeout=5)
        try:
            with self._connect() as conn:
                conn.execute("UPDATE app_instance SET alive=0 WHERE id=?",
                             (self._instance_id,))
                conn.commit()
        except Exception:
            logger.exception("Failed to mark instance dead")

    def enter(self, user_id: int | None, session_key: str | None):
        self._put(('enter', user_id, session_key))

    def exit(self, user_id: int | None, session_key: str | None):
        self._put(('exit', user_id, session_key))

    # ------------------------------------------------------------ internals
    def _put(self, item):
        if not self._running or self._instance_id is None:
            return
        try:
            self.queue.put_nowait(item)
        except queue.Full:
            # Drop rather than block the request. Fine for tracking.
            logger.debug("Tracking queue full, dropping %s", item[0])

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        try:
            yield conn
        finally:
            conn.close()

    def _loop(self):
        buf: list[tuple] = []
        last_flush = time.monotonic()

        while self._running:
            try:
                item = self.queue.get(timeout=self.flush_interval)
            except queue.Empty:
                item = None

            if item is _STOP:
                break
            if item is not None:
                buf.append(item)

            now = time.monotonic()
            if buf and (len(buf) >= self.batch_size or now - last_flush >= self.flush_interval):
                self._flush(buf)
                buf.clear()
                last_flush = now

        if buf:
            self._flush(buf)

    def _flush(self, batch):
        """Apply a batch in a single transaction. Rolls back on failure."""
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                now = time.time()
                inserts = []
                deletes = []

                for kind, user_id, session_key in batch:
                    if kind == 'enter':
                        inserts.append((self._instance_id, user_id, session_key, now, now))
                    else:
                        deletes.append((self._instance_id, user_id, session_key))

                if inserts:
                    conn.executemany(
                        """INSERT INTO active_users
                             (instance_id, user_id, session_key, entered_at, last_seen)
                           VALUES (?,?,?,?,?)
                           ON CONFLICT(instance_id, user_id, session_key)
                           DO UPDATE SET last_seen=excluded.last_seen""",
                        inserts,
                    )
                if deletes:
                    conn.executemany(
                        """DELETE FROM active_users
                           WHERE instance_id=? AND user_id IS ? AND session_key IS ?""",
                        deletes,
                    )

                conn.execute("UPDATE app_instance SET last_seen=? WHERE id=?",
                             (now, self._instance_id))
                conn.execute("COMMIT")
        except Exception:
            logger.exception("Tracking flush failed (%d items)", len(batch))