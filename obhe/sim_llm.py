# -*- coding: utf-8 -*-
"""on-prem LLM 미연결 데모용 결정론적 시뮬레이터.

artifact 텍스트의 관측 가능한 신호(section 수, 표 행, URL, 숫자 포함 문장)로
Human Action Ledger를 생성한다. 호출 횟수에 따라 수량을 ±10% 변주해
3중 추정(judge) 집계 경로를 실측처럼 시험할 수 있게 한다.

실운영에서는 ledger_builder.restore_paths(llm=...)에 complete_json(prompt,
max_tokens) -> dict 계약을 만족하는 실제 LLM 클라이언트를 넘길 것.
"""
import re


class SimLLM:
    def __init__(self):
        self._calls = 0

    def _vary(self, n):
        """judge별 결정론적 변주: 호출 순서에 따라 -10%/0/+10%."""
        factor = 1.0 + 0.1 * ((self._calls % 3) - 1)
        return max(1, round(n * factor))

    def complete_json(self, prompt, max_tokens=4000):
        self._calls += 1
        m = re.search(r"---\n(.*)\n---", prompt, re.DOTALL)
        text = m.group(1) if m else prompt

        sections = len(re.findall(r"^#{1,3} ", text, re.MULTILINE)) or 1
        table_rows = len(re.findall(r"^\|.*\|$", text, re.MULTILINE))
        urls = len(re.findall(r"https?://\S+", text))
        charts = len(re.findall(r"차트|chart|그래프|figure", text, re.IGNORECASE))
        claims = len(re.findall(r"^[^\n]*\d+(?:\.\d+)?%?[^\n]*$", text, re.MULTILINE))
        claims = max(3, min(claims, 60))
        sources = max(3, urls if urls else sections)

        v = self._vary
        reference = [
            {"outcome": "최종 문서", "action": "search_source", "quantity": v(sources * 2),
             "drivers": [], "evidence": f"URL/참조 {urls}건, section {sections}개에서 역산",
             "role": "analyst", "confidence": "B"},
            {"outcome": "최종 문서", "action": "read_source", "quantity": v(sources),
             "drivers": [], "evidence": f"유효 source {sources}건", "role": "analyst", "confidence": "B"},
            {"outcome": "최종 문서", "action": "extract_data", "quantity": v(max(table_rows, 5)),
             "drivers": [], "evidence": f"표 행 {table_rows}개", "role": "analyst", "confidence": "B"},
            {"outcome": "최종 문서", "action": "analyze_compare",
             "quantity": v(max(table_rows, 4)), "drivers": ["qualitative_judgement"],
             "evidence": "비교 표 구조", "role": "analyst", "confidence": "B"},
            {"outcome": "최종 문서", "action": "design_decision", "quantity": v(max(2, sections // 4)),
             "drivers": [], "evidence": "문서 구조·결론 단위", "role": "analyst", "confidence": "B"},
            {"outcome": "최종 문서", "action": "write_section", "quantity": v(sections),
             "drivers": [], "evidence": f"section {sections}개", "role": "analyst", "confidence": "A"},
            {"outcome": "최종 문서", "action": "verify_claim", "quantity": v(claims),
             "drivers": [], "evidence": f"수치 포함 주장 약 {claims}건", "role": "reviewer", "confidence": "B"},
            {"outcome": "최종 문서", "action": "review_final", "quantity": 1,
             "drivers": [], "evidence": "완성 artifact 1건", "role": "reviewer", "confidence": "A"},
        ]
        if charts:
            reference.insert(6, {
                "outcome": "최종 문서", "action": "make_chart", "quantity": v(charts),
                "drivers": [], "evidence": f"차트 언급 {charts}건", "role": "analyst", "confidence": "B"})

        # 복제 경로: 잉여 분량까지 그대로 재현 → 작성·검증 수량 증가
        replication = []
        for r in reference:
            rr = dict(r)
            if rr["action"] in ("write_section", "verify_claim", "extract_data", "make_chart"):
                rr = {**rr, "quantity": round(rr["quantity"] * 2.5)}
            replication.append(rr)

        return {
            "outcomes": [
                {"unit": "완성 section", "quantity": sections, "evidence": "heading 수"},
                {"unit": "검증 대상 주장", "quantity": claims, "evidence": "수치 포함 문장"},
            ],
            "reference_ledger": reference,
            "replication_ledger": replication,
            "outcome_confidence": "B",
            "rationale": "artifact 표면 신호 기반 시뮬레이션 복원 (데모용)",
        }
