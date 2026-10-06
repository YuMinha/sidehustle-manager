import datetime as dt
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

import ai
import collect
import db
import naver
import recommend

st.set_page_config(page_title="부업 관리", page_icon="💰", layout="wide")
conn = st.cache_resource(db.connect)()
today = dt.date.today()
col = st.column_config


def q(sql, params=()):
    return db.query(conn, sql, params)


def as_dates(df, *cols):
    for c in cols:
        df[c] = pd.to_datetime(df[c]).dt.date
    return df


def edit_table(table, df, cols, config, disabled=(), prep=None, key=""):
    """표 편집기 + 저장 버튼. 저장하면 표를 새로 그린다."""
    key = f"{table}{key}-{st.session_state.setdefault('ver', 0)}"
    edited = st.data_editor(
        df, key=key, num_rows="dynamic", hide_index=True,
        column_config={"id": col.NumberColumn("#"), **config},
        disabled=["id", *disabled],
    )
    st.caption("표에서 바로 추가·수정·삭제한 뒤 저장을 누르세요.")
    if st.button("저장", key=key + "-save", type="primary"):
        if prep:
            edited = prep(edited.copy())
        try:
            db.save(conn, table, df, edited, cols)
        except sqlite3.Error as e:
            st.error(f"저장하지 못했어요: {e}")
            return
        st.session_state.ver += 1
        st.rerun()


page = st.sidebar.radio("메뉴", ["오늘 할 일", "오늘의 추천", "초안 작업실", "콘텐츠 캘린더", "성과 입력",
                               "대시보드", "키워드", "뉴스"])
env = naver.load_env()
PHOTO_TYPES = ["jpg", "jpeg", "png", "webp"]


def photos_of(post_id):
    folder = collect.HERE / "media" / str(post_id) / "photos"
    return sorted(p for p in folder.glob("*") if p.suffix.lower().lstrip(".") in PHOTO_TYPES) if folder.exists() else []
st.title(page)

if page == "오늘 할 일":
    st.caption("프로그램이 키워드·뉴스·추천·초안을 맡고, 여기에는 내가 직접 해야 하는 일만 모아요.")
    week_ago = (today - dt.timedelta(days=7)).isoformat()
    todo = []
    n = int(q("""SELECT COUNT(*) AS n FROM recommendations
                 WHERE picked = 0 AND rec_date = (SELECT MAX(rec_date) FROM recommendations)""").n[0])
    if n:
        todo.append(("오늘의 추천", f"추천 {n}개 중 쓸 주제 고르기"))
    for r in q("SELECT title FROM posts WHERE status = '기획' AND draft_body IS NULL").itertuples():
        todo.append(("초안 작업실", f"「{r.title}」 AI 초안 만들기"))
    for r in q("SELECT title, draft_body FROM posts WHERE status <> '발행' AND instr(draft_body, ?) > 0",
               (ai.PLACEHOLDER,)).itertuples():
        todo.append(("초안 작업실", f"「{r.title}」 직접 채울 자리 {r.draft_body.count(ai.PLACEHOLDER)}곳 채우기 (경험·사진)"))
    for r in q("""SELECT title FROM posts WHERE status <> '발행' AND draft_body IS NOT NULL
                  AND instr(draft_body, ?) = 0""", (ai.PLACEHOLDER,)).itertuples():
        todo.append(("초안 작업실", f"「{r.title}」 체크리스트 확인하고 블로그에 발행하기"))
    for r in q("SELECT title, planned_date FROM posts WHERE status <> '발행' AND planned_date < ?",
               (today.isoformat(),)).itertuples():
        todo.append(("콘텐츠 캘린더", f"「{r.title}」 발행 예정일({r.planned_date}) 지남"))
    for r in q("""SELECT p.title FROM posts p WHERE p.status = '발행' AND NOT EXISTS
                  (SELECT 1 FROM stats s WHERE s.post_id = p.id AND s.record_date >= ?)""", (week_ago,)).itertuples():
        todo.append(("성과 입력", f"「{r.title}」 이번 주 조회수 입력"))
    published = int(q("SELECT COUNT(*) AS n FROM posts WHERE status = '발행'").n[0])
    if published and q("SELECT 1 FROM stats WHERE source = '파일' AND record_date >= ?", (week_ago,)).empty:
        todo.append(("성과 입력", "브랜드커넥트 수익 리포트 올리기 (주 1회)"))

    if todo:
        for where, what in todo:
            st.checkbox(f"{what}  ·  `{where}`", key=f"todo-{what}")
    else:
        st.success("지금 할 일이 없어요. 내일 아침 새 추천이 올라와요.")

    missing = [name for key, name in [("SEARCHAD_SECRET_KEY", "네이버 검색광고"), ("NAVER_HUB_CLIENT_ID", "NAVER API HUB"),
                                      ("ANTHROPIC_API_KEY", "Claude API (초안·뉴스 키워드)"),
                                      ("IG_ACCESS_TOKEN", "인스타그램 (릴스 올리기·성과)")] if not env.get(key)]
    if missing:
        st.caption("아직 연결 안 된 기능: " + ", ".join(missing) + " — README의 API 키 안내를 보세요.")

elif page == "오늘의 추천":
    st.caption("관심 분야에서 팔리는 상품 키워드 중 검색은 꾸준하고, 요즘 오르거나 성수기가 다가오는 것을 골라요. "
               "매일 아침 자동 수집 때도 새로 뽑아요.")
    cats = st.multiselect("관심 분야", list(recommend.CATEGORY_SEEDS), default=list(recommend.CATEGORY_SEEDS))
    if st.button("추천 새로 받기", type="primary", disabled=not cats):
        try:
            with st.spinner("네이버에서 키워드를 훑는 중... (10~30초 걸려요)"):
                _, warnings = recommend.recommend(conn, cats)
            for w in warnings:
                st.warning(w)
            st.session_state.ver = st.session_state.get("ver", 0) + 1
        except Exception as e:
            st.error(f"추천을 받지 못했어요: {e}")

    recs = q("""SELECT id, keyword, category, reason, score, rec_date FROM recommendations
                WHERE picked = 0 AND rec_date = (SELECT MAX(rec_date) FROM recommendations)
                ORDER BY score DESC""")
    if recs.empty:
        st.info("아직 추천이 없어요. `추천 새로 받기`를 눌러 보세요.")
    else:
        st.subheader(f"{recs['rec_date'].iloc[0]} 추천")
        recs.insert(0, "pick", False)
        picked = st.data_editor(
            recs.drop(columns="rec_date"), hide_index=True, key=f"recs-{st.session_state.get('ver', 0)}",
            disabled=["keyword", "category", "reason", "score"],
            column_config={
                "id": None,
                "pick": col.CheckboxColumn("쓸래요"),
                "keyword": col.TextColumn("키워드"),
                "category": col.TextColumn("분야"),
                "reason": col.TextColumn("추천 이유", width="large"),
                "score": col.NumberColumn("점수", format="%.1f"),
            },
        )
        if st.button("고른 키워드로 글 만들기"):
            ids = [int(i) for i in picked.loc[picked["pick"], "id"]]
            if ids:
                recommend.pick(conn, ids)
                st.session_state.ver = st.session_state.get("ver", 0) + 1
                st.success(f"{len(ids)}개를 키워드에 등록하고 콘텐츠 캘린더에 '기획' 글로 넣었어요.")
                st.rerun()

elif page == "초안 작업실":
    posts = q("""SELECT p.id, p.title, p.status, k.keyword, k.peak_months FROM posts p
                 LEFT JOIN keywords k ON k.id = p.keyword_id WHERE p.status <> '발행' ORDER BY p.id DESC""")
    if posts.empty:
        st.info("발행 전 글이 없어요. `오늘의 추천`에서 주제를 고르면 여기로 와요.")
        st.stop()
    labels = {int(r.id): f"[{r.status}] {r.title}" for r in posts.itertuples()}
    pid = st.selectbox("글", list(labels), format_func=labels.get)
    sel = posts[posts.id == pid].iloc[0]
    title, product_url, commission, body, caption, script, video_path, ig_id = conn.execute(
        """SELECT title, product_url, commission_rate, draft_body, caption, shorts_script, video_path, ig_media_id
           FROM posts WHERE id = ?""", (pid,)).fetchone()
    k = f"{pid}-{st.session_state.get('ver', 0)}"

    c1, c2 = st.columns([3, 1])
    product_url = c1.text_input("쇼핑커넥트 제휴 링크", product_url or "", key=f"url-{k}")
    commission = c2.number_input("수수료율(%)", value=float(commission or 0), step=0.5, key=f"cr-{k}")

    if st.button("AI로 초안 만들기" if not body else "AI로 초안 다시 만들기", type="secondary" if body else "primary",
                 help="블로그 초안·인스타 캡션·숏폼 대본을 한 번에 써요. 다시 만들면 지금 초안을 덮어써요."):
        try:
            with st.spinner("Claude가 초안을 쓰는 중... (30초~1분)"):
                extra = f"성수기 {sel.peak_months}" if sel.peak_months else None
                d = ai.write_drafts(sel.keyword or title, product_url or None, extra)
            with conn:
                conn.execute("""UPDATE posts SET title = ?, draft_body = ?, caption = ?, shorts_script = ?,
                                product_url = ?, commission_rate = ?, status = '작성중' WHERE id = ?""",
                             (d["title"], d["blog_body"], d["instagram_caption"], "\n".join(d["shorts_lines"]),
                              product_url or None, commission or None, pid))
            st.session_state.ver = st.session_state.get("ver", 0) + 1
            st.rerun()
        except Exception as e:
            st.error(f"초안을 만들지 못했어요: {e}")

    blog_tab, insta_tab, shorts_tab = st.tabs(["블로그 초안", "인스타 캡션", "숏폼 대본·영상"])
    with blog_tab:
        if body:
            st.caption(f"`{ai.PLACEHOLDER}: ...]` 자리 {body.count(ai.PLACEHOLDER)}곳 남음. "
                       "직접 써 본 경험과 사진으로 바꿔 주세요.")
        new_title = st.text_input("제목", title, key=f"title-{k}")
        new_body = st.text_area("본문", body or "", height=480, key=f"body-{k}")
    with insta_tab:
        new_caption = st.text_area("캡션", caption or "", height=220, key=f"cap-{k}")
    with shorts_tab:
        new_script = st.text_area("대본 (한 줄에 한 문장)", script or "", height=220, key=f"script-{k}")
        photos = photos_of(pid)
        uploads = st.file_uploader("내가 찍은 사진 (영상과 블로그에 쓸 것)", type=PHOTO_TYPES,
                                   accept_multiple_files=True, key=f"up-{k}")
        if uploads:
            folder = collect.HERE / "media" / str(pid) / "photos"
            folder.mkdir(parents=True, exist_ok=True)
            for f in uploads:
                (folder / Path(f.name).name).write_bytes(f.getvalue())
            st.session_state.ver = st.session_state.get("ver", 0) + 1
            st.rerun()
        if photos:
            st.image([str(p) for p in photos], width=120)
        if st.button("숏폼 영상 만들기", disabled=not new_script.strip()):
            try:
                import video
                with st.spinner("목소리·자막을 입혀 영상 만드는 중..."):
                    out = video.make_video(pid, new_script.splitlines(), photos)
                with conn:
                    conn.execute("UPDATE posts SET video_path = ?, shorts_script = ? WHERE id = ?",
                                 (str(out), new_script, pid))
                video_path = str(out)
            except Exception as e:
                st.error(f"영상을 만들지 못했어요: {e}")
        if video_path and Path(video_path).exists():
            st.video(video_path)
            if ig_id:
                st.caption(f"인스타에 올렸어요 (게시물 ID {ig_id}).")
            elif st.button("인스타 릴스로 올리기", disabled=not env.get("IG_ACCESS_TOKEN"),
                           help="인스타 키가 있어야 해요. 네이버 클립은 직접 올려 주세요."):
                try:
                    import instagram
                    with st.spinner("인스타에 올리는 중... (1~3분)"):
                        media_id = instagram.publish_reel(video_path, new_caption)
                    with conn:
                        conn.execute("UPDATE posts SET ig_media_id = ? WHERE id = ?", (media_id, pid))
                    st.success("릴스를 올렸어요.")
                except Exception as e:
                    st.error(f"올리지 못했어요: {e}")

    if st.button("저장"):
        with conn:
            conn.execute("""UPDATE posts SET title = ?, draft_body = ?, caption = ?, shorts_script = ?,
                            product_url = ?, commission_rate = ? WHERE id = ?""",
                         (new_title, new_body or None, new_caption or None, new_script or None,
                          product_url or None, commission or None, pid))
        st.toast("저장했어요")

    st.subheader("발행 체크리스트")
    checks = [
        (ai.DISCLOSURE in new_body, "본문에 광고 표시 문구가 있어요"),
        (bool(product_url), "쇼핑커넥트 제휴 링크를 넣었어요"),
        (bool(new_body) and ai.PLACEHOLDER not in new_body, "직접 채울 자리를 모두 채웠어요 (경험·사진)"),
        (bool(photos_of(pid)), "직접 찍은 사진이 있어요"),
    ]
    for ok, text in checks:
        st.markdown(f"{'✅' if ok else '⬜'} {text}")
    if not checks[0][0]:
        st.code(ai.DISCLOSURE, language=None)
    st.caption("본문을 복사해 네이버 블로그에 직접 올린 뒤 아래 버튼을 누르세요.")
    if st.button("블로그에 발행했어요", type="primary", disabled=not all(ok for ok, _ in checks)):
        try:
            with conn:
                conn.execute("""UPDATE posts SET title = ?, draft_body = ?, caption = ?, shorts_script = ?,
                                product_url = ?, commission_rate = ?, status = '발행' WHERE id = ?""",
                             (new_title, new_body, new_caption or None, new_script or None,
                              product_url, commission or None, pid))
            st.session_state.ver = st.session_state.get("ver", 0) + 1
            st.rerun()
        except sqlite3.IntegrityError as e:
            st.error(str(e))

elif page == "대시보드":
    month = today.strftime("%Y-%m")
    m = q("""SELECT COALESCE(SUM(revenue_krw), 0) AS revenue,
                    COALESCE(SUM(views), 0)       AS views,
                    COALESCE(SUM(clicks), 0)      AS clicks
             FROM stats WHERE strftime('%Y-%m', record_date) = ?""", (month,)).iloc[0]
    c1, c2, c3 = st.columns(3)
    c1.metric(f"{today.month}월 수익", f"{m.revenue:,}원")
    c2.metric(f"{today.month}월 조회수", f"{m.views:,}")
    c3.metric(f"{today.month}월 링크 클릭", f"{m.clicks:,}")

    sunday = today + dt.timedelta(days=6 - today.weekday())
    st.subheader("이번 주 할 일")
    st.caption("이번 주 일요일까지 발행 예정인 글 (밀린 글 포함)")
    todo = q("""SELECT p.planned_date AS 발행예정일, p.title AS 제목, p.channel AS 채널,
                       p.status AS 상태, k.keyword AS 키워드
                FROM posts p LEFT JOIN keywords k ON k.id = p.keyword_id
                WHERE p.status <> '발행' AND p.planned_date <= ?
                ORDER BY p.planned_date""", (sunday.isoformat(),))
    if len(todo):
        st.dataframe(todo, hide_index=True)
    else:
        st.info("이번 주 예정된 글이 없어요.")

    left, right = st.columns(2)
    with left:
        st.subheader("수익 상위 글 5개")
        st.dataframe(q("""SELECT p.title AS 제목, p.channel AS 채널, SUM(s.revenue_krw) AS 수익
                          FROM posts p JOIN stats s ON s.post_id = p.id
                          GROUP BY p.id ORDER BY 수익 DESC LIMIT 5"""), hide_index=True)
        st.subheader("키워드별 수익")
        st.dataframe(q("""SELECT k.keyword AS 키워드,
                                 COUNT(DISTINCT p.id) AS 글수,
                                 SUM(s.revenue_krw)   AS 총수익
                          FROM keywords k
                          JOIN posts p ON p.keyword_id = k.id
                          JOIN stats s ON s.post_id = p.id
                          GROUP BY k.keyword ORDER BY 총수익 DESC"""), hide_index=True)
    with right:
        st.subheader("월별 수익")
        monthly = q("""SELECT strftime('%Y-%m', record_date) AS 월, SUM(revenue_krw) AS 수익
                       FROM stats GROUP BY 월 ORDER BY 월""")
        if len(monthly):
            st.bar_chart(monthly, x="월", y="수익")
        else:
            st.info("성과 기록이 아직 없어요.")

elif page == "키워드":
    with st.expander("연관 키워드 찾기 (네이버 검색광고)", expanded=True):
        with st.form("related_form"):
            seed = st.text_input("씨앗 키워드", placeholder="캠핑의자")
            if st.form_submit_button("찾기") and seed:
                try:
                    st.session_state.related = naver.keyword_stats([seed])[:100]
                except Exception as e:
                    st.error(f"가져오지 못했어요: {e}")
        if "related" in st.session_state:
            rel = pd.DataFrame(st.session_state.related)
            rel.insert(0, "add", False)
            picked = st.data_editor(
                rel, hide_index=True, key="related_table", disabled=["keyword", "monthly_search", "comp_idx"],
                column_config={
                    "add": col.CheckboxColumn("추가"),
                    "keyword": col.TextColumn("키워드"),
                    "monthly_search": col.NumberColumn("월 검색량", format="%d"),
                    "comp_idx": col.TextColumn("경쟁"),
                },
            )
            if st.button("선택한 키워드 추가", type="primary"):
                rows = picked[picked["add"]]
                with conn:
                    conn.executemany(
                        """INSERT INTO keywords (keyword, monthly_search, comp_idx) VALUES (?, ?, ?)
                           ON CONFLICT (keyword) DO UPDATE
                           SET monthly_search = excluded.monthly_search, comp_idx = excluded.comp_idx""",
                        rows[["keyword", "monthly_search", "comp_idx"]].itertuples(index=False),
                    )
                del st.session_state.related
                st.session_state.ver = st.session_state.get("ver", 0) + 1
                st.rerun()

    df = q("""SELECT k.id, k.keyword, k.monthly_search, k.comp_idx, k.blog_ratio, k.trend_index, k.peak_months,
                     k.product_count, k.competition,
                     EXISTS (SELECT 1 FROM posts p WHERE p.keyword_id = k.id) AS used, k.memo
              FROM keywords k
              ORDER BY CASE k.comp_idx WHEN '낮음' THEN 0 WHEN '중간' THEN 1 WHEN '높음' THEN 2 ELSE 3 END,
                       k.monthly_search DESC""")
    df["used"] = df["used"].astype(bool)

    left, right = st.columns([3, 1])
    if left.toggle("안 쓴 키워드만"):
        df = df[~df["used"]]
    if right.button("키워드 새로고침", help="검색량·경쟁·상승세·성수기를 네이버에서 다시 가져와요. 매일 아침 자동으로도 돌아요"):
        try:
            with st.spinner("네이버에서 가져오는 중..."):
                collect.refresh_keywords(conn)
            st.session_state.ver = st.session_state.get("ver", 0) + 1
            st.rerun()
        except Exception as e:
            st.error(f"가져오지 못했어요: {e}")

    def fill_competition(d):
        # 경쟁률을 비워 두면 상품수 ÷ 월 검색량으로 채운다
        auto = (d["product_count"] / d["monthly_search"]).round(2)
        d["competition"] = d["competition"].fillna(auto)
        return d

    edit_table(
        "keywords", df,
        ["keyword", "monthly_search", "comp_idx", "product_count", "competition", "memo"],
        {
            "keyword": col.TextColumn("키워드", required=True),
            "monthly_search": col.NumberColumn("월 검색량", format="%d"),
            "comp_idx": col.SelectboxColumn("경쟁", options=["낮음", "중간", "높음"], help="네이버 검색광고 경쟁정도"),
            "blog_ratio": col.NumberColumn("블로그 경쟁률", format="%.2f", help="블로그 글 수 ÷ 월 검색량. 낮을수록 좋아요"),
            "trend_index": col.NumberColumn("상승세", format="%.2f", help="지난달 ÷ 최근 1년 평균. 1보다 크면 오르는 중"),
            "peak_months": col.TextColumn("성수기", help="최근 3년 중 검색이 몰리는 달"),
            "product_count": col.NumberColumn("상품수", format="%d", help="판다랭크에서 본 값 (선택)"),
            "competition": col.NumberColumn("경쟁률", help="상품수 ÷ 월 검색량. 비우면 자동 계산", format="%.2f"),
            "used": col.CheckboxColumn("사용함", help="이 키워드로 쓴 글이 있음"),
            "memo": col.TextColumn("메모"),
        },
        disabled=["used", "blog_ratio", "trend_index", "peak_months"], prep=fill_competition,
    )

elif page == "뉴스":
    st.caption("상품 주제를 찾기 위한 최신 뉴스 제목이에요. 사고·재난 뉴스는 빼고 모아요. 기사 내용은 글에 옮기지 마세요.")
    if st.button("지금 뉴스 모으기"):
        try:
            with st.spinner("뉴스 모으는 중..."):
                st.toast(f"새 뉴스 {collect.collect_news(conn)}건")
        except Exception as e:
            st.error(f"가져오지 못했어요: {e}")
    news = q("""SELECT pub_date, topic, title, link FROM news_items
                WHERE pub_date >= date('now', 'localtime', '-7 days')
                ORDER BY pub_date DESC, id DESC""")
    topics = st.multiselect("검색어", collect.NEWS_TOPICS, default=collect.NEWS_TOPICS)
    st.dataframe(
        news[news["topic"].isin(topics)], hide_index=True,
        column_config={
            "pub_date": col.TextColumn("날짜"),
            "topic": col.TextColumn("검색어"),
            "title": col.TextColumn("제목", width="large"),
            "link": col.LinkColumn("기사", display_text="열기"),
        },
    )

elif page == "콘텐츠 캘린더":
    kw = q("SELECT id, keyword FROM keywords ORDER BY keyword")
    kw_names = dict(zip(kw["id"], kw["keyword"]))

    df = as_dates(q("""SELECT id, keyword_id, title, channel, status, planned_date, published_date, product_url
                       FROM posts ORDER BY planned_date IS NULL, planned_date"""),
                  "planned_date", "published_date")
    df["keyword_id"] = df["keyword_id"].astype("Int64")

    counts = df["status"].value_counts()
    for c, s in zip(st.columns(3), ["기획", "작성중", "발행"]):
        c.metric(s, int(counts.get(s, 0)))

    f1, f2 = st.columns(2)
    channels = f1.multiselect("채널", ["블로그", "인스타"], default=["블로그", "인스타"])
    statuses = f2.multiselect("상태", ["기획", "작성중", "발행"], default=["기획", "작성중", "발행"])
    df = df[df["channel"].isin(channels) & df["status"].isin(statuses)]

    edit_table(
        "posts", df,
        ["keyword_id", "title", "channel", "status", "planned_date", "published_date", "product_url"],
        {
            "keyword_id": col.SelectboxColumn("키워드", options=list(kw_names), format_func=lambda i: kw_names.get(i, "")),
            "title": col.TextColumn("제목", required=True, width="large"),
            "channel": col.SelectboxColumn("채널", options=["블로그", "인스타"], default="블로그", required=True),
            "status": col.SelectboxColumn("상태", options=["기획", "작성중", "발행"], default="기획", required=True),
            "planned_date": col.DateColumn("발행 예정일", format="YYYY-MM-DD"),
            "published_date": col.DateColumn("발행일", format="YYYY-MM-DD", help="상태를 발행으로 바꾸면 자동으로 오늘"),
            "product_url": col.LinkColumn("연결 상품"),
        },
    )

elif page == "성과 입력":
    with st.expander("수익 리포트 파일 올리기 (브랜드커넥트 엑셀·CSV)"):
        f = st.file_uploader("리포트 파일", type=["csv", "xlsx"])
        if f:
            try:
                report = pd.read_csv(f) if f.name.endswith(".csv") else pd.read_excel(f)
            except Exception as e:
                st.error(f"파일을 읽지 못했어요: {e}")
                st.stop()
            st.dataframe(report.head(), hide_index=True)
            cols = list(report.columns)
            a, b, c, d = st.columns(4)
            date_col = a.selectbox("날짜 열", cols)
            revenue_col = b.selectbox("수익 열", cols, index=min(1, len(cols) - 1))
            match_col = c.selectbox("상품(URL·이름) 열", cols, index=min(2, len(cols) - 1),
                                    help="내 글의 제휴 링크나 키워드와 맞춰 볼 열")
            clicks_col = d.selectbox("클릭 열 (선택)", [None] + cols)
            if st.button("가져오기", type="primary"):
                ok, missed = collect.import_revenue(conn, report, date_col, revenue_col, match_col, clicks_col)
                st.success(f"{ok}행을 내 글과 맞춰 저장했어요."
                           + (f" {missed}행은 맞는 글이 없어 건너뛰었어요." if missed else ""))

    posts = q("SELECT id, title, channel FROM posts ORDER BY id DESC")
    if posts.empty:
        st.info("콘텐츠 캘린더에서 글을 먼저 추가하세요.")
        st.stop()
    labels = {r.id: f"[{r.channel}] {r.title}" for r in posts.itertuples()}
    post_id = st.selectbox("글", list(labels), format_func=labels.get)

    df = as_dates(q("""SELECT id, record_date, views, clicks, revenue_krw
                       FROM stats WHERE post_id = ? ORDER BY record_date""", (post_id,)),
                  "record_date")
    c1, c2, c3 = st.columns(3)
    c1.metric("누적 조회수", f"{int(df['views'].sum()):,}")
    c2.metric("누적 클릭", f"{int(df['clicks'].sum()):,}")
    c3.metric("누적 수익", f"{int(df['revenue_krw'].sum()):,}원")

    def attach_post(d):
        d["post_id"] = post_id
        return d

    edit_table(
        "stats", df,
        ["post_id", "record_date", "views", "clicks", "revenue_krw"],
        {
            "record_date": col.DateColumn("날짜", format="YYYY-MM-DD", default=today, required=True),
            "views": col.NumberColumn("조회수", min_value=0, default=0, format="%d"),
            "clicks": col.NumberColumn("링크 클릭", min_value=0, default=0, format="%d"),
            "revenue_krw": col.NumberColumn("수익(원)", min_value=0, default=0, format="%d"),
        },
        prep=attach_post, key=str(post_id),
    )
