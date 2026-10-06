import sqlite3
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent


# 예전 버전으로 만든 DB에 새로 붙일 컬럼
MIGRATIONS = {
    "keywords": [("comp_idx", "TEXT"), ("peak_months", "TEXT"), ("trend_index", "REAL"),
                 ("blog_ratio", "REAL"), ("source_url", "TEXT")],
    "posts": [("commission_rate", "REAL"), ("draft_body", "TEXT"), ("caption", "TEXT"),
              ("shorts_script", "TEXT"), ("video_path", "TEXT"), ("ig_media_id", "TEXT")],
    "stats": [("source", "TEXT")],
    "recommendations": [("blog_ratio", "REAL"), ("source_url", "TEXT")],
}


def connect(path=HERE / "sidehustle.db"):
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    for table, columns in MIGRATIONS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for column, kind in columns:
            if have and column not in have:  # 테이블이 아직 없으면 schema.sql이 새로 만든다
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
    conn.executescript((HERE / "schema.sql").read_text(encoding="utf-8"))
    return conn


def query(conn, sql, params=()):
    return pd.read_sql_query(sql, conn, params=params)


def clean(v):
    """pandas 값(NaN, Timestamp, numpy 숫자)을 SQLite에 넣을 수 있는 값으로."""
    if v is None or pd.isna(v):
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()[:10]
    if hasattr(v, "item"):
        return v.item()
    return v


def save(conn, table, before, after, cols):
    """표 편집 결과를 DB에 반영: 사라진 행은 DELETE, id 없는 행은 INSERT, 나머지는 UPDATE."""
    kept = set(after["id"].dropna().astype(int))
    with conn:  # 하나라도 실패하면 전체 롤백
        for gone in set(before["id"].astype(int)) - kept:
            conn.execute(f"DELETE FROM {table} WHERE id = ?", (gone,))
        for row in after.to_dict("records"):
            vals = [clean(row.get(c)) for c in cols]
            if pd.isna(row.get("id")):
                conn.execute(
                    f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                    vals,
                )
            else:
                conn.execute(
                    f"UPDATE {table} SET {', '.join(c + ' = ?' for c in cols)} WHERE id = ?",
                    [*vals, int(row["id"])],
                )
