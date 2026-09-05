#!/usr/bin/env python3
"""pi 用量度量 — 扫描 session .jsonl，聚合模型/项目/时间，输出可改进信号。"""
import json, os, glob
from collections import defaultdict

def _find_root():
    cands=[os.environ.get("PI_SESSIONS"), os.path.expanduser("~/.pi/agent/sessions")]
    if os.environ.get("PI_CODING_AGENT_DIR"):
        cands.append(os.path.join(os.environ["PI_CODING_AGENT_DIR"], "sessions"))
    cands += ["/mnt/d/Program Files/piagent/.pi/agent/sessions"]
    for c in cands:
        if c and os.path.isdir(c): return c
    return os.path.expanduser("~/.pi/agent/sessions")
ROOT = _find_root()

per_model = defaultdict(lambda: {"turns":0,"in":0,"out":0,"r":0,"cr":0,"tok":0,"cost":0.0})
per_proj  = defaultdict(lambda: {"sess":0,"turns":0,"tok":0})
per_day   = defaultdict(lambda: {"sess":0,"turns":0})
mchg = defaultdict(int)

def scan():
    for pd in glob.glob(os.path.join(ROOT,"*")):
        if not os.path.isdir(pd): continue
        proj=os.path.basename(pd)
        for f in glob.glob(os.path.join(pd,"*.jsonl")):
            with open(f,encoding="utf-8",errors="ignore") as fh:
                for line in fh:
                    line=line.strip()
                    if not line: continue
                    try: o=json.loads(line)
                    except: continue
                    t=o.get("type")
                    if t=="session":
                        per_proj[proj]["sess"]+=1
                        per_day[o.get("timestamp","")[:10]]["sess"]+=1
                    elif t=="model_change": mchg[o.get("modelId","?")]+=1
                    elif t=="message":
                        m=o.get("message",{})
                        if m.get("role")!="assistant": continue
                        u=m.get("usage") or {}; mdl=m.get("model","?")
                        pm=per_model[mdl]; pm["turns"]+=1
                        pm["in"]+=u.get("input",0); pm["out"]+=u.get("output",0)
                        pm["r"]+=u.get("reasoning",0); pm["cr"]+=u.get("cacheRead",0)
                        pm["tok"]+=u.get("totalTokens",0)
                        pm["cost"]+=(u.get("cost") or {}).get("total",0) or 0
                        per_proj[proj]["turns"]+=1; per_proj[proj]["tok"]+=u.get("totalTokens",0)
                        per_day[o.get("timestamp","")[:10]]["turns"]+=1

def f(v): return f"{v:,}"
def p(a,b): return f"{(a/b*100 if b else 0):.0f}%"

scan()
tok=sum(m["tok"] for m in per_model.values()); turns=sum(m["turns"] for m in per_model.values())
W=("模型","轮次","输入","输出","推理","缓存读","总token")
print("="*72); print("PI 用量度量报告"); print("="*72)
print(f"总轮次 {f(turns)}   总token {f(tok)}")
print()
for m,d in sorted(per_model.items(),key=lambda x:-x[1]["tok"]):
    print(f"{m[:26]:<28}{d['turns']:>5}{f(d['in']):>11}{f(d['out']):>10}{f(d['r']):>9}{f(d['cr']):>11}{f(d['tok']):>12}")
    print(f"{'':<28}{'推理占比':>13}{p(d['r'],d['tok']):>8}   avg/轮 {f(d['tok']//max(1,d['turns'])):>9}")
print()
print("### 按项目 (token TOP)")
for p,d in sorted(per_proj.items(),key=lambda x:-x[1]["tok"])[:8]:
    print(f"  {p[:42]:<43}{d['sess']}会话/{f(d['turns'])}轮/{f(d['tok'])}token")
print()
print("### 模型切换次数")
for m,n in sorted(mchg.items(),key=lambda x:-x[1])[:5]: print(f"  {m}: {n}次")
print()
print("### 活跃日期 (近7天)")
for d in sorted(per_day.keys())[-7:]: print(f"  {d}: {per_day[d]['sess']}会话/{f(per_day[d]['turns'])}轮")
print()
print("### 改进信号")
if per_model:
    top=max(per_model.items(),key=lambda x:x[1]["tok"])
    tot=sum(m["in"] for m in per_model.values()); out=sum(m["out"] for m in per_model.values())
    rr=sum(m["r"] for m in per_model.values()); cr=sum(m["cr"] for m in per_model.values())
    print(f"  * 最大消耗模型: {top[0]} ({f(top[1]['tok'])} token, {p(top[1]['tok'],tok)})")
    print(f"  * 推理token占比: {p(rr,tok)} (高->考虑降低 thinking)")
    print(f"  * 缓存读占比:   {p(cr,tok)} (高->上下文复用好)")
    print(f"  * 输入/输出 token: {f(tot)} / {f(out)} (输出多->回复冗长)")
print("="*72)
