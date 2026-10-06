"""매일 아침 자동 수집: 키워드 검색량·경쟁정도·상승세·성수기 갱신, 뉴스 제목 모으기.

python collect.py   → 한 번 실행 (작업 스케줄러가 매일 이걸 실행한다)
"""
import datetime as dt
import statistics

import db
import naver

# 상품 주제를 찾을 뉴스 검색어. 바꾸고 싶으면 여기만 고치면 된다.
NEWS_TOPICS = ["품절 대란", "인기 상품", "신제품 출시", "여행 수요", "날씨 예보", "유행 아이템"]
# 사고·재난 뉴스는 상품 주제로 쓰지 않는다
BLOCKED_WORDS = ["사고", "사망", "참사", "화재", "재난", "지진", "부상", "숨져", "숨진", "실종", "피해", "붕괴"]


def peak_months(series):
    """월별 추이 → 평균보다 30% 이상 높은 달 상위 2개. 뚜렷한 성수기가 없으면 '연중'."""
    by_month = {}
    for period, ratio in series:
        by_month.setdefault(int(period[5:7]), []).append(ratio)
    avg = {m: statistics.mean(v) for m, v in by_month.items()}
    overall = statistics.mean(avg.values()) if avg else 0
    top = sorted(avg, key=avg.get, reverse=True)[:2]
    top = [m for m in top if overall and avg[m] >= overall * 1.3]
    return ", ".join(f"{m}월" for m in sorted(top)) if top else "연중"


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

    today = dt.date.today().isoformat()
    with conn:
        for i, _ in rows:
            s, series = stats.get(i, {}), trends.get(i, [])
            ti = trend_index(series)
            conn.execute(
                """UPDATE keywords
                   SET monthly_search = COALESCE(?, monthly_search), comp_idx = COALESCE(?, comp_idx),
                       peak_months = ?, trend_index = ?
                   WHERE id = ?""",
                (s.get("monthly_search"), s.get("comp_idx"), peak_months(series) if series else None, ti, i),
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


if __name__ == "__main__":
    conn = db.connect()
    print(f"키워드 {refresh_keywords(conn)}개 갱신, 새 뉴스 {collect_news(conn)}건")
