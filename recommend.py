"""오늘의 주제 추천: 관심 분야 씨앗 키워드 → 연관 키워드 → 걸러내기 → 상승세·성수기 확인 → 점수순 10개.

python recommend.py   → 추천을 뽑아 출력
"""
import datetime as dt
import math

import collect
import db
import naver

# 분야별 씨앗 키워드. 여기서 연관 키워드 수백 개가 나온다. 분야를 더하거나 바꾸려면 여기만 고친다.
CATEGORY_SEEDS = {
    "생활·주방": ["생활용품", "주방용품", "청소용품"],
    "가전·디지털": ["소형가전", "생활가전", "전자기기"],
    "캠핑·레저": ["캠핑용품", "등산용품", "낚시용품"],
    "뷰티": ["스킨케어", "화장품", "헤어용품"],
    "건강·식품": ["건강식품", "영양제", "간식"],
    "육아": ["육아용품", "유아용품"],
    "인테리어": ["인테리어소품", "수납용품"],
    "패션잡화": ["가방", "신발", "모자"],
    "반려동물": ["강아지용품", "고양이용품"],
    "여행": ["여행용품", "여행준비물"],
}
# 검색이 너무 적으면 안 팔리고, 너무 많으면 새 블로그가 상위에 못 올라간다
MIN_SEARCH, MAX_SEARCH = 1_000, 50_000
# 광고가 5개 이상 붙는 키워드만 '팔리는 상품'으로 본다 (119안심콜 같은 비상품 키워드는 0~2)
MIN_AD_DEPTH = 5
COMP_WEIGHT = {"낮음": 1.0, "중간": 0.8, "높음": 0.5}  # 광고 경쟁이 셀수록 감점
CANDIDATES = 40  # 트렌드까지 확인할 후보 수 (API 호출 수를 정한다)
TOP = 10


def norm(s):
    return s.replace(" ", "").upper()


def score(c):
    """검색량(로그) × 경쟁 가중치 × 상승세 보너스 × 성수기 임박 보너스"""
    s = math.log10(c["monthly_search"]) * COMP_WEIGHT[c["comp_idx"]]
    if c.get("trend_index"):
        s *= 1 + max(-0.5, min(c["trend_index"] - 1, 1))  # 상승세는 -50% ~ +100%까지만 반영
    if c.get("peak_soon"):
        s *= 1.5
    return round(s, 2)


def reason(c):
    parts = [f"월 {c['monthly_search']:,}회 검색", f"경쟁 {c['comp_idx']}"]
    if c.get("trend_index") and c["trend_index"] >= 1.2:
        parts.append(f"평소보다 {c['trend_index']}배 검색 중")
    if c.get("peak_soon"):
        parts.append(f"성수기({c['peak_months']}) 다가옴")
    return " · ".join(parts)


def recommend(conn, categories=None, today=None):
    today = today or dt.date.today()
    categories = categories or list(CATEGORY_SEEDS)
    used = {norm(k) for (k,) in conn.execute(
        "SELECT DISTINCT k.keyword FROM keywords k JOIN posts p ON p.keyword_id = k.id")}

    # 1. 분야별 연관 키워드를 모아 검색량·경쟁으로 거른다
    per_category = math.ceil(CANDIDATES / len(categories))
    candidates, seen = [], set(used)
    for cat in categories:
        seeds = {norm(s) for s in CATEGORY_SEEDS[cat]}
        rows = [
            {**r, "category": cat}
            for r in naver.keyword_stats(CATEGORY_SEEDS[cat])
            if r["comp_idx"] in COMP_WEIGHT and r["ad_depth"] >= MIN_AD_DEPTH
            and MIN_SEARCH <= r["monthly_search"] <= MAX_SEARCH
            and norm(r["keyword"]) not in seen and norm(r["keyword"]) not in seeds
        ]
        rows.sort(key=score, reverse=True)
        for r in rows[:per_category]:
            seen.add(norm(r["keyword"]))
            candidates.append(r)

    # 2. 후보의 상승세·성수기를 검색어 트렌드로 확인
    soon = {(today.month + i - 1) % 12 + 1 for i in range(3)}  # 이번 달 ~ 두 달 뒤
    for n in range(0, len(candidates), 5):
        chunk = candidates[n:n + 5]
        trends = naver.monthly_trend([c["keyword"] for c in chunk], today)
        for c in chunk:
            series = trends.get(c["keyword"], [])
            c["trend_index"] = collect.trend_index(series)
            c["peak_months"] = collect.peak_months(series) if series else None
            c["peak_soon"] = bool(set(collect.peak_month_numbers(series)) & soon)

    # 3. 점수순 TOP개를 오늘 추천으로 저장 (아직 안 고른 오늘 추천은 새로 뽑은 것으로 바꾼다)
    top = sorted(candidates, key=score, reverse=True)[:TOP]
    with conn:
        conn.execute("DELETE FROM recommendations WHERE rec_date = ? AND picked = 0", (today.isoformat(),))
        conn.executemany(
            """INSERT OR IGNORE INTO recommendations
               (rec_date, keyword, category, monthly_search, comp_idx, trend_index, peak_months, score, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(today.isoformat(), c["keyword"], c["category"], c["monthly_search"], c["comp_idx"],
              c["trend_index"], c["peak_months"], score(c), reason(c)) for c in top],
        )
    return top


def pick(conn, rec_ids):
    """고른 추천 → 키워드 등록 + 콘텐츠 캘린더에 '기획' 글 추가."""
    with conn:
        for rid in rec_ids:
            r = conn.execute(
                "SELECT keyword, monthly_search, comp_idx, trend_index, peak_months FROM recommendations WHERE id = ?",
                (rid,),
            ).fetchone()
            conn.execute(
                """INSERT INTO keywords (keyword, monthly_search, comp_idx, trend_index, peak_months, memo)
                   VALUES (?, ?, ?, ?, ?, '추천에서 고름')
                   ON CONFLICT (keyword) DO UPDATE
                   SET monthly_search = excluded.monthly_search, comp_idx = excluded.comp_idx,
                       trend_index = excluded.trend_index, peak_months = excluded.peak_months""",
                r,
            )
            kid = conn.execute("SELECT id FROM keywords WHERE keyword = ?", (r[0],)).fetchone()[0]
            conn.execute("INSERT INTO posts (keyword_id, title) VALUES (?, ?)", (kid, f"{r[0]} (제목 미정)"))
            conn.execute("UPDATE recommendations SET picked = 1 WHERE id = ?", (rid,))


if __name__ == "__main__":
    for c in recommend(db.connect()):
        print(f"{score(c):>5}  [{c['category']}] {c['keyword']}  — {reason(c)}")
