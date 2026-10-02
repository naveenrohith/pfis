"""Intentionally vulnerable in-memory SQL fixture, reachable only on lab networks."""

from __future__ import annotations

import json
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

connection = sqlite3.connect(":memory:", check_same_thread=False)
connection.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, label TEXT NOT NULL)")
connection.executemany("INSERT INTO items (label) VALUES (?)", [("synthetic-item",)])


class FixtureHandler(BaseHTTPRequestHandler):
    server_version = "PFIS-SQL-Fixture"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        if parsed.path != "/item":
            self.send_error(404)
            return
        item_id = parse_qs(parsed.query).get("id", ["1"])[0]
        # Deliberately unsafe query for scanner positive-control verification.
        query = f"SELECT id, label FROM items WHERE id = {item_id}"
        try:
            # codeql[py/sql-injection] Deliberate in-memory positive control; never application data.
            row = connection.execute(query).fetchone()
        except sqlite3.Error:
            row = None
        body = json.dumps({"item": row}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


HTTPServer(("0.0.0.0", 8080), FixtureHandler).serve_forever()
