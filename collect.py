"""매일 아침 자동 수집: 키워드 검색량·경쟁정도·상승세·성수기 갱신, 뉴스 제목 모으기.

python collect.py   → 한 번 실행 (작업 스케줄러가 매일 이걸 실행한다)
"""
import datetime as dt
import statistics

from pathlib import Path

import db
import naver

HERE = Path(__file__).parent

# 상품 주제를 찾을 뉴스 검색어. 바꾸고 싶으면 여기만 고치면 된다.
NEWS_TOPICS = ["품절 대란", "인기 상품", "신제품 출시", "여행 수요", "날씨 예보", "유행 아이템"]
# 사고·재난 뉴스는 상품 주제로 쓰지 않는다
BLOCKED_WORDS = ["사고", "사망", "참사", "화재", "재난", "지진", "부상", "숨져", "숨진", "실종", "피해", "붕괴"]


def peak_month_numbers(series):
    """월별 추이 → 평균보다 30% 이상 높은 달 상위 2개 (숫자). 뚜렷한 성수기가 없으면 []."""
    by_month = {}
    for period, ratio in series:
        by_month.setdefault(int(period[5:7]), []).append(ratio)
    avg = {m: statistics.mean(v) for m, v in by_month.items()}
    overall = statistics.mean(avg.values()) if avg else 0
    top = sorted(avg, key=avg.get, reverse=True)[:2]
    return sorted(m for m in top if overall and avg[m] >= overall * 1.3)


def peak_months(series):
    top = peak_month_numbers(series)
    return ", ".join(f"{m}월" for m in top) if top else "연중"


def trend_index(series):
    """지난달 ÷ 그 전 12개월 평균. 1.5면 평소보다 1.5배 검색되는 중."""
    if len(series) < 13:
        return None
    base = statistics.mean(r for _, r in series[-13:-1])
    return round(series[-1][1] / base, 2) if base else None


def refresh_keywords(conn):
    """저장된 키워드 전부의 검색량·경쟁정도·상승세·성수기를 다시 가져와 저장하고 스냅샷을 남긴다."""
    rows = conn.execute("SELECT id, keyword FROM keywords").fetchall()
    norm = lambda s: s.replace(" ", "").upper()  # 검색광고 API는 공백을 빼고 돌려준다
    ids = {norm(k): i for i, k in rows}

    stats, trends = {}, {}
    # ponytail: 5개씩 순서대로 호출. 키워드가 수백 개가 되면 호출 간격 조절 필요
    for n in range(0, len(rows), 5):
        chunk = rows[n:n + 5]
        for r in naver.keyword_stats([k for _, k in chunk]):
            if norm(r["keyword"]) in ids:
                stats[ids[norm(r["keyword"])]] = r
        for k, series in naver.monthly_trend([k for _, k in chunk]).items():
            trends[ids[norm(k)]] = series

    blogs, blog_ok = {}, True
    for i, k in rows:
        count = naver.blog_count(k) if blog_ok else None
        blog_ok = count is not None  # 블로그 검색 API가 없으면 한 번만 시도
        if count is not None and stats.get(i, {}).get("monthly_search"):
            blogs[i] = round(count / stats[i]["monthly_search"], 2)

    today = dt.date.today().isoformat()
    with conn:
        for i, _ in rows:
            s, series = stats.get(i, {}), trends.get(i, [])
            ti = trend_index(series)
            conn.execute(
                """UPDATE keywords
                   SET monthly_search = COALESCE(?, monthly_search), comp_idx = COALESCE(?, comp_idx),
                       peak_months = ?, trend_index = ?, blog_ratio = COALESCE(?, blog_ratio)
                   WHERE id = ?""",
                (s.get("monthly_search"), s.get("comp_idx"), peak_months(series) if series else None, ti,
                 blogs.get(i), i),
            )
            conn.execute(
                """INSERT INTO keyword_snapshots (keyword_id, checked_date, monthly_search, comp_idx, trend_index)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT (keyword_id, checked_date) DO UPDATE
                   SET monthly_search = excluded.monthly_search, comp_idx = excluded.comp_idx,
                       trend_index = excluded.trend_index""",
                (i, today, s.get("monthly_search"), s.get("comp_idx"), ti),
            )
    return len(rows)


def collect_news(conn):
    """NEWS_TOPICS 검색어로 최신 뉴스 제목을 모은다. 사고·재난 뉴스는 뺀다."""
    added = 0
    with conn:
        for topic in NEWS_TOPICS:
            for item in naver.news(topic):
                if any(w in item["title"] for w in BLOCKED_WORDS):
                    continue
                added += conn.execute(
                    "INSERT OR IGNORE INTO news_items (topic, title, link, pub_date) VALUES (?, ?, ?, ?)",
                    (topic, item["title"], item["link"], item["pub_date"]),
                ).rowcount
    return added


def collect_instagram(conn):
    """인스타에 올린 글의 조회수를 가져와 stats에 하루치 증가분으로 남긴다."""
    import instagram

    rows = conn.execute("SELECT id, ig_media_id FROM posts WHERE ig_media_id IS NOT NULL").fetchall()
    today = dt.date.today().isoformat()
    with conn:
        for post_id, media_id in rows:
            total = instagram.insights(media_id).get("views", 0)
            # 인스타는 누적값을 주므로, 지금까지 기록한 합계를 빼서 오늘 늘어난 만큼만 저장한다
            conn.execute("DELETE FROM stats WHERE post_id = ? AND record_date = ? AND source = '인스타'", (post_id, today))
            before = conn.execute("SELECT COALESCE(SUM(views), 0) FROM stats WHERE post_id = ? AND source = '인스타'",
                                  (post_id,)).fetchone()[0]
            conn.execute("INSERT INTO stats (post_id, record_date, views, source) VALUES (?, ?, ?, '인스타')",
                         (post_id, today, max(total - before, 0)))
    return len(rows)


def import_revenue(conn, df, date_col, revenue_col, match_col, clicks_col=None):
    """수익 리포트(엑셀/CSV) → stats. 각 행을 상품 URL 또는 키워드로 내 글과 맞춘다.
    (맞춘 행 수, 못 맞춘 행 수)를 돌려준다."""
    import pandas as pd

    posts = conn.execute(
        "SELECT p.id, p.product_url, k.keyword FROM posts p LEFT JOIN keywords k ON k.id = p.keyword_id").fetchall()

    def find_post(text):
        text = str(text)
        for pid, url, kw in posts:
            if url and (url in text or text in url):
                return pid
        for pid, url, kw in posts:
            if kw and kw.replace(" ", "") in text.replace(" ", ""):
                return pid
        return None

    d = pd.DataFrame({
        "post_id": df[match_col].map(find_post),
        "record_date": pd.to_datetime(df[date_col], errors="coerce").dt.date.astype(str),
        "revenue_krw": pd.to_numeric(df[revenue_col].astype(str).str.replace(r"[^0-9.-]", "", regex=True),
                                     errors="coerce").fillna(0),
        "clicks": pd.to_numeric(df[clicks_col], errors="coerce").fillna(0) if clicks_col else 0,
    })
    matched = d.dropna(subset=["post_id"])
    matched = matched[matched["record_date"] != "NaT"]
    grouped = matched.groupby(["post_id", "record_date"], as_index=False)[["revenue_krw", "clicks"]].sum()
    with conn:
        for r in grouped.itertuples(index=False):
            # 같은 날짜 파일을 다시 올려도 두 번 더해지지 않게, 그 날짜의 파일 기록은 바꿔 쓴다
            conn.execute("DELETE FROM stats WHERE post_id = ? AND record_date = ? AND source = '파일'",
                         (int(r.post_id), r.record_date))
            conn.execute("""INSERT INTO stats (post_id, record_date, clicks, revenue_krw, source)
                            VALUES (?, ?, ?, ?, '파일')""",
                         (int(r.post_id), r.record_date, int(r.clicks), int(r.revenue_krw)))
    return len(matched), len(d) - len(matched)


if __name__ == "__main__":
    import recommend

    conn = db.connect()
    print(dt.datetime.now().isoformat(timespec="minutes"))
    print(f"키워드 {refresh_keywords(conn)}개 갱신, 새 뉴스 {collect_news(conn)}건")
    top, warnings = recommend.recommend(conn)
    print(f"추천 {len(top)}개", *warnings, sep="\n  ")
    if naver.load_env().get("IG_ACCESS_TOKEN"):
        print(f"인스타 성과 {collect_instagram(conn)}개 갱신")
