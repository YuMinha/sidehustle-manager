"""네이버 API 호출.

- 검색광고 API: 키워드 월 검색량·경쟁정도·연관 키워드
- NAVER API HUB: 검색어 트렌드(월별 추이), 뉴스 검색

python naver.py 캠핑의자 텀블러   → 바로 확인
"""
import base64
import datetime as dt
import email.utils
import hashlib
import hmac
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ENV = Path(__file__).with_name(".env")
HUB = "https://naverapihub.apigw.ntruss.com"


def load_env():
    env = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and not key.strip().startswith("#"):
                env[key.strip()] = value.strip()
    return env


def to_int(v):
    """검색량이 아주 적으면 API가 '< 10' 같은 문자열을 준다."""
    return 5 if isinstance(v, str) else int(v)


def keyword_stats(keywords):
    """키워드(최대 5개)와 연관 키워드의 월 검색량·경쟁정도. 검색량 많은 순."""
    env = load_env()
    customer, license_, secret = (env.get(k) for k in
                                  ("SEARCHAD_CUSTOMER_ID", "SEARCHAD_ACCESS_LICENSE", "SEARCHAD_SECRET_KEY"))
    if not (customer and license_ and secret):
        raise RuntimeError(".env에 검색광고 API 키 3개를 넣어 주세요.")

    uri = "/keywordstool"
    timestamp = str(int(time.time() * 1000))
    signature = base64.b64encode(
        hmac.new(secret.encode(), f"{timestamp}.GET.{uri}".encode(), hashlib.sha256).digest()
    ).decode()
    # 검색광고 API는 키워드에 공백을 허용하지 않는다
    hints = ",".join(k.replace(" ", "") for k in keywords[:5])
    req = urllib.request.Request(
        f"https://api.searchad.naver.com{uri}?" + urllib.parse.urlencode({"hintKeywords": hints, "showDetail": 1}),
        headers={"X-Timestamp": timestamp, "X-API-KEY": license_, "X-Customer": customer, "X-Signature": signature},
    )
    with urllib.request.urlopen(req, timeout=15) as res:
        rows = json.load(res)["keywordList"]

    out = [
        {
            "keyword": r["relKeyword"],
            "monthly_search": to_int(r["monthlyPcQcCnt"]) + to_int(r["monthlyMobileQcCnt"]),
            "comp_idx": r["compIdx"],
            "ad_depth": r.get("plAvgDepth") or 0,  # 검색 결과에 붙는 광고 수. 상품 키워드는 보통 5 이상
        }
        for r in rows
    ]
    return sorted(out, key=lambda r: r["monthly_search"], reverse=True)


def _hub(path, body=None):
    env = load_env()
    if not (env.get("NAVER_HUB_CLIENT_ID") and env.get("NAVER_HUB_CLIENT_SECRET")):
        raise RuntimeError(".env에 NAVER API HUB 키 2개를 넣어 주세요.")
    headers = {"X-NCP-APIGW-API-KEY-ID": env["NAVER_HUB_CLIENT_ID"],
               "X-NCP-APIGW-API-KEY": env["NAVER_HUB_CLIENT_SECRET"]}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(HUB + path, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as res:
        return json.load(res)


def monthly_trend(keywords, today=None):
    """키워드(최대 5개)의 최근 3년 월별 검색 추이. {키워드: [ratio, ...]} (오래된 달 → 지난달)"""
    today = today or dt.date.today()
    end = today.replace(day=1) - dt.timedelta(days=1)  # 지난달 말일까지 (이번 달은 아직 덜 찼음)
    start = end.replace(year=end.year - 3, day=1) + dt.timedelta(days=32)
    body = {
        "startDate": start.replace(day=1).isoformat(),
        "endDate": end.isoformat(),
        "timeUnit": "month",
        "keywordGroups": [{"groupName": k, "keywords": [k]} for k in keywords[:5]],
    }
    res = _hub("/search-trend/v1/search", body)
    return {r["title"]: [(d["period"], d["ratio"]) for d in r["data"]] for r in res["results"]}


def blog_count(keyword):
    """네이버 블로그에 이 키워드로 쓰인 글 수. API HUB에 블로그 검색이 없으면 None."""
    try:
        res = _hub("/search/v1/blog?" + urllib.parse.urlencode({"query": keyword, "display": 1}))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return None
        raise
    return res["total"]


def news(query, display=30):
    """최신 뉴스 제목. [{title, link, pub_date}]"""
    res = _hub("/search/v1/news?" + urllib.parse.urlencode({"query": query, "display": display, "sort": "date"}))
    return [
        {
            "title": html.unescape(re.sub(r"<[^>]+>", "", i["title"])),
            "link": i["link"],
            "pub_date": email.utils.parsedate_to_datetime(i["pubDate"]).date().isoformat(),
        }
        for i in res["items"]
    ]


if __name__ == "__main__":
    for r in keyword_stats(sys.argv[1:] or ["캠핑의자"])[:15]:
        print(f"{r['keyword']:<20} {r['monthly_search']:>9,}  경쟁 {r['comp_idx']}")
