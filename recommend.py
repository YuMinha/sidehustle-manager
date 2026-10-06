"""오늘의 주제 추천: 관심 분야 씨앗 키워드 → 연관 키워드 → 걸러내기 → 상승세·성수기 확인 → 점수순 10개.

python recommend.py   → 추천을 뽑아 출력
"""
import datetime as dt
import math

import ai
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


def blog_weight(ratio):
    """블로그 글 수 ÷ 월 검색량. 낮을수록 새 글이 상위에 오르기 쉽다."""
    if ratio is None:
        return 1.0
    return 1.3 if ratio < 1 else 1.0 if ratio < 3 else 0.7 if ratio < 10 else 0.4


def score(c):
    """검색량(로그) × 광고 경쟁 × 블로그 경쟁 × 상승세 × 성수기 임박 × 뉴스"""
    s = math.log10(c["monthly_search"]) * COMP_WEIGHT[c["comp_idx"]] * blog_weight(c.get("blog_ratio"))
    if c.get("trend_index"):
        s *= 1 + max(-0.5, min(c["trend_index"] - 1, 1))  # 상승세는 -50% ~ +100%까지만 반영
    if c.get("peak_soon"):
        s *= 1.5
    if c.get("news_title"):
        s *= 1.3  # 뉴스발 키워드는 지금 써야 의미가 있다
    return round(s, 2)


def reason(c):
    parts = []
    if c.get("news_title"):
        parts.append(f"뉴스 「{c['news_title']}」 · 빨리 쓰기")
    parts += [f"월 {c['monthly_search']:,}회 검색", f"광고 경쟁 {c['comp_idx']}"]
    if c.get("blog_ratio") is not None:
        parts.append(f"블로그 경쟁률 {c['blog_ratio']}")
    if c.get("trend_index") and c["trend_index"] >= 1.2:
        parts.append(f"평소보다 {c['trend_index']}배 검색 중")
    if c.get("peak_soon"):
        parts.append(f"성수기({c['peak_months']}) 다가옴")
    return " · ".join(parts)


def sellable(r):
    return (r["comp_idx"] in COMP_WEIGHT and r["ad_depth"] >= MIN_AD_DEPTH
            and MIN_SEARCH <= r["monthly_search"] <= MAX_SEARCH)


def news_candidates(conn, seen):
    """최근 3일 뉴스 제목 → Claude가 상품 키워드 추출 → 검색광고 API로 팔리는지 확인."""
    news = [{"title": t, "link": l} for t, l in conn.execute(
        """SELECT title, link FROM news_items WHERE pub_date >= date('now', 'localtime', '-3 days')
           ORDER BY pub_date DESC LIMIT 80""")]
    found = {norm(k["keyword"]): k for k in ai.news_keywords(news)}
    out = []
    names = [k["keyword"] for n, k in found.items() if n not in seen]
    for n in range(0, len(names), 5):
        for r in naver.keyword_stats(names[n:n + 5]):
            k = found.get(norm(r["keyword"]))
            if k and sellable(r) and norm(r["keyword"]) not in seen:
                seen.add(norm(r["keyword"]))
                out.append({**r, "category": "뉴스", "news_title": k["title"], "source_url": k["link"]})
    return out


def recommend(conn, categories=None, today=None):
    """오늘의 추천을 뽑아 저장한다. (추천 목록, 경고 메시지 목록)을 돌려준다."""
    today = today or dt.date.today()
    categories = categories or list(CATEGORY_SEEDS)
    warnings = []
    used = {norm(k) for (k,) in conn.execute(
        "SELECT DISTINCT k.keyword FROM keywords k JOIN posts p ON p.keyword_id = k.id")}

    # 1. 분야별 연관 키워드를 모아 팔리는 상품 키워드만 남긴다
    per_category = math.ceil(CANDIDATES / len(categories))
    candidates, seen = [], set(used)
    for cat in categories:
        seeds = {norm(s) for s in CATEGORY_SEEDS[cat]}
        rows = [{**r, "category": cat} for r in naver.keyword_stats(CATEGORY_SEEDS[cat])
                if sellable(r) and norm(r["keyword"]) not in seen and norm(r["keyword"]) not in seeds]
        rows.sort(key=score, reverse=True)
        for r in rows[:per_category]:
            seen.add(norm(r["keyword"]))
            candidates.append(r)

    # 1-2. 뉴스에서 나온 상품 키워드 (Claude API 키가 있을 때만)
    if naver.load_env().get("ANTHROPIC_API_KEY"):
        try:
            candidates += news_candidates(conn, seen)
        except Exception as e:  # 뉴스 쪽이 실패해도 분야 추천은 그대로 낸다
            warnings.append(f"뉴스 키워드를 뽑지 못했어요: {e}")
    else:
        warnings.append("Claude API 키가 없어 뉴스 키워드는 건너뛰었어요.")

    # 2. 후보의 상승세·성수기(검색어 트렌드)와 블로그 경쟁률(블로그 검색)을 확인
    soon = {(today.month + i - 1) % 12 + 1 for i in range(3)}  # 이번 달 ~ 두 달 뒤
    for n in range(0, len(candidates), 5):
        chunk = candidates[n:n + 5]
        trends = naver.monthly_trend([c["keyword"] for c in chunk], today)
        for c in chunk:
            series = trends.get(c["keyword"], [])
            c["trend_index"] = collect.trend_index(series)
            c["peak_months"] = collect.peak_months(series) if series else None
            c["peak_soon"] = bool(set(collect.peak_month_numbers(series)) & soon)
    blog_ok = True
    for c in candidates:
        count = naver.blog_count(c["keyword"]) if blog_ok else None
        if count is None:
            blog_ok = False  # 블로그 검색 API가 없으면 한 번만 시도하고 끝
        c["blog_ratio"] = round(count / c["monthly_search"], 2) if count is not None else None
    if not blog_ok:
        warnings.append("API HUB에 블로그 검색이 없어 블로그 경쟁률은 빼고 계산했어요.")

    # 3. 점수순 TOP개를 오늘 추천으로 저장 (아직 안 고른 오늘 추천은 새로 뽑은 것으로 바꾼다)
    top = sorted(candidates, key=score, reverse=True)[:TOP]
    with conn:
        conn.execute("DELETE FROM recommendations WHERE rec_date = ? AND picked = 0", (today.isoformat(),))
        conn.executemany(
            """INSERT OR IGNORE INTO recommendations
               (rec_date, keyword, category, monthly_search, comp_idx, trend_index, peak_months,
                blog_ratio, source_url, score, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(today.isoformat(), c["keyword"], c["category"], c["monthly_search"], c["comp_idx"],
              c["trend_index"], c["peak_months"], c["blog_ratio"], c.get("source_url"), score(c), reason(c))
             for c in top],
        )
    return top, warnings


def pick(conn, rec_ids):
    """고른 추천 → 키워드 등록 + 콘텐츠 캘린더에 '기획' 글 추가."""
    with conn:
        for rid in rec_ids:
            r = conn.execute(
                """SELECT keyword, monthly_search, comp_idx, trend_index, peak_months, blog_ratio, source_url,
                          CASE WHEN category = '뉴스' THEN '뉴스에서 나온 추천' ELSE '추천에서 고름' END
                   FROM recommendations WHERE id = ?""",
                (rid,),
            ).fetchone()
            conn.execute(
                """INSERT INTO keywords (keyword, monthly_search, comp_idx, trend_index, peak_months,
                                         blog_ratio, source_url, memo)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (keyword) DO UPDATE
                   SET monthly_search = excluded.monthly_search, comp_idx = excluded.comp_idx,
                       trend_index = excluded.trend_index, peak_months = excluded.peak_months,
                       blog_ratio = excluded.blog_ratio""",
                r,
            )
            kid = conn.execute("SELECT id FROM keywords WHERE keyword = ?", (r[0],)).fetchone()[0]
            conn.execute("INSERT INTO posts (keyword_id, title) VALUES (?, ?)", (kid, f"{r[0]} (제목 미정)"))
            conn.execute("UPDATE recommendations SET picked = 1 WHERE id = ?", (rid,))


if __name__ == "__main__":
    top, warnings = recommend(db.connect())
    for c in top:
        print(f"{score(c):>5}  [{c['category']}] {c['keyword']}  — {reason(c)}")
    for w in warnings:
        print("!", w)
