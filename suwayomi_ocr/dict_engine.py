import os
import sqlite3
import threading


_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")


class SQLiteDictEngine:
    def __init__(self, db_filename: str = "manga_dict.db") -> None:
        self.db_path = os.path.normpath(os.path.join(_DATA_DIR, db_filename))
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

        if not os.path.exists(self.db_path):
            print(f"WARN dict DB missing at {self.db_path}")
            return

        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)

    def lookup(self, base_form: str) -> dict:
        if self._conn is None:
            return {"r": "", "d": ""}
        try:
            with self._lock:
                cursor = self._conn.execute(
                    "SELECT reading, definition FROM dictionary WHERE term = ? LIMIT 1",
                    (base_form,),
                )
                row = cursor.fetchone()
        except Exception as exc:
            print(f"dict lookup error: {exc}")
            return {"r": "", "d": ""}

        if row:
            return {"r": row[0], "d": row[1]}
        return {"r": "", "d": ""}


dict_engine = SQLiteDictEngine()
