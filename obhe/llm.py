# -*- coding: utf-8 -*-
"""LLM 백엔드 팩토리 — 교체는 이 함수 하나로 끝난다.

계약 (모든 백엔드 공통):
    complete_json(prompt: str, max_tokens: int) -> dict

사용:
    llm = make_llm("cursor")                 # cursor-proxy (기본)
    llm = make_llm("sim")                    # 데모 시뮬레이터
    llm = make_llm("my_pkg.my_mod:MyLLM")    # 임의 백엔드 동적 로드
    llm = make_llm()                          # env OBHE_LLM_BACKEND, 기본 cursor

새 백엔드 추가: complete_json 계약을 구현한 클래스를 만들고
"모듈경로:클래스명"으로 지정하면 코드 수정 없이 교체된다.
"""
import importlib
import os

DEFAULT_BACKEND = "cursor"


def make_llm(spec=None, **kwargs):
    spec = spec or os.environ.get("OBHE_LLM_BACKEND", DEFAULT_BACKEND)
    if spec == "cursor":
        try:
            from .cursor_llm import CursorProxyLLM
        except ImportError:
            from cursor_llm import CursorProxyLLM
        return CursorProxyLLM(**kwargs)
    if spec == "sim":
        try:
            from .sim_llm import SimLLM
        except ImportError:
            from sim_llm import SimLLM
        return SimLLM()
    module_path, sep, cls_name = spec.partition(":")
    if not sep:
        raise ValueError(f"알 수 없는 LLM 백엔드: {spec!r} — 'cursor' | 'sim' | '모듈경로:클래스명'")
    cls = getattr(importlib.import_module(module_path), cls_name)
    obj = cls(**kwargs)
    if not callable(getattr(obj, "complete_json", None)):
        raise TypeError(f"{spec}: complete_json(prompt, max_tokens) 계약 미구현")
    return obj
