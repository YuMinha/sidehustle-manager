"""python test_db.py 로 실행. 저장 로직(추가·수정·삭제)과 스키마 규칙을 확인한다."""
import datetime as dt

import pandas as pd

import collect
import db
import recommend

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

# 성수기·상승세 계산
months = [f"{y}-{m:02d}-01" for y in (2024, 2025, 2026) for m in range(1, 13)]
winter = [(p, 50 if p[5:7] in ("11", "12") else 10) for p in months]
assert collect.peak_months(winter) == "11월, 12월"
assert collect.peak_months([(p, 10) for p in months]) == "연중"
rising = [(p, 10) for p in months[:-1]] + [(months[-1], 25)]
assert collect.trend_index(rising) == 2.5
assert collect.trend_index(rising[:5]) is None

# 추천 점수: 오르는 중·성수기 임박이면 높게, 경쟁 '높음'은 감점
base = {"monthly_search": 10_000, "comp_idx": "중간"}
assert recommend.score({**base, "trend_index": 2.0, "peak_soon": True}) > recommend.score(base)
assert recommend.score({**base, "comp_idx": "높음"}) < recommend.score(base)
assert recommend.score({**base, "trend_index": 9.0}) == recommend.score({**base, "trend_index": 2.0})  # 상한

# 추천 고르기 → 키워드 + 기획 글
conn.execute("""INSERT INTO recommendations (rec_date, keyword, monthly_search, comp_idx, score, reason)
                VALUES ('2026-10-06', '전기요', 17130, '중간', 5.0, '테스트')""")
recommend.pick(conn, [conn.execute("SELECT id FROM recommendations").fetchone()[0]])
assert conn.execute("SELECT title, status FROM posts p JOIN keywords k ON k.id = p.keyword_id "
                    "WHERE k.keyword = '전기요'").fetchone() == ("전기요 (제목 미정)", "기획")
assert conn.execute("SELECT picked FROM recommendations").fetchone()[0] == 1


# 수익 리포트 가져오기: 상품 URL이나 키워드로 내 글과 맞추고, 같은 날짜를 다시 올려도 두 번 더하지 않는다
import pandas as pd

pid = conn.execute("SELECT id FROM posts").fetchone()[0]
conn.execute("UPDATE posts SET product_url = 'https://brandconnect.naver.com/p/123' WHERE id = ?", (pid,))
report = pd.DataFrame({
    "일자": ["2026-10-01", "2026-10-01", "2026-10-02", "2026-10-02"],
    "수익금": ["1,200원", "800", "500", "999"],
    "상품": ["https://brandconnect.naver.com/p/123", "전기요 싱글", "전기요", "모르는 상품"],
})
assert collect.import_revenue(conn, report, "일자", "수익금", "상품") == (3, 1)
collect.import_revenue(conn, report, "일자", "수익금", "상품")
assert conn.execute("SELECT SUM(revenue_krw) FROM stats WHERE source = '파일'").fetchone()[0] == 2500

# 뉴스 키워드: Claude가 돌려준 뉴스 번호를 기사 제목·링크로 바꾼다 (API 호출은 가짜로 대체)
import ai

ai._ask = lambda *a, **k: {"items": [{"keyword": "전기요", "news_index": 1}, {"keyword": "엉뚱", "news_index": 9}]}
news = [{"title": "가을 날씨", "link": "a"}, {"title": "한파 예보", "link": "b"}]
assert ai.news_keywords(news) == [{"keyword": "전기요", "title": "한파 예보", "link": "b"}]

# 발행 막기: 직접 채울 자리가 남은 초안은 '발행'으로 못 바꾼다
import sqlite3

conn.execute("INSERT INTO posts (title, draft_body) VALUES ('초안', '본문 [직접 채우기: 써 본 느낌]')")
try:
    conn.execute("UPDATE posts SET status = '발행' WHERE title = '초안'")
    raise AssertionError("발행이 막히지 않았다")
except sqlite3.IntegrityError:
    pass

print("ok")
