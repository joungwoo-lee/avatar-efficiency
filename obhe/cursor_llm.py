# -*- coding: utf-8 -*-
"""cursor-proxy(OpenAI 호환, 기본 127.0.0.1:18741) LLM 클라이언트.

계약: complete_json(prompt: str, max_tokens: int) -> dict
env:
    OBHE_LLM_BASE   기본 http://127.0.0.1:18741/v1
    OBHE_LLM_MODEL  기본 gpt-5-mini
"""
import json
import os
import re
import urllib.error
import urllib.request

DEFAULT_BASE = "http://127.0.0.1:18741/v1"
DEFAULT_MODEL = "gpt-5-mini"


def _extract_json(text):
    """모델 응답에서 JSON 오브젝트 1개 추출 (코드펜스·잡담 방어)."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start:end + 1])
    raise ValueError("응답에서 JSON 오브젝트를 찾지 못함: " + text[:200])


class CursorProxyLLM:
    def __init__(self, base_url=None, model=None, timeout=300):
        self.base_url = (base_url or os.environ.get("OBHE_LLM_BASE", DEFAULT_BASE)).rstrip("/")
        self.model = model or os.environ.get("OBHE_LLM_MODEL", DEFAULT_MODEL)
        self.timeout = timeout

    def complete_json(self, prompt, max_tokens):
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0,
            "stream": False,
        }
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"LLM HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"cursor-proxy 연결 실패({self.base_url}): {e.reason}. "
                "proxy 기동 확인 또는 --llm sim 사용.") from e
        content = payload["choices"][0]["message"]["content"]
        return _extract_json(content)
