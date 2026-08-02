# Passive Session-to-Task Attribution and Counterfactual Efficiency Accounting for AI-Assisted Work

*Draft v0.1 — 2026-08-02. Evaluation sections are planned work; see §7.*

## Abstract

Organizations are rapidly deploying AI coding agents, yet they lack a way to answer two basic accounting questions: *which* organizational work did each AI session actually serve, and *how much* value did it produce relative to the human labor it displaced? Existing measurements rely on controlled experiments, self-report, or proxy activity metrics, none of which attribute AI usage to an organization's own role and task structure. We propose a passive, non-intrusive pipeline that (1) models each worker as an **avatar card** — a login-keyed profile holding weighted roles, weighted tasks, and natural-language task scripts supplied by the organization; (2) sweeps locally stored agent session transcripts at agent start-up time, with an idempotent ledger that guarantees exactly-once analysis per session content; (3) uses a small LLM judge to match each finished session to a task and to estimate a **counterfactual manual-effort time**, yielding a per-session efficiency coefficient η = (estimated manual hours × quality) / active session hours; and (4) rolls η up through task and role weights to an avatar-level efficiency E, which converts an organization's cost plan into effective cost and token-level return on investment. We describe the formal model, a working implementation for Claude Code sessions that requires no API keys and never blocks the user's interactive sessions, and the validity threats that motivate our planned evaluation: attribution accuracy against labeled sessions, and calibration of LLM counterfactual effort estimates against measured human baselines.

**Keywords:** AI-assisted work, productivity measurement, LLM-as-a-judge, usage log analysis, effort estimation, ROI accounting

## 1. Introduction

Evidence on whether AI assistants make knowledge workers faster is contested. A controlled experiment found GitHub Copilot users completed a well-defined task 55.8% faster [1], while a 2025 randomized controlled trial by METR found that experienced open-source developers were 19% *slower* with AI tools — while believing they had been 20% faster [2]. The perception–reality gap in [2] is the central motivation of this work: **self-report cannot be trusted, and controlled experiments do not scale to everyday organizational work.** An organization that funds AI subscriptions needs a continuous, passive measurement instrument, not a one-off lab study.

At the same time, large-scale usage analyses such as the Anthropic Economic Index [3], built on the privacy-preserving Clio framework [4], have shown that LLM conversations *can* be reliably classified against an external task taxonomy (O\*NET) at the scale of millions of conversations. However, these analyses target economy-wide occupational categories. They do not answer the question a specific organization asks: *did this session advance task t of role r of employee a, and what was it worth relative to our cost plan?*

We bridge this gap with an organizational accounting layer on top of passive session logs. Our contributions:

1. **A formal attribution and accounting model** (avatar → weighted roles → weighted tasks → sessions) in which a per-session efficiency coefficient η aggregates into avatar-level efficiency E and converts planned labor cost into effective cost and token ROI (§3).
2. **A passive, safe collection architecture**: an agent-start-up sweeper over locally stored transcripts with an idempotent single-file ledger (offset bookmarks, in-progress marks, self-recursion exclusion) that guarantees no duplicate LLM analysis and no interference with live sessions — implemented for Claude Code without any API key, using only the organization's existing subscription (§4).
3. **An honest treatment of the counterfactual**: manual-effort time is estimated by an LLM judge anchored by per-task rubrics; we position this as a *relative* indicator, identify its validity threats, and design the calibration study needed to justify it (§6, §7).

## 2. Related Work

**Measuring AI-assisted developer productivity.** Controlled experiments show large but conflicting effects: +55.8% speed on a greenfield task [1] versus −19% on mature-repository issues, with participants misperceiving the direction of the effect [2]. Telemetry-correlation studies such as Ziegler et al. tie acceptance rates of code completions to perceived productivity [5]. These designs either require constructed tasks or measure the assistant in isolation; none attribute value to an organization's own work breakdown.

**Productivity frameworks.** SPACE [6] argues productivity is multi-dimensional (satisfaction, performance, activity, communication, efficiency) and warns against single activity metrics; DORA metrics [7] measure delivery performance at team level. Our system is complementary: it contributes the *attribution* and *cost* dimension these frameworks lack, and its η/E metrics can feed a SPACE-style dashboard as the efficiency axis.

**Usage-log task classification.** Clio [4] and the Anthropic Economic Index [3] demonstrate privacy-preserving, LLM-driven classification of assistant conversations onto a 20k-task occupational taxonomy. We adopt the same core idea — an LLM classifies transcripts against a task inventory — but replace the universal taxonomy with an organization-supplied, weighted role/task tree per worker, and extend classification with counterfactual effort estimation and cost roll-up.

**LLM-as-a-judge.** Zheng et al. establish that strong LLM judges can approximate human preference judgments at ~85% agreement [8], legitimizing LLM judges as scalable measurement instruments while documenting their biases. Our judge performs two harder tasks: closed-set classification (mitigated by an explicit *no-match* option) and quantitative effort estimation, which we anchor with per-task rubrics and treat as requiring calibration (§7).

**Software effort estimation.** Decades of work on human expert estimation [9] and algorithmic models such as COCOMO [10] show that expert judgment, though biased, is competitive with formal models and improves with historical anchors. Our per-task "anchor" rubrics (e.g., "one lint violation fixed manually ≈ 5 min") transplant this finding: the organization encodes its own anchors, and the LLM interpolates them over the session's observed outputs.

## 3. Model

**Avatar cards.** Each worker is an avatar `a` with a login identifier, a natural-language scope script, and weighted roles: `roles(a) = {(r, w_r)}`, `Σ w_r = 1`. Each role holds weighted tasks `tasks(r) = {(t, w_t)}`, `Σ w_t = 1`, and each task carries a *script*: a concrete description with tool names, artifact names, and manual-effort anchors. Scripts and weights are supplied by an external module (the organization's planning system); the measurement pipeline only consumes them. A project cost plan (*PM plan*) allocates a budget share `B_a` to each avatar.

**Session attribution.** A finished session `s` (transcript excerpt: first user prompt + last N messages) is classified by a judge into `(r, t)` or *no-match*. No-match sessions are recorded but excluded from aggregation — forcing a match would corrupt η.

**Efficiency coefficient.** For a matched session,

```
η(s) = ( Ĥ_manual(s) × q(s) ) / H_active(s)
```

- `Ĥ_manual(s)`: judge-estimated hours for a human to produce the session's actual outputs manually, interpolated from the task's anchors (LLM-estimated — the calibrated quantity, §7).
- `q(s) ∈ [0,1]`: judge-assessed completion quality (unfinished or rework-needed sessions are discounted; failed sessions can yield η < 1).
- `H_active(s)`: measured active time — sum of inter-message gaps ≤ 15 min from transcript timestamps (computed, not estimated; idle gaps excluded so abandoned-open sessions are not undercounted).

**Aggregation.** Task-level η̄_t is the mean over its sessions (tasks with no sessions default to η = 1, the manual baseline). Then

```
E_r = Σ_t w_t · η̄_t        E_a = Σ_r w_r · E_r        EffectiveCost(a) = B_a / E_a
```

**Token value.** With per-session token usage `T(s)` read from the transcript and an hourly labor rate ρ derived from the cost plan (`ρ = B_a / planned hours`):

```
V(s) = Ĥ_manual · ρ · q − H_active · ρ_sup      C(s) = price(T(s))
ROI = Σ V / Σ C                                  value-per-token = Σ V / Σ T
```

where `ρ_sup` is the supervision rate (the human's attendance cost during the session) and `price(·)` applies published per-token rates (an imputed opportunity cost under subscription pricing; the convention is fixed and disclosed). Because `Ĥ_manual` is judge-estimated, V and ROI are reported as *relative* indicators — valid for comparing tasks, models, and periods under a fixed judge and rubric, not as audited currency amounts.

## 4. Architecture

The pipeline must satisfy four constraints: passive (no user action), non-interfering (never block or touch live sessions), duplicate-free (each session content analyzed once), and self-contained (no API key; the judge runs on the organization's existing agent subscription).

**Trigger.** Session-end hooks fire only on clean exits and miss abandoned or crashed sessions. Instead, a hook at *agent start-up* detaches a background sweeper — the user starting their agent is itself the batch trigger, and every previously finished session is eventually swept regardless of how it ended.

**Selection.** The sweeper scans the agent's local transcript store (one JSONL per session, sharded by working directory) and selects files that are (i) older than the sweep start, (ii) quiescent for ≥ 30 min (excludes live sessions; reads are read-only and never lock the writer), and (iii) *unprocessed* — not in the ledger, or grown past the ledger's byte offset **with at least one real user+assistant turn** (an mtime change alone, e.g. a resume-and-close, does not trigger re-analysis).

**Idempotency ledger.** A single append-only file is both processing ledger and send spool: `{uuid, offset, result, sent}`. In-progress marks written immediately before each judge call bound crash-induced re-analysis to one call; a lock file and a throttle serialize concurrent sweeps; results are upserted by session UUID so resumed sessions update rather than duplicate.

**Self-recursion.** The judge is invoked as a headless agent call (`claude -p`, small model), which itself produces transcripts. Two guards prevent the analyzer from feeding on itself: judge calls run in a dedicated working directory whose transcript shard is excluded from scanning, and a child-marker environment variable makes the start-up hook exit immediately in analyzer-spawned agents. Environment inheritance from the user's session is severed by relaying the sweeper through the OS task scheduler.

**Reporting.** Labeled records `{avatar, role, task, η, quality, hours, tokens, uuid}` are appended to the local spool, then posted asynchronously (short timeout, at-least-once, server-side idempotent upsert) to an aggregation server that computes E and value metrics under the organization's weights and rates. Send failures never block analysis; retries cost no judge tokens.

A reference implementation (~700 LoC, no runtime dependencies, single self-installing binary for Windows and WSL) accompanies this paper; its dedup properties are exercised by an automated harness (re-sweep yields zero re-analysis; appended turns yield exactly one incremental re-analysis).

## 5. Privacy and Deployment Considerations

Transcripts contain the worker's full interaction with the agent. Deployment requires explicit consent and scope limits: only sessions on the enrolled machine account are read; only the derived record (labels, η, hours, token counts, one-sentence rationale) leaves the machine; raw transcripts never do. This is strictly less exposure than Clio-style centralized analysis [4], at the price of trusting the local sweeper. Gaming is a real concern once η feeds evaluations (Goodhart pressure): prompting the agent to inflate apparent output raises `Ĥ_manual`. Mitigations — auditing rationale strings, anchoring rubrics to verifiable artifacts, and separating measurement from individual appraisal — are organizational as much as technical.

## 6. Threats to Validity

- **Counterfactual estimation.** `Ĥ_manual` is an LLM estimate of work not actually performed. Expert-estimation research shows humans are competitive but biased at this task [9]; whether a rubric-anchored LLM matches expert accuracy is precisely our planned calibration question. Until then η is a relative, not absolute, indicator.
- **Judge bias.** LLM judges carry position/verbosity biases [8]; a session that *narrates* well may score higher quality than one that quietly succeeds.
- **Attribution errors.** Misclassified sessions pollute both the numerator task and the denominator baseline; the no-match option trades recall for precision by design.
- **Active-time proxy.** Gap-capped transcript time misses off-screen human work (reading, meetings) interleaved with the session, inflating η.
- **Single-vendor scope.** The implementation reads one agent's transcript format; the model is agent-agnostic but the evidence so far is not.

## 7. Planned Evaluation

1. **Attribution accuracy.** Label ≥ 300 real sessions (multiple workers, ≥ 2 orgs/teams) with ground-truth task assignments; report precision/recall per task and the no-match operating point; ablate script specificity (with/without tool and artifact names).
2. **η calibration.** For a stratified sample of matched sessions, obtain (a) independent expert estimates of manual effort and (b) for a subset, *measured* manual reproduction time by a worker of the target skill level. Report LLM-vs-human agreement (MAE, rank correlation), the effect of anchor rubrics, and judge-model sensitivity (small vs. frontier judge).
3. **Longitudinal deployment.** 8–12 weeks across a small team; compare aggregate E trends against self-reported productivity and delivery metrics (DORA [7]); qualitative interviews on perceived fairness and gaming pressure.
4. **Cost fidelity.** Compare imputed token costs under subscription against metered API pricing for identical workloads.

## 8. Conclusion

We presented a passive accounting layer that turns an organization's existing AI-agent transcripts into attributed, cost-weighted efficiency measurements — without user interaction, API keys, or interference with live work. The formal model is deliberately simple (weighted roll-up of a per-session efficiency coefficient), the architecture guarantees duplicate-free analysis, and the epistemically risky component — LLM counterfactual effort estimation — is isolated behind a single calibratable quantity. If the planned calibration succeeds, organizations gain a continuous instrument for a question they currently answer with anecdotes; if it fails, the failure mode itself (how far LLM effort estimates deviate from measured human baselines) is a finding the field needs.

## References

[1] S. Peng, E. Kalliamvakou, P. Cihon, M. Demirer. *The Impact of AI on Developer Productivity: Evidence from GitHub Copilot.* arXiv:2302.06590, 2023.

[2] J. Becker, N. Rush, E. Barnes, D. Rein (METR). *Measuring the Impact of Early-2025 AI on Experienced Open-Source Developer Productivity.* arXiv:2507.09089, 2025.

[3] K. Handa, A. Tamkin, M. McCain, et al. *Which Economic Tasks are Performed with AI? Evidence from Millions of Claude Conversations.* arXiv:2503.04761, 2025.

[4] A. Tamkin, M. McCain, K. Handa, et al. *Clio: Privacy-Preserving Insights into Real-World AI Use.* arXiv:2412.13678, 2024.

[5] A. Ziegler, E. Kalliamvakou, X. A. Li, et al. *Productivity Assessment of Neural Code Completion.* MAPS @ PLDI, 2022. arXiv:2205.06537.

[6] N. Forsgren, M.-A. Storey, C. Maddila, T. Zimmermann, B. Houck, J. Butler. *The SPACE of Developer Productivity.* ACM Queue 19(1), 2021.

[7] N. Forsgren, J. Humble, G. Kim. *Accelerate: The Science of Lean Software and DevOps.* IT Revolution Press, 2018.

[8] L. Zheng, W.-L. Chiang, Y. Sheng, et al. *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena.* NeurIPS Datasets and Benchmarks, 2023. arXiv:2306.05685.

[9] M. Jørgensen. *A Review of Studies on Expert Estimation of Software Development Effort.* Journal of Systems and Software 70(1–2):37–60, 2004.

[10] B. W. Boehm. *Software Engineering Economics.* Prentice-Hall, 1981.

---

## 부록 A — 한국어 요약 (초안 메모)

- **문제**: 조직이 AI 에이전트 구독에 돈을 쓰는데, 어느 업무에 얼마나 가치가 났는지 잴 수단이 없음. 자기보고는 METR 실험이 보여줬듯 방향조차 틀림(체감 +20% vs 실측 −19%) [2].
- **핵심 아이디어**: 아바타(로그인 ID 선별) → 역할(w_r) → 업무(w_t, 스크립트+수작업 앵커) 트리를 조직이 제공하고, 에이전트 기동 시점 스위퍼가 지난 transcript를 소급 분석 — 소형 LLM 저지가 ① 업무 매칭(해당 없음 허용) ② 반사실 수작업 시간 추정 → η = 수작업추정×품질 ÷ 실측활동시간 → 가중합 E → 실효 코스트·토큰 ROI.
- **기술 기여**: 중복 0 보장 원장(오프셋 책갈피·in-progress·단일 파일), 자기 꼬리 재귀 차단(전용 cwd+훅 마커), API 키 없이 구독만으로 동작, 라이브 세션 무간섭.
- **과학적 정직성**: 최약점 = LLM 반사실 추정 → 이것을 §7 캘리브레이션 연구 질문으로 정면 배치. 절대값 아닌 상대 지표로 운용.
- **타겟**: 워크샵 → ICSE SEIP/EMSE (실배포 데이터 확보 후).
