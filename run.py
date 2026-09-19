"""Development and WSGI entry point.

Production imports ``app`` through Gunicorn. Direct execution is intentionally
development-only and refuses to hide an already-running local instance.
"""

from __future__ import annotations

import os
import socket

from app import create_app

app = create_app()


def _ensure_local_port_available(port: int) -> None:
    """Fail clearly instead of serving a stale and a fresh build on one port."""

    try:
        connection = socket.create_connection(("127.0.0.1", port), timeout=0.25)
    except OSError:
        return
    connection.close()
    raise SystemExit(
        f"Port {port} is already serving an application. Stop the existing AutoDrive "
        "process before starting another instance."
    )


if __name__ == "__main__":
    local_port = int(os.getenv("PORT", "5000"))
    _ensure_local_port_available(local_port)
    app.run(host=os.getenv("HOST", "0.0.0.0"), port=local_port)
