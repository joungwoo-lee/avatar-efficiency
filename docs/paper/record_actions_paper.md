# Deterministic, LLM-Free Counterfactual Effort Accounting from Coding-Agent Session Transcripts

*Draft v0.1 — 2026-08-29. Companion to `paper.md` (v0.1, LLM-judge pipeline). Method source: `efficiency-calculator/session-api/record_actions_code_api.md`; numeric provenance: `efficiency-calculator/CHANGELOG.md` §-references cited inline.*

## Abstract

Estimating how much human labor an AI coding agent displaces usually relies on controlled experiments, self-report, or an LLM judge. We present a fully deterministic, LLM-free estimator that reads a single Claude Code session transcript (`.jsonl`) and returns a speedup ratio `human_min / agent_min`. The numerator is the time a *competent human going directly to the outcome* would have spent, computed from transcript evidence (what was read, written, searched, executed, and deliberated) multiplied by a published rate table; the denominator is the AI path's cost, computed as measured AI wall-time plus modeled human supervision. The central design principle is **outcome attribution — only work that contributed to the final outcome counts as human labor** — realized as a three-tier read classifier (contributing / skimmed / wasted), net-of-reversal write replay, per-identity execution collapsing, a four-part execution model, and position-based selection of strategic reasoning tokens. All rates are graded by evidence level (direct literature anchor, derived anchor, adjacent anchor, measured, or modeling seed) and reported with sensitivity bands. On a single-user pilot corpus of 57 sessions the estimator yields an aggregate ratio of 4.63× (session median 3.73×); humanization reduces the naive "replay the AI trajectory" numerator by 23%, and swinging unanchored supervision seeds by 0.5×–2× moves the aggregate between 3.04× and 1.91× while preserving session rank order. We report zero human ground-truth measurements and therefore position the ratio as a relative, auditable indicator, and lay out the paired-measurement study needed to validate it.

**Keywords:** AI-assisted software engineering, productivity measurement, counterfactual effort, usage-log analysis, deterministic instrumentation, rate-table calibration

## 1. Introduction

Evidence on coding-agent productivity is contradictory: a controlled Copilot task showed +55.8% speed [1], while METR's 2025 RCT found experienced developers 19% *slower* yet believing themselves 20% faster [2]. Organizations that pay for agent subscriptions need a continuous instrument rather than a lab study, and our earlier design [11] proposed an LLM judge for that role. A judge, however, is itself non-deterministic, costs tokens, and cannot be audited line by line.

This paper asks a narrower question: **how far can a purely deterministic reading of the agent's own transcript go?** The transcript records every file the agent read, every edit it made, every command it ran with timestamps, every user instruction, and — since the 2026-08-12 Claude Code format — the number of hidden reasoning tokens per response. We show that these signals, combined with a small, evidence-graded rate table, suffice to build an estimator that is (a) reproducible (same input → same output), (b) free of API keys and model calls, (c) auditable per session via a channel-level ledger of counted and uncounted text, and (d) honest about where its numbers come from.

Contributions:

1. **Outcome-attribution humanization** (§3): a set of deterministic rules that convert an agent's exploratory, trial-and-error trajectory into the minimal path a knowledgeable human would take — contributing-read detection by five transcript signals, net-of-reversal write replay, execution collapsing, and strategic-thought selection.
2. **A hybrid denominator** (§4): AI time measured directly from per-turn inter-record gaps (capped at 10 min per gap; invariant `AI_time ≤ session_runtime` enforced by regression test), plus modeled human-in-the-loop supervision whose only measured component (instruction cost) is fitted on 1,456 instructions.
3. **An evidence-graded rate table** (§5) mapping each rate to direct / derived / adjacent literature anchors or explicitly labeled seeds, with sensitivity bands reported alongside every aggregate.
4. **A pilot study** (§6) on 57 sessions and an ablation of each design change, plus a validity analysis (§7) enumerating twelve known bias directions.

## 2. Measurement Stance

**No wall-clock for human labor.** Human work on a task can happen outside the session (thinking in the shower, batching edits later); transcript elapsed time cannot capture it. The numerator is therefore *always* `evidence × rate`, with two deliberate exceptions where the transcript directly records what a human would also have waited for: command execution latency (`tool_use → tool_result` timestamps, §59) and — on the denominator side — all AI time (§62).

**Numerator and denominator are different counterfactuals.** The numerator assumes a competent human takes the direct route (net of reversals). The denominator is the AI path's *estimated total cost* including everything the human had to look at, so review is charged on *cumulative* edits, not net edits. The asymmetry is intentional and is the source of the monotonicity guarantee below.

**Parallel sub-agents.** Sidechain transcripts are included in the numerator (a serial human must do that work too) and excluded from the denominator (they ran in parallel and add no wall time). Before this rule the numerator was under-counted by up to 2.2× on sessions that used sub-agents (3.54× → 7.67×, §59).

**Exclusions.** Sessions with runtime ≤ 5 min are excluded (fixed completion costs inflate their ratio 5–7×, §9/§64); sessions launched programmatically (`entrypoint="sdk-cli"` or `promptSource="sdk"`) are excluded as non-human work (§54).

**Monotonicity.** Two humanization switches (`rw` for read/write, `act` for action counts) yield four configurations ordered `ON·ON ≤ OFF·ON ≤ ON·OFF ≤ OFF·OFF` per item by construction (clamps in §43/§46); the fully-OFF configuration is the "human replays the AI trajectory verbatim" baseline.

## 3. Numerator: Outcome-Attribution Humanization

### 3.1 Reading — three tiers

Every file read (including shell reads such as `sed`/`cat`, §27/§47) is classified:

| Tier | Rule (any one signal suffices for DEEP) | Rate |
|---|---|---|
| DEEP (contributing) | ① later edited; ② named in the final answer; ③ same span revisited ≥2×; ④ landing read immediately after the turn's last search; ⑤ content overlap (6-word run or discriminative identifier reappears in answer/edit) | read rate on evidenced 200-word blocks, skim rate on the rest |
| SKIM (candidate) | non-contributing file read *before* the turn's last DEEP read | 1/20 of read |
| WASTE | non-contributing file read only *after* contribution was secured | 0 — a human would not open it |

Within a DEEP file only blocks carrying evidence (≥2 discriminative identifiers or a 6-word overlap) are charged at the read rate; the remainder is skimmed. Re-reads of the same span are counted once.

### 3.2 Writing — net-of-reversal replay

Only words surviving in the final artifact are labor. For files the session created, edits are replayed to reconstruct the final text (create-then-discard round trips net to zero) and the result is charged as *draft*. For pre-existing files, a later edit whose `old_string` covers an earlier insertion cancels it; partial overlaps are not detected (conservative). Failed edits are dropped. Report-only sessions charge the final answer as draft. Words are further split by kind — code 0.08, prose 0.05, data (JSON/YAML/CSV) 0.01 min/word — because the human procedures differ (write, compose, *generate*); measured composition of written words is 44% / 31.5% / 24.4% (§59).

### 3.3 Actions — net counts

- **Search** = 1 episode per landing on a DEEP file; query refinement is absorbed into that episode; searches that never land count 0. Shell `grep`/`find` are reclassified as search.
- **Execute** = 1 per *normalized command identity*; edit-rerun loops collapse; failed calls cancel. Shell reads are reclassified as reads; redirections, heredocs and `sed -i` remain executes.
- Clamps: floor 1 per item if any trace exists, ceiling = raw call count. One final *verify* episode is charged in both ON and OFF modes to prevent inversion (§43).

### 3.4 Execution — four-part episode model

A flat 2.0 min/execution made `git status` and a 97-word heredoc script cost the same. The episode is decomposed:

| Part | Human activity | Evidence | Rate |
|---|---|---|---|
| Compose | type the command/script | command word count (first identity only) | 0.05 min/word (prose composition rate — no design pass) |
| Wait | wait for completion | measured `tool_use → tool_result` latency | as measured |
| Interpret | read the output | output words: first 200 at read rate, rest skimmed | 0.005 / 0.00025 |
| Operate | switch, enter, confirm | new command / rerun | 0.25 / 0.10 min |

Reconstruction showed the old 2.0 min equalled the *lower bound* of this model: correct for one-liners (12% of executions), 3–5× too low for ad-hoc scripts (about half). Output interpretation had previously been charged at zero.

### 3.5 Strategic thought — position-selected reasoning tokens

Humanization *removes* AI verbosity; the numerator still lacked *judgment* labor because every human rate assumes an expert who already knows the answer. Since 2026-08-12 the transcript records `usage.output_tokens_details.thinking_tokens` (content remains blank). We charge reasoning tokens only at **strategy points** — the first assistant message after a genuine user instruction (instruction := user record − tool results − meta − sidechain):

```
think_min = Σ_{strategy points} thinking_tokens × 0.75 (tokens→words) × 0.005 min/word
```

Rationale (§3.1 of the source): an expert spends no deliberation on tool operation or on output formatting; deliberation happens when deciding *how to approach* a task; self-initiated mid-task re-strategizing has no deterministic boundary and is left uncounted (deliberately conservative). Measured over 16 sessions / 632 messages / 366,638 tokens, this rule selects 52.7% of reasoning tokens; 77% of the excluded tokens accompany tool calls, confirming that position alone filters the two "expert automation" axes. The rejected alternative — charge *all* tokens at read rate — doubled the numerator (+103%), made thought 70% of the median numerator, inflated small sessions 8×, and made the ratio a function of the model's reasoning-effort setting.

Pre-2026-08-12 transcripts have strategy points but no token counts; each is charged a flat 1.5 min — the measured *median* (396 tokens ≈ 1.49 min), not the mean (2.98 min). Applying this rule to the 16 sessions with real counts gives a median ratio of 1.14× against measured (0.28×–7.41×, two-sided), i.e. no directional drift. A mean-based fill (§55) was rejected because token count then correlated 0.99 with instruction count — it measured instructions, not thought.

## 4. Denominator: Measured AI Time + Modeled Supervision

### 4.1 AI time — timestamp measurement (§62/§65)

```
AI_time = Σ_turns Σ (gap between consecutive AI records within the turn, each gap capped at 10 min)
```

A *turn* starts at a waking input (any user record that is not a tool result — human utterance, background notification, system injection, interrupt) and consists of assistant responses and tool-result records. Time from the AI's last record to the next waking input is human time and excluded; turn-end `system` stamps and display lines are ignored because the idle time after them (354 h measured) would otherwise leak in. The 10-min cap discards abandonment (the longest observed tool execution is exactly 10.0 min, the Bash timeout); without it a session left open 9.1 days accrued 8.3 days of "AI time". The invariant `AI_time ≤ session_runtime` is a regression test. There are no model- or machine-specific constants: a slow environment simply measures longer gaps.

The former rate model (0.3 min/call, 0.0005 min/output word, 0.002 min/draft word) is retained only as a fallback for timestamp-less transcripts and reported as `machine_rate_estimate`; it over-estimated measured time by 1.29× in aggregate with per-session dispersion 1.25–3.94×. Switching to measurement moved the aggregate from 4.43× to 5.00× and the median from 2.86× to 4.10× — the per-session accuracy gain is the substantive change.

### 4.2 Human supervision (hitl)

| Item | Model | Evidence |
|---|---|---|
| instruct | 0.5 min/instruction + 0.05 min/word, capped at 60 words (anti-paste) | **fitted** on 1,456 instructions |
| review | *turn-confirmation model* (§50): at each substantive instruction (≥5 words) and at session end — conclusion (previous answer) read at 0.008 min/word capped at 300 words, progress reports skimmed at 0.002; artifacts: if code changed, one 2.0-min run check + scale-proportional check (code 0.005 / prose 0.0025 min/word) + 0.5 min per non-code file sample | seed; code coefficient derived from 233 edit→check pairs (median 0.0050 in the 600–1,500-word bin), noting the data do **not** support linearity (per-word cost spans 0.0882–0.0007 across bins) |
| verification delegation | if tests pass at a check point, run check 2.0 → 0.3 min, scaled by coverage; files modified after the last test result excluded | seed |
| correct | 4.0 min per user interrupt (re-orientation cost; the new instruction is charged separately) | seed, flagged for sensitivity |

A proposed surcharge for long tool waits (>30 s) was added and then **withdrawn** (§60): against measured AI time the model without it was more accurate (sum ratio 0.98 vs 1.11; sessions within 0.5–2.0× 42/63 vs 40/63) because the flat per-call charge on thousands of sub-second calls already offset the rare long waits. Its aggregate is retained for audit as `long_wait_min`.

Artifact review is modeled as *checking*, not *reading* (§61/§63): humans do not read agent-written code line by line. Code and prose were split after noticing that a shared 0.002 min/word implied 500 wpm for prose (plausible skim) but 6,073 LOC/h for code (implausible).

## 5. Rate Table and Evidence Grading

| Rate | Value | Equivalent | Anchor | Grade |
|---|---|---|---|---|
| read | 0.005 min/word | 200 wpm | Brysbaert meta-analysis: 238 wpm mean, 175–300 typical [R1] | direct |
| skim | 0.00025 | "4,000 wpm" | interpreted as *5% selective reading*, not reading speed [R2] | seed |
| draft-code | 0.08 | 152 LOC/h | Prechelt 22–31 LOC/h total productivity [R8] ÷ Xia et al. editing share 13.9–15.3% [R9] = 144–223 LOC/h; conservative end | derived |
| draft-prose | 0.05 | 20 wpm | Karat et al. keyboard composition ≈19 cwpm [R3] | direct |
| draft-data | 0.01 | — | "humans generate, not type, data files"; 25× swing moves aggregate only 5.25–5.77× | seed |
| edit | draft × 0.4 | — | inherits prior 0.02/0.05 ratio; Dhakal 51.6 wpm as typing throughput anchor [R4] | adjacent |
| search | 2.0 min/landing | — | Aula et al. 2.94 min, 4.98 queries per successful task [R5] | adjacent |
| execute | 4-part model | — | compose/interpret rates as above; wait measured; operate 0.25/0.10 seed vs KLM seconds-scale [R6] | measured+seed |
| verify | 3.0 min | — | none | seed |
| correct | 4.0 min/interrupt | — | none | seed |
| think | 0.005 min/word | 200 wpm | set equal to read rate; no literature on deliberation speed | seed |
| review conclusion | 0.008 min/word | 125 wpm | inspection effort is task-dependent [R7] | seed |

Dividing total productivity by editing share avoids double counting: comprehension is charged on the read axis, navigation on search, deliberation on think. An interim value of 0.15 (81 LOC/h) was discarded as outside the literature band.

## 6. Pilot Study (single user, one machine)

**Corpus.** All Claude Code transcripts under one user's `~/.claude/projects` as of 2026-08-2x: 70 human sessions after excluding SDK-launched runs; 57 after the 5-min runtime rule. Sub-agent sidechains attached to their parents.

**Aggregate and ablation** (cumulative, §7 of the source):

| Configuration | human min | agent min | aggregate | session median |
|---|---:|---:|---:|---:|
| before §59 | 34,193 | 13,490 | 2.53× | 2.31× |
| + sub-agents, 4-part exec, write kinds, long-wait withdrawn (§59–60) | 60,319 | 13,603 | 4.43× | 2.85× |
| + measured AI time (§62) | 60,584 | 12,129 | 5.00× | 4.10× |
| + code/prose review split (§63) | 60,787 | 13,196 | 4.61× | 3.89× |
| + 5-min runtime exclusion (§64) | 60,649 | 13,154 | 4.61× | 3.73× |
| + 10-min gap cap (§65) | **60,718** | **13,125** | **4.63×** | **3.73×** |

Leave-one-out contribution (at §60 baseline 4.43×): sub-agent inclusion +0.87, four-part execution +0.81, write-kind split +0.09 (code raised, data lowered — a composition change, not a volume change). Execution rose from 27.3% to 39.7% of the numerator once composition and output interpretation were charged.

**Humanization effect** (63-session snapshot, 2026-08-21, before §62): numerator −23.4% from fully-OFF to fully-ON (read/write −88.6 min, actions −74.4 min per session on average); the reduction concentrates in large sessions (165 min vs 14.6 min for sessions above/below the 62.9-min agent-time median), consistent with reversal and waste scaling with exploration.

**Strategic-thought effect** (63 sessions): +11.4% numerator, aggregate 2.278× → 2.538×. Sessions in the top half of reasoning volume gain +12.9%, bottom half +2.4%; judgment-heavy, tool-free sessions gain +180–250% versus +11–29% for tool-driven work — the correction is largest exactly where the direct-route assumption under-counted most. Per-strategy-point tokens are stable (1,053–1,440) for tool-driven sessions and ~10× higher for judgment-only sessions, supporting proportionality *within* the selected subset.

**Sensitivity.** Swinging unfitted supervision seeds (review, correct) by 0.5× / 1× / 2× moves the aggregate 3.04× / 2.54× / 1.91× (2026-08-21 snapshot) with unchanged session ordering; think rate 0.005 / 0.0025 / 0.0016 moves new-format numerators +30.8% / +15.4% / +9.9%, ordering unchanged; the four-part execution band (compose 50→20 wpm, operate 15 s→1 min) spans 1.0–2.3× on the execution share.

**Audit ledger.** Every session returns `channel_audit`: per-channel counted words and uncounted residue (sub-agent report prose, screenshot interpretation); residue above 2,000 words is confessed in `notes`. Historical blind spots — shell-embedded code (359 k words), execution output (468 k words), all sub-agent work — were found precisely because they had been silently zeroed as "execution, not reading".

## 7. Threats to Validity

1. **Zero human ground truth.** No paired human execution of any session exists; every absolute ratio is unvalidated. Report bands and rank order, not points.
2. **Estimate ÷ estimate.** Both sides depend on the rate table; the fitted components are instruction cost and AI time only.
3. **Single-user corpus.** 57 sessions from one developer on one machine; task mix undocumented beyond written-word composition. Not generalizable.
4. **No quality term.** Surviving artifacts are counted regardless of correctness; over-engineered outputs inflate the numerator faster than the denominator. Combining with the quality factor `q(s)` of [11] is future work.
5. **Judgment still under-counted**: verify is a fixed single episode; mid-task re-strategizing is uncounted; pre-2026-08-12 sessions charge a median 1.5 min per strategy point even where deliberation was deep (a re-check on 442 points gives median 2.33 min; raising to it changes the aggregate +1.3%; the lower bound was retained).
6. **Spoken corrections undetected** — only interrupts count as `correct`; "no, not that…" without interruption is charged as instruction. Direction opposite to the possible over-charge of 4.0 min/interrupt; net unknown, covered by the seed sensitivity band.
7. **Denominator thinking uncounted** — reasoning content is blank; rate-based machine estimates trail measured time by ~14% mainly for this reason; measured AI time now sidesteps it.
8. **Uncounted channels**: sub-agent report prose (one session ran 78 sub-agents with no numerator change), screenshot interpretation (count only).
9. **Execution composition assumption**: ad-hoc scripts are assumed human-equivalent; a human might use a GUI (cheaper) or lack automation (dearer).
10. **Think rate is a seed** worth 23.6% of new-format numerators — the largest seed exposure — and depends on the model's reasoning-effort setting.
11. **Linearity of code review** is a design choice contradicted by the fitted data (fixed-cost dominated).
12. **Cross-file tasks**: contribution promotion does not cross session-file boundaries (§17).

## 8. Planned Validation

1. **Paired measurement**: recruit developers to perform a stratified sample (small/large, code/prose/investigation) of already-measured sessions' tasks manually; compare wall-time to the numerator per configuration; this measurement supersedes literature anchors wherever available.
2. **Tier-label audit**: human annotators label a sample of file reads DEEP/SKIM/WASTE blind to the classifier; report κ.
3. **Multi-user replication** across ≥5 developers and ≥3 machines; publish task-type distribution.
4. **Quality integration**: attach test-pass / acceptance outcome to each session and report ratio conditioned on outcome.
5. **Rate re-fitting**: replace seeds (verify, correct, review, think, skim) by fitted values from (1); publish the fitted table with confidence intervals.

## 9. Conclusion

A deterministic reading of agent transcripts can produce a reproducible, auditable counterfactual effort estimate without any model call. Its strength is not the headline ratio but the discipline around it: outcome attribution as a stated principle, measured quantities separated from modeled ones, every rate graded by its evidence, every uncounted channel confessed, and every seed accompanied by a sensitivity band. On the pilot corpus the instrument reports 4.63× aggregate / 3.73× median with humanization removing a quarter of naive replay effort; those numbers should be read as "what an unvalidated but fully transparent model says", pending the paired-measurement study that alone can turn them into a claim.

## References

- [1] Peng, S., Kalliamvakou, E., Cihon, P., Demirer, M. (2023). *The Impact of AI on Developer Productivity: Evidence from GitHub Copilot.* arXiv:2302.06590.
- [2] Becker, J., et al. (2025). *Measuring the Impact of Early-2025 AI on Experienced Open-Source Developer Productivity.* METR.
- [11] *Passive Session-to-Task Attribution and Counterfactual Efficiency Accounting for AI-Assisted Work*, draft v0.1, 2026-08-02 (`docs/paper/paper.md`).
- [R1] Brysbaert, M. (2019). *How many words do we read per minute? A review and meta-analysis of reading rate.* J. Memory and Language, 109, 104047.
- [R2] Rayner, K., Schotter, E. R., Masson, M. E. J., Potter, M. C., Treiman, R. (2016). *So Much to Read, So Little Time.* Psychological Science in the Public Interest, 17(1), 4–34.
- [R3] Karat, C.-M., Halverson, C., Horn, D., Karat, J. (1999). *Patterns of Entry and Correction in Large Vocabulary Continuous Speech Recognition Systems.* CHI '99.
- [R4] Dhakal, V., Feit, A. M., Kristensson, P. O., Oulasvirta, A. (2018). *Observations on Typing from 136 Million Keystrokes.* CHI 2018.
- [R5] Aula, A., Khan, R. M., Guan, Z. (2010). *How does Search Behavior Change as Search Becomes More Difficult?* CHI 2010.
- [R6] Card, S. K., Moran, T. P., Newell, A. (1980). *The Keystroke-Level Model for User Performance Time with Interactive Systems.* CACM 23(7).
- [R7] NASA. *Software Formal Inspections Standard*, NASA-STD-8739.9.
- [R8] Prechelt, L. (2000). *An Empirical Comparison of Seven Programming Languages.* IEEE Computer 33(10).
- [R9] Xia, X., Bao, L., Lo, D., Xing, Z., Hassan, A. E., Li, S. (2018). *Measuring Program Comprehension: A Large-Scale Field Study with Professionals.* IEEE TSE 44(10).
- [R10] Minelli, R., Mocci, A., Lanza, M. (2015). *I Know What You Did Last Summer.* ICPC 2015.

## 부록 A — 한국어 요약

AI 코딩 도구가 사람 일을 얼마나 덜어줬는지 재는 방법을 제안한다. 외부 모델을 한 번도 부르지 않고, 세션 기록만 읽어 같은 입력이면 항상 같은 값이 나온다. 분자는 "일을 아는 사람이 곧장 갔으면 걸렸을 시간"을 기록 속 단서(무엇을 읽고·쓰고·찾고·돌리고·고민했나)에 요율을 곱해 구하고, 분모는 AI 가 실제로 돌아간 시간(타임스탬프 실측)에 사람이 지시하고 확인한 시간을 더한다. 핵심 원칙은 **결말에 기여한 것만 사람 노동으로 친다**는 것이다. 요율은 문헌 근거 등급을 붙여 공개하고, 근거 없는 값은 흔들어 봤을 때 결론이 얼마나 움직이는지를 함께 적는다. 한 사람의 57세션에서 사람이 하면 4.63배(세션 중앙 3.73배) 걸린다고 나왔으나, 사람이 직접 해본 정답이 하나도 없으므로 이 수치는 검증된 주장이 아니라 "투명한 모델이 말하는 값"이다. 다음 단계는 같은 일을 사람에게 시켜 재는 짝 실험이다.
