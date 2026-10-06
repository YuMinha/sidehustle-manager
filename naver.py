"""네이버 검색광고 API로 키워드 월 검색량·경쟁정도를 가져온다.

python naver.py 캠핑의자 텀블러   → 바로 확인
"""
import base64
import hashlib
import hmac
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ENV = Path(__file__).with_name(".env")


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
        }
        for r in rows
    ]
    return sorted(out, key=lambda r: r["monthly_search"], reverse=True)


if __name__ == "__main__":
    for r in keyword_stats(sys.argv[1:] or ["캠핑의자"])[:15]:
        print(f"{r['keyword']:<20} {r['monthly_search']:>9,}  경쟁 {r['comp_idx']}")
