"""python test_db.py 로 실행. 저장 로직(추가·수정·삭제)과 스키마 규칙을 확인한다."""
import datetime as dt

import pandas as pd

import db

conn = db.connect(":memory:")
cols = ["keyword", "monthly_search", "product_count", "competition", "memo"]

# 추가
empty = db.query(conn, "SELECT id, " + ", ".join(cols) + " FROM keywords")
db.save(conn, "keywords", empty, pd.DataFrame([
    {"id": None, "keyword": "캠핑의자", "monthly_search": 1000, "product_count": 500, "competition": 0.5, "memo": None},
    {"id": None, "keyword": "텀블러", "monthly_search": 2000, "product_count": 100, "competition": None, "memo": "후보"},
]), cols)
before = db.query(conn, "SELECT id, " + ", ".join(cols) + " FROM keywords ORDER BY id")
assert list(before["keyword"]) == ["캠핑의자", "텀블러"]

# 수정 + 삭제
after = before.copy()
after.loc[0, "memo"] = "확정"
after = after[after["keyword"] != "텀블러"]
db.save(conn, "keywords", before, after, cols)
rows = conn.execute("SELECT keyword, memo FROM keywords").fetchall()
assert rows == [("캠핑의자", "확정")], rows

# 날짜 변환 + 발행 트리거 + 연쇄 삭제
kid = conn.execute("SELECT id FROM keywords").fetchone()[0]
conn.execute("INSERT INTO posts (keyword_id, title, planned_date) VALUES (?, '캠핑의자 후기', ?)",
             (kid, db.clean(pd.Timestamp("2026-10-10"))))
conn.execute("UPDATE posts SET status = '발행'")
planned, published = conn.execute("SELECT planned_date, published_date FROM posts").fetchone()
assert planned == "2026-10-10" and published == dt.date.today().isoformat()
conn.execute("INSERT INTO stats (post_id, record_date, revenue_krw) VALUES (1, '2026-10-11', 3000)")
conn.execute("DELETE FROM posts")
assert conn.execute("SELECT COUNT(*) FROM stats").fetchone()[0] == 0

print("ok")
