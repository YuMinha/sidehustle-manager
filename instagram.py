"""Instagram Graph API: 릴스 올리기, 게시물 성과(조회수) 가져오기.

필요한 것: 비즈니스/크리에이터 계정 + Meta 개발자 앱에서 받은 토큰.
.env:
    IG_USER_ID=        인스타 비즈니스 계정 ID
    IG_ACCESS_TOKEN=   장기 액세스 토큰 (instagram_content_publish, instagram_manage_insights 권한)

ponytail: 실제 계정으로 아직 시험하지 못했다. 첫 업로드 때 오류가 나면 응답 메시지대로 고친다.
"""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

import naver

GRAPH = "https://graph.facebook.com/v23.0"
RUPLOAD = "https://rupload.facebook.com/ig-api-upload/v23.0"


def _env():
    env = naver.load_env()
    if not (env.get("IG_USER_ID") and env.get("IG_ACCESS_TOKEN")):
        raise RuntimeError(".env에 IG_USER_ID와 IG_ACCESS_TOKEN을 넣어 주세요.")
    return env["IG_USER_ID"], env["IG_ACCESS_TOKEN"]


def _call(method, url, params=None, data=None, headers=None):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            return json.load(res)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"인스타 API 오류 {e.code}: {e.read().decode(errors='replace')[:300]}") from None


def publish_reel(video_path, caption):
    """영상 파일을 릴스로 올리고 게시물 ID를 돌려준다."""
    user, token = _env()
    video = Path(video_path).read_bytes()
    # 1. 업로드 컨테이너 만들기
    container = _call("POST", f"{GRAPH}/{user}/media", {
        "media_type": "REELS", "upload_type": "resumable", "caption": caption, "access_token": token,
    })["id"]
    # 2. 영상 파일 올리기
    _call("POST", f"{RUPLOAD}/{container}", data=video, headers={
        "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(len(video)),
    })
    # 3. 인스타가 영상 처리를 끝낼 때까지 기다리기 (최대 5분)
    for _ in range(60):
        status = _call("GET", f"{GRAPH}/{container}", {"fields": "status_code", "access_token": token})["status_code"]
        if status == "FINISHED":
            break
        if status == "ERROR":
            raise RuntimeError("인스타가 영상 처리에 실패했어요. 영상 길이(3~90초)와 형식을 확인하세요.")
        time.sleep(5)
    else:
        raise RuntimeError("인스타 영상 처리가 5분 넘게 끝나지 않았어요.")
    # 4. 게시
    return _call("POST", f"{GRAPH}/{user}/media_publish", {"creation_id": container, "access_token": token})["id"]


def insights(media_id):
    """게시물 성과 → {views, likes, comments, saved, shares}"""
    _, token = _env()
    res = _call("GET", f"{GRAPH}/{media_id}/insights", {
        "metric": "views,likes,comments,saved,shares", "access_token": token,
    })
    return {m["name"]: m["values"][0]["value"] for m in res["data"]}
