-- 부업 (2차 버전에서 어도비 스톡 추가용)
CREATE TABLE IF NOT EXISTS side_hustles (
    id       INTEGER PRIMARY KEY,
    name     TEXT NOT NULL UNIQUE,
    platform TEXT
);
INSERT OR IGNORE INTO side_hustles (id, name, platform)
VALUES (1, '네이버 브랜드커넥트', '네이버');

-- 판다랭크에서 찾은 키워드
CREATE TABLE IF NOT EXISTS keywords (
    id             INTEGER PRIMARY KEY,
    side_hustle_id INTEGER NOT NULL DEFAULT 1 REFERENCES side_hustles(id),
    keyword        TEXT    NOT NULL UNIQUE,
    monthly_search INTEGER,
    product_count  INTEGER,
    competition    REAL,
    comp_idx       TEXT,  -- 검색광고 API 경쟁정도: 높음/중간/낮음
    peak_months    TEXT,  -- 성수기 (예: '11월, 12월' 또는 '연중')
    trend_index    REAL,  -- 지난달 검색 추이 ÷ 최근 1년 평균. 1보다 크면 오르는 중
    blog_ratio     REAL,  -- 블로그 글 수 ÷ 월 검색량. 낮을수록 새 글이 올라가기 쉽다
    source_url     TEXT,  -- 뉴스에서 나온 키워드면 기사 링크
    memo           TEXT,
    created_at     TEXT    NOT NULL DEFAULT (date('now', 'localtime'))
);

-- 매일 수집한 키워드 수치 (추이 분석용)
CREATE TABLE IF NOT EXISTS keyword_snapshots (
    id             INTEGER PRIMARY KEY,
    keyword_id     INTEGER NOT NULL REFERENCES keywords(id) ON DELETE CASCADE,
    checked_date   TEXT    NOT NULL,
    monthly_search INTEGER,
    comp_idx       TEXT,
    trend_index    REAL,
    UNIQUE (keyword_id, checked_date)
);

-- 매일 뽑은 주제 추천
CREATE TABLE IF NOT EXISTS recommendations (
    id             INTEGER PRIMARY KEY,
    rec_date       TEXT    NOT NULL,
    keyword        TEXT    NOT NULL,
    category       TEXT,
    monthly_search INTEGER,
    comp_idx       TEXT,
    trend_index    REAL,
    peak_months    TEXT,
    score          REAL,
    reason         TEXT,
    blog_ratio     REAL,
    source_url     TEXT,
    picked         INTEGER NOT NULL DEFAULT 0,
    UNIQUE (rec_date, keyword)
);

-- 주제 찾기용 뉴스 제목 (기사 내용은 저장하지 않는다)
CREATE TABLE IF NOT EXISTS news_items (
    id             INTEGER PRIMARY KEY,
    topic          TEXT NOT NULL,
    title          TEXT NOT NULL,
    link           TEXT NOT NULL UNIQUE,
    pub_date       TEXT NOT NULL,
    collected_date TEXT NOT NULL DEFAULT (date('now', 'localtime'))
);

-- 글 (기획 → 작성중 → 발행)
CREATE TABLE IF NOT EXISTS posts (
    id             INTEGER PRIMARY KEY,
    keyword_id     INTEGER REFERENCES keywords(id) ON DELETE SET NULL,
    title          TEXT NOT NULL,
    channel        TEXT NOT NULL DEFAULT '블로그' CHECK (channel IN ('블로그', '인스타')),
    status         TEXT NOT NULL DEFAULT '기획'   CHECK (status IN ('기획', '작성중', '발행')),
    planned_date   TEXT,
    published_date TEXT,
    product_url    TEXT,
    commission_rate REAL,  -- 쇼핑커넥트 수수료율(%)
    draft_body     TEXT,   -- 블로그 초안
    caption        TEXT,   -- 인스타 캡션
    shorts_script  TEXT,   -- 숏폼 대본 (한 줄에 한 문장)
    video_path     TEXT,
    ig_media_id    TEXT
);

-- 글별 성과
CREATE TABLE IF NOT EXISTS stats (
    id          INTEGER PRIMARY KEY,
    post_id     INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    record_date TEXT    NOT NULL,
    views       INTEGER NOT NULL DEFAULT 0,
    clicks      INTEGER NOT NULL DEFAULT 0,
    revenue_krw INTEGER NOT NULL DEFAULT 0,
    source      TEXT  -- 수동 / 파일 / 인스타
);

-- 상태를 '발행'으로 바꾸면 발행일이 비어 있을 때 오늘 날짜를 채운다
CREATE TRIGGER IF NOT EXISTS posts_set_published_date
AFTER UPDATE OF status ON posts
WHEN NEW.status = '발행' AND NEW.published_date IS NULL
BEGIN
    UPDATE posts SET published_date = date('now', 'localtime') WHERE id = NEW.id;
END;

-- 초안에 직접 채울 자리([직접 채우기: ...])가 남아 있으면 발행으로 못 넘어간다
CREATE TRIGGER IF NOT EXISTS posts_block_unfinished_publish
BEFORE UPDATE OF status ON posts
WHEN NEW.status = '발행' AND NEW.draft_body LIKE '%[직접 채우기%'
BEGIN
    SELECT RAISE(ABORT, '초안에 [직접 채우기] 자리가 남아 있어요. 경험과 사진을 채운 뒤 발행하세요.');
END;
