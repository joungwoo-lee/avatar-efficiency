# -*- coding: utf-8 -*-
"""4조합(ON/ON·rwOFF·actOFF·OFF/OFF) 전후 비교 벤치 — PENDING_CONSIDERATIONS.md 재측정용.
첫 실행 시 이 PC 최근 60세션(200KB 초과) 목록을 bench_files.json에 고정하고, 이후 같은 목록으로 돈다.
수정 전 1회 → 수정 후 1회 돌려 표를 비교. 역전(ON>OFF) 세션 수도 함께 낸다."""
import sys, glob, os, json
sys.path.insert(0, r"C:\Users\joung\avatar-efficiency\efficiency-calculator\session-api")
sys.stdout.reconfigure(encoding="utf-8")
import session_api
from record_actions_code_api import measure
from agent_effort import load_rates
S=os.path.dirname(os.path.abspath(__file__)); L=os.path.join(S,"bench_files.json")
if os.path.exists(L): files=json.load(open(L))
else:
    files=[f for f in glob.glob(os.path.expanduser(r"~\.claude\projects\*\*.jsonl")) if not os.path.basename(f).startswith("agent-") and os.path.getsize(f)>200_000]
    files.sort(key=os.path.getmtime, reverse=True); files=files[:60]; json.dump(files,open(L,"w"))
rates=load_rates(); combos=[("ON/ON",True,True),("rwOFF",False,True),("actOFF",True,False),("OFF/OFF",False,False)]
tot={c[0]:0.0 for c in combos}; items={c[0]:{} for c in combos}; ai=0; n=0; inv_w=0; inv_t=0
for f in files:
    rs={}
    for name,rw,act in combos:
        r=measure(f,humanize_rw=rw,humanize_act=act,rates=rates)
        if r.get("excluded") or "error" in r: rs=None; break
        rs[name]=r
    if not rs: continue
    n+=1; ai+=rs["ON/ON"]["agent"]["total_min"]
    for name,r in rs.items():
        tot[name]+=r["human"]["min"]
        for b in r["human"]["breakdown"]: items[name][b["primitive"]]=items[name].get(b["primitive"],0)+b["minutes"]
    w=lambda r: sum(b["minutes"] for b in r["human"]["breakdown"] if b["primitive"] in ("draft","edit"))
    inv_w+= w(rs["ON/ON"])>w(rs["OFF/OFF"])+1e-6; inv_t+= rs["ON/ON"]["human"]["min"]>rs["OFF/OFF"]["human"]["min"]+1e-6
print(f"세션 {n}  분모 {ai:,.0f}")
for name,*_ in combos:
    print(f"{name:8s} {tot[name]:9,.0f}min {tot[name]/ai:5.2f}x  "+" ".join(f"{k}={v:,.0f}" for k,v in sorted(items[name].items())))
print(f"ON>OFF 역전: 쓰기항목 {inv_w}세션, 총합 {inv_t}세션")
