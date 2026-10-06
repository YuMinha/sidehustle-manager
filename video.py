"""숏폼 대본 → 세로 영상(1080x1920): 문장마다 AI 목소리 + 자막 + 내 사진.

목소리는 edge-tts(마이크로소프트 Edge의 읽어주기 음성)를 쓴다. 공식 유료 API가 아니라서
서비스가 바뀌면 멈출 수 있다. 그때는 tts() 한 함수만 다른 음성 API로 바꾸면 된다.
"""
import asyncio
import tempfile
import textwrap
from pathlib import Path

import edge_tts
import numpy as np
from moviepy import AudioFileClip, ImageClip, concatenate_videoclips
from PIL import Image, ImageDraw, ImageFont, ImageOps

W, H = 1080, 1920
VOICE = "ko-KR-SunHiNeural"  # 여성 목소리. 남성은 ko-KR-InJoonNeural
FONT = "C:/Windows/Fonts/malgunbd.ttf"  # 맑은 고딕 굵게 (윈도우 기본 글꼴)
MEDIA = Path(__file__).with_name("media")


def tts(text, path):
    asyncio.run(edge_tts.Communicate(text, VOICE).save(str(path)))


def frame(photo, caption):
    """사진을 세로 화면에 꽉 채우고 아래쪽에 자막을 얹은 한 장."""
    if photo:
        img = ImageOps.fit(Image.open(photo).convert("RGB"), (W, H))
    else:
        img = Image.new("RGB", (W, H), (34, 40, 49))
    draw = ImageDraw.Draw(img, "RGBA")
    font = ImageFont.truetype(FONT, 72)
    lines = textwrap.wrap(caption, 13) or [""]
    line_h = 96
    top = H - 520 - line_h * len(lines) // 2
    draw.rectangle([0, top - 40, W, top + line_h * len(lines) + 40], fill=(0, 0, 0, 150))
    for i, line in enumerate(lines):
        w = draw.textlength(line, font=font)
        draw.text(((W - w) / 2, top + i * line_h), line, font=font, fill="white")
    return np.array(img)


def make_video(post_id, lines, photos):
    """대본 문장 목록 + 사진 경로 목록 → media/<post_id>/shorts.mp4 경로"""
    lines = [l.strip() for l in lines if l.strip()]
    if not lines:
        raise ValueError("숏폼 대본이 비어 있어요.")
    out = MEDIA / str(post_id) / "shorts.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        clips = []
        for i, line in enumerate(lines):
            voice = Path(tmp) / f"{i}.mp3"
            tts(line, voice)
            audio = AudioFileClip(str(voice))
            photo = photos[i % len(photos)] if photos else None
            clips.append(ImageClip(frame(photo, line)).with_duration(audio.duration + 0.3).with_audio(audio))
        video = concatenate_videoclips(clips)
        video.write_videofile(str(out), fps=24, codec="libx264", audio_codec="aac", logger=None)
        video.close()
        for c in clips:
            c.audio.close()
    return out
