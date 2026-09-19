from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from run import _ensure_local_port_available


def test_local_server_refuses_to_start_over_an_existing_listener() -> None:
    connection = Mock()
    with patch("run.socket.create_connection", return_value=connection):
        with pytest.raises(SystemExit, match="already serving"):
            _ensure_local_port_available(5000)
    connection.close.assert_called_once_with()


def test_local_server_accepts_an_unused_port() -> None:
    with patch("run.socket.create_connection", side_effect=OSError):
        _ensure_local_port_available(5000)
