"""Tests for auto_detect._build_postgres_dsn() — all three detection sources."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.tools.skills.storage.auto_detect import _build_postgres_dsn


class TestSource1DatabaseUrl(unittest.TestCase):

    def test_plain_postgresql_url_passes_through(self):
        """Standard postgresql:// URL is returned unchanged."""
        env = {"DATABASE_URL": "postgresql://hp1:pass@hp1-postgres:5432/hp1_agent"}
        with patch.dict("os.environ", env, clear=True):
            result = _build_postgres_dsn()
        self.assertEqual(result, "postgresql://hp1:pass@hp1-postgres:5432/hp1_agent")

    def test_asyncpg_dialect_is_stripped(self):
        """postgresql+asyncpg:// dialect suffix is stripped so psycopg2 can use the URL."""
        env = {"DATABASE_URL": "postgresql+asyncpg://hp1:pass@hp1-postgres:5432/hp1_agent"}
        with patch.dict("os.environ", env, clear=True):
            result = _build_postgres_dsn()
        self.assertEqual(result, "postgresql://hp1:pass@hp1-postgres:5432/hp1_agent")

    def test_postgres_scheme_also_accepted(self):
        """postgres:// (short form) is also accepted."""
        env = {"DATABASE_URL": "postgres://hp1:pass@hp1-postgres:5432/hp1_agent"}
        with patch.dict("os.environ", env, clear=True):
            result = _build_postgres_dsn()
        self.assertEqual(result, "postgres://hp1:pass@hp1-postgres:5432/hp1_agent")


class TestSource2PostgresVars(unittest.TestCase):

    def test_postgres_host_var_builds_dsn(self):
        """POSTGRES_HOST set → DSN built from individual POSTGRES_* vars."""
        env = {
            "POSTGRES_HOST": "hp1-postgres",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": "hp1_agent",
            "POSTGRES_USER": "hp1",
            "POSTGRES_PASSWORD": "secret",
        }
        with patch.dict("os.environ", env, clear=True):
            result = _build_postgres_dsn()
        self.assertEqual(result, "postgresql://hp1:secret@hp1-postgres:5432/hp1_agent")


class TestSource3Probe(unittest.TestCase):

    def test_hp1_postgres_probed_first(self):
        """hp1-postgres is the first hostname tried in the probe list."""
        env = {
            "POSTGRES_USER": "hp1",
            "POSTGRES_PASSWORD": "hp1agent",
            "POSTGRES_DB": "hp1_agent",
        }
        with patch.dict("os.environ", env, clear=True):
            with patch(
                "mcp_server.tools.skills.storage.auto_detect._port_open"
            ) as mock_probe:
                mock_probe.side_effect = lambda host, port: host == "hp1-postgres"
                with patch("socket.getaddrinfo", side_effect=OSError):
                    result = _build_postgres_dsn()
        self.assertIn("hp1-postgres", result)
        # Confirm hp1-postgres was the first host tried
        first_call_host = mock_probe.call_args_list[0][0][0]
        self.assertEqual(first_call_host, "hp1-postgres")

    def test_fallback_empty_when_nothing_resolves(self):
        """Returns empty string when no source succeeds — caller uses SQLite."""
        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "mcp_server.tools.skills.storage.auto_detect._port_open",
                return_value=False,
            ):
                with patch("socket.getaddrinfo", side_effect=OSError):
                    result = _build_postgres_dsn()
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
