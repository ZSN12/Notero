"""Tests that the test harness refuses to touch non-test databases."""

from unittest.mock import MagicMock, patch

import pytest

from tests.harness.db_guard import ensure_test_database, validate_test_database_url


class TestValidateTestDatabaseUrl:
    def test_accepts_test_database(self):
        name = validate_test_database_url("postgresql://u:p@localhost:5432/notero_test")
        assert name == "notero_test"

    def test_accepts_postgres_plus_psycopg2(self):
        name = validate_test_database_url(
            "postgresql+psycopg2://u:p@localhost:5432/nootbook_test"
        )
        assert name == "nootbook_test"

    @pytest.mark.parametrize("url", [
        "postgresql://u:p@localhost:5432/nootbook",
        "postgresql://u:p@localhost:5432/dev_notero",
        "postgresql://u:p@localhost:5432/PROD",
    ])
    def test_rejects_non_test_database(self, url):
        with pytest.raises(RuntimeError) as excinfo:
            validate_test_database_url(url)
        assert "Refusing to reset non-test database" in str(excinfo.value)

    def test_rejects_non_postgresql(self):
        with pytest.raises(RuntimeError) as excinfo:
            validate_test_database_url("sqlite:///test.db")
        assert "PostgreSQL" in str(excinfo.value)


class TestEnsureTestDatabase:
    def test_raises_before_any_drop_when_name_is_not_test(self):
        """If TEST_DATABASE_URL points to a non-test DB, drop_all must never run."""
        bad_url = "postgresql://u:p@localhost:5432/nootbook"
        with pytest.raises(RuntimeError):
            ensure_test_database(bad_url)

    def test_creates_missing_test_database(self):
        url = "postgresql://u:p@localhost:5432/notero_test"
        mock_engine = MagicMock()
        mock_conn = mock_engine.connect.return_value.__enter__.return_value
        mock_conn.execute.return_value.scalar.return_value = None

        with patch("tests.harness.db_guard.create_engine", return_value=mock_engine) as create_engine_mock:
            ensure_test_database(url)

        create_engine_mock.assert_called_once()
        called_url = create_engine_mock.call_args[0][0]
        assert called_url == "postgresql://u:p@localhost:5432/postgres"
        # The CREATE DATABASE statement must target the test DB, not dev/prod.
        execute_calls = [call.args for call in mock_conn.execute.call_args_list]
        assert any('CREATE DATABASE "notero_test"' in str(args[0]) for args in execute_calls)
