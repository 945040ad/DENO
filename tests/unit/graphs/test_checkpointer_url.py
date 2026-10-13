from psycopg.conninfo import conninfo_to_dict

from deno_graphs.validation.runner import _psycopg_url


def test_password_with_uri_reserved_characters() -> None:
    url = "postgresql+asyncpg://postgres.ref:p?a&ss/w=rd@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres"
    params = conninfo_to_dict(_psycopg_url(url))
    assert params == {
        "host": "aws-0-ap-northeast-1.pooler.supabase.com",
        "port": "5432",
        "dbname": "postgres",
        "user": "postgres.ref",
        "password": "p?a&ss/w=rd",
    }


def test_query_parameters_are_kept() -> None:
    params = conninfo_to_dict(_psycopg_url("postgresql+asyncpg://u:pw@h:6543/db?sslmode=require"))
    assert params["sslmode"] == "require"
    assert params["port"] == "6543"
