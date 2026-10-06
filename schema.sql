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
    memo           TEXT,
    created_at     TEXT    NOT NULL DEFAULT (date('now', 'localtime'))
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
    product_url    TEXT
);

-- 글별 성과
CREATE TABLE IF NOT EXISTS stats (
    id          INTEGER PRIMARY KEY,
    post_id     INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    record_date TEXT    NOT NULL,
    views       INTEGER NOT NULL DEFAULT 0,
    clicks      INTEGER NOT NULL DEFAULT 0,
    revenue_krw INTEGER NOT NULL DEFAULT 0
);

-- 상태를 '발행'으로 바꾸면 발행일이 비어 있을 때 오늘 날짜를 채운다
CREATE TRIGGER IF NOT EXISTS posts_set_published_date
AFTER UPDATE OF status ON posts
WHEN NEW.status = '발행' AND NEW.published_date IS NULL
BEGIN
    UPDATE posts SET published_date = date('now', 'localtime') WHERE id = NEW.id;
END;
