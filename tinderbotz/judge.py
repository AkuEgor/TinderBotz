"""
AI judge: looks at a geomatch's photos + profile text and decides like/pass
against a plain-language preferences file. Runs Claude Haiku on Amazon Bedrock.

Auth: AWS profile from env (AWS_PROFILE, default "claude-ops").
Model/region overridable via JUDGE_MODEL / JUDGE_REGION.
"""
import base64
import os
from typing import Literal

import requests
from anthropic import AnthropicBedrock
from pydantic import BaseModel, Field

MODEL = os.environ.get("JUDGE_MODEL", "eu.anthropic.claude-haiku-4-5-20251001-v1:0")
REGION = os.environ.get("JUDGE_REGION", "eu-central-1")
MAX_IMAGES = int(os.environ.get("JUDGE_MAX_IMAGES", "4"))
SUPPORTED_MEDIA = {"image/jpeg", "image/png", "image/gif", "image/webp"}

SYSTEM = """You screen dating-app profiles for one person. You get their preferences and one profile (photos + text).
Decide "like" or "pass" by applying their preferences as written. Hard dealbreakers in the preferences always mean pass.
When the profile is ambiguous or has too little info, lean on photos and overall vibe; do not invent facts.
Score 0-10 = how well this profile fits their preferences. Reason = one short sentence a friend would say."""


class Verdict(BaseModel):
    decision: Literal["like", "pass"]
    score: int = Field(ge=0, le=10)
    reason: str


def _client():
    os.environ.setdefault("AWS_PROFILE", "claude-ops")
    return AnthropicBedrock(aws_region=REGION)


def _image_blocks(urls):
    blocks = []
    for url in (urls or [])[:MAX_IMAGES]:
        try:
            resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
        except requests.RequestException:
            continue
        media_type = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        if media_type not in SUPPORTED_MEDIA:
            continue
        blocks.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type,
                       "data": base64.standard_b64encode(resp.content).decode()},
        })
    return blocks


def _profile_text(g):
    fields = {
        "name": g.name, "age": g.age, "distance": g.distance, "work": g.work, "study": g.study,
        "home": g.home, "gender": g.gender, "bio": g.bio, "passions": g.passions,
        "lifestyle": g.lifestyle, "basics": g.basics, "looking_for": g.looking_for,
    }
    return "\n".join(f"{k}: {v}" for k, v in fields.items() if v)


class Judge:
    def __init__(self, preferences: str):
        self.preferences = preferences
        self.client = _client()

    def judge(self, geomatch) -> Verdict:
        images = _image_blocks(geomatch.image_urls)
        text = (f"<preferences>\n{self.preferences}\n</preferences>\n\n"
                f"<profile photos=\"{len(images)}\">\n{_profile_text(geomatch)}\n</profile>")
        response = self.client.messages.parse(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM,
            messages=[{"role": "user", "content": images + [{"type": "text", "text": text}]}],
            output_format=Verdict,
        )
        return response.parsed_output
