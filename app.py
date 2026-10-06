import datetime as dt
import sqlite3

import pandas as pd
import streamlit as st

import db
import naver

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


page = st.sidebar.radio("메뉴", ["대시보드", "키워드", "콘텐츠 캘린더", "성과 입력"])
st.title(page)

if page == "대시보드":
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

    df = q("""SELECT k.id, k.keyword, k.monthly_search, k.comp_idx, k.product_count, k.competition,
                     EXISTS (SELECT 1 FROM posts p WHERE p.keyword_id = k.id) AS used, k.memo
              FROM keywords k
              ORDER BY CASE k.comp_idx WHEN '낮음' THEN 0 WHEN '중간' THEN 1 WHEN '높음' THEN 2 ELSE 3 END,
                       k.monthly_search DESC""")
    df["used"] = df["used"].astype(bool)

    left, right = st.columns([3, 1])
    if left.toggle("안 쓴 키워드만"):
        df = df[~df["used"]]
    if right.button("검색량 새로고침", help="저장된 키워드의 월 검색량·경쟁을 네이버에서 다시 가져와요"):
        names = [r[0] for r in conn.execute("SELECT keyword FROM keywords")]
        try:
            # ponytail: 5개씩 순서대로 호출, 키워드가 수백 개면 호출 간격 조절 필요
            with conn:
                for i in range(0, len(names), 5):
                    for r in naver.keyword_stats(names[i:i + 5]):
                        conn.execute(
                            """UPDATE keywords SET monthly_search = ?, comp_idx = ?
                               WHERE upper(replace(keyword, ' ', '')) = upper(?)""",
                            (r["monthly_search"], r["comp_idx"], r["keyword"]),
                        )
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
            "product_count": col.NumberColumn("상품수", format="%d", help="판다랭크에서 본 값 (선택)"),
            "competition": col.NumberColumn("경쟁률", help="상품수 ÷ 월 검색량. 비우면 자동 계산", format="%.2f"),
            "used": col.CheckboxColumn("사용함", help="이 키워드로 쓴 글이 있음"),
            "memo": col.TextColumn("메모"),
        },
        disabled=["used"], prep=fill_competition,
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
