"""Claude API: 블로그 초안·인스타 캡션·숏폼 대본 쓰기, 뉴스 제목에서 상품 키워드 뽑기.

.env에 ANTHROPIC_API_KEY가 있어야 한다.
"""
import json

import anthropic

import naver

MODEL = "claude-opus-5-5"
PLACEHOLDER = "[직접 채우기"  # 초안에 이 표시가 남아 있으면 발행으로 못 넘어간다 (schema.sql 트리거)
DISCLOSURE = "이 포스팅은 네이버 쇼핑 커넥트 활동의 일환으로, 판매 발생 시 수수료를 제공받습니다."


def _ask(system, prompt, schema, effort):
    key = naver.load_env().get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(".env에 ANTHROPIC_API_KEY를 넣어 주세요.")
    res = anthropic.Anthropic(api_key=key).beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",  # 안전 분류기가 거절하면 서버가 다른 모델로 다시 시도
        system=system,
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": prompt}],
    )
    if res.stop_reason == "refusal":
        raise RuntimeError("Claude가 이 요청을 처리하지 않았어요. 키워드를 바꿔 보세요.")
    if res.stop_reason == "max_tokens":
        raise RuntimeError("응답이 너무 길어 잘렸어요. 다시 시도해 주세요.")
    return json.loads(next(b.text for b in res.content if b.type == "text"))


DRAFT_SYSTEM = f"""너는 네이버 블로그 쇼핑 리뷰 초안을 돕는 작가다. 블로그 주인이 실제로 써 본 경험을 채워 넣을 수 있는 뼈대를 만든다.

규칙:
- 써 보지 않은 경험, 효과, 수치를 지어내지 않는다. 사용 경험·느낌·사진이 들어갈 자리는 반드시 "{PLACEHOLDER}: 무엇을 쓸지]" 형식으로 비워 둔다. 블로그 초안에 이 자리를 최소 3개 둔다.
- 상품의 일반 정보(용도, 고를 때 볼 점, 계절성)는 써도 된다. 가격·스펙처럼 확인이 필요한 사실도 "{PLACEHOLDER}: 가격 확인]"처럼 비워 둔다.
- 블로그 본문 첫 줄에 광고 표시 문구를 그대로 넣는다: "{DISCLOSURE}"
- 네이버 블로그 말투(친근한 존댓말), 소제목 3~5개, 1,500자 안팎.
- 인스타 캡션은 3~5줄 + 해시태그 5~8개, 첫 줄에 "#광고"를 넣는다.
- 숏폼 대본은 6~8줄, 한 줄 30자 이내, 소리 내어 읽기 좋게. 첫 줄은 시선을 끄는 질문이나 상황."""

DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "블로그 글 제목, 키워드 포함, 40자 이내"},
        "blog_body": {"type": "string"},
        "instagram_caption": {"type": "string"},
        "shorts_lines": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "blog_body", "instagram_caption", "shorts_lines"],
    "additionalProperties": False,
}


def write_drafts(keyword, product_url=None, extra=None):
    """키워드 → {title, blog_body, instagram_caption, shorts_lines}"""
    prompt = f"키워드: {keyword}\n"
    if product_url:
        prompt += f"제휴 상품 링크: {product_url}\n"
    if extra:
        prompt += f"참고: {extra}\n"
    prompt += "이 키워드로 블로그 초안, 인스타 캡션, 숏폼 대본을 써 줘."
    return _ask(DRAFT_SYSTEM, prompt, DRAFT_SCHEMA, effort="medium")


NEWS_SYSTEM = """너는 쇼핑 블로거의 주제 발굴을 돕는다. 뉴스 제목 목록을 보고, 지금 사람들이 검색해서 살 만한 '상품 키워드'를 뽑는다.

규칙:
- 실제로 온라인에서 살 수 있는 상품이나 여행 상품만. 사람·회사·사건 이름은 빼고, 사고·재난·범죄 뉴스에서는 뽑지 않는다.
- 키워드는 네이버에서 실제로 검색할 법한 2~10자 명사 (예: 전기요, 발열내의, 일본여행, 포켓와이파이).
- 같은 뜻은 하나만. 최대 15개."""

NEWS_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string"},
                    "news_index": {"type": "integer", "description": "근거가 된 뉴스 번호"},
                },
                "required": ["keyword", "news_index"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def news_keywords(news):
    """news: [{title, link}] → [{keyword, title, link}]"""
    if not news:
        return []
    listing = "\n".join(f"{i}. {n['title']}" for i, n in enumerate(news))
    items = _ask(NEWS_SYSTEM, f"뉴스 제목:\n{listing}", NEWS_SCHEMA, effort="low")["items"]
    return [
        {"keyword": it["keyword"], "title": news[it["news_index"]]["title"], "link": news[it["news_index"]]["link"]}
        for it in items
        if 0 <= it["news_index"] < len(news)
    ]
