"""
database.py - Supabase client wrapper.
Uses the SERVICE ROLE key server-side only.
Never expose this key to the frontend.
"""
import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL: str = os.environ["SUPABASE_URL"]
SUPABASE_KEY: str = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

_client: Client | None = None


def get_db() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


def upsert(table: str, data: dict | list, on_conflict: str = "dedupe_key") -> list:
    """Insert or update by dedupe_key. Returns saved rows."""
    db = get_db()
    result = (
        db.table(table)
        .upsert(data, on_conflict=on_conflict)
        .execute()
    )
    return result.data or []


def select(table: str, filters: dict = None, order: str = None,
           limit: int = 100, columns: str = "*") -> list:
    """Select rows with optional filters."""
    db = get_db()
    q = db.table(table).select(columns)
    if filters:
        for col, val in filters.items():
            q = q.eq(col, val)
    if order:
        desc = order.startswith("-")
        col = order.lstrip("-")
        q = q.order(col, desc=desc)
    q = q.limit(limit)
    return q.execute().data or []


def count(table: str, filters: dict = None) -> int:
    db = get_db()
    q = db.table(table).select("id", count="exact")
    if filters:
        for col, val in filters.items():
            q = q.eq(col, val)
    result = q.execute()
    return result.count or 0
