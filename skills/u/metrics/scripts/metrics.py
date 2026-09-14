#!/usr/bin/env python3
"""pi usage metrics + self-iteration loop — scans session.jsonl files and reports
usage, work patterns, baseline delta, and recommendations.

Usage:
  metrics.py                 current report + delta (vs baseline) + recommendations
  metrics.py --save-baseline store the current numbers as the new baseline
"""
import json, os, glob, re, argparse, sys
from collections import defaultdict

def _sessions_root():
    c=[os.environ.get("PI_SESSIONS"),
       os.path.join(os.environ["PI_CODING_AGENT_DIR"], "sessions") if os.environ.get("PI_CODING_AGENT_DIR") else None,
       os.path.expanduser("~/pi/agent/sessions"),
       os.path.expanduser("~/.pi/agent/sessions")]
    for x in c:
        if x and os.path.isdir(x): return x
    return os.path.expanduser("~/pi/agent/sessions")
ROOT=_sessions_root()

def _config_dir():
    if os.environ.get("PI_CODING_AGENT_DIR"): return os.environ["PI_CODING_AGENT_DIR"]
    return os.path.dirname(ROOT)  # parent of sessions/ = agent config dir
BASELINE=os.path.join(_config_dir(), "metrics-baseline.json")

per_model=defaultdict(lambda:{"turns":0,"in":0,"out":0,"r":0,"cr":0,"tok":0,"cost":0.0})
per_proj=defaultdict(lambda:{"sess":0,"turns":0,"tok":0})
per_day=defaultdict(lambda:{"sess":0,"turns":0})
mchg=defaultdict(int); skill_cnt=defaultdict(int)
tool_cnt=defaultdict(int); proj_tools=defaultdict(lambda:defaultdict(int))

def classify(proj,t):
    pn=proj
    if any(k in pn for k in ['Linux-Work','Linux_Work','linux-','driver','debug','i.MX','i.mx']): return 'driver/debug'
    if any(k in pn for k in ['论文','paper','thesis','投稿','summe','research']): return 'paper/research'
    if any(k in pn for k in ['ppt','slide','slid']): return 'PPT'
    if any(k in pn for k in ['piagent','pi-setup','pi/agent']): return 'pi-config'
    if t.get('chrome_devtools_evaluate',0)+t.get('chrome_devtools_navigate',0)>=3: return 'web-automation'
    if t.get('WebSearch',0)>=6: return 'search/writing'
    return 'other'

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
                    ty=o.get("type")
                    if ty=="session":
                        per_proj[proj]["sess"]+=1; per_day[o.get("timestamp","")[:10]]["sess"]+=1
                    elif ty=="model_change": mchg[o.get("modelId","?")]+=1
                    elif ty=="message":
                        m=o.get("message",{})
                        for seg in (m.get("content") or []):
                            if isinstance(seg,dict):
                                txt=seg.get("text","")
                                if seg.get("type")=="toolCall":
                                    tool_cnt[seg.get("name","?")]+=1
                                    proj_tools[proj][seg.get("name","?")]+=1
                            else: txt=str(seg)
                            for sm in re.findall(r'<skill\s+name="([^"]+)"',txt): skill_cnt[sm]+=1
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
def pct(a,b): return f"{(a/b*100 if b else 0):.0f}%"

def compute_current():
    tok=sum(m["tok"] for m in per_model.values()); turns=sum(m["turns"] for m in per_model.values())
    rr=sum(m["r"] for m in per_model.values()); cr=sum(m["cr"] for m in per_model.values())
    out=sum(m["out"] for m in per_model.values())
    # work patterns
    cat=defaultdict(lambda:[0,0,0])
    for proj,d in per_proj.items():
        c=classify(proj,proj_tools[proj]); cat[c][0]+=d["tok"]; cat[c][1]+=d["turns"]; cat[c][2]+=d["sess"]
    wp={c:(v[0]/tok if tok else 0) for c,v in cat.items()}
    perModelTok={m:d["tok"] for m,d in per_model.items()}
    return {"totalTokens":tok,"totalTurns":turns,"avgTokensPerTurn":(tok//turns if turns else 0),
            "reasoningPct":(rr/tok if tok else 0),"cacheReadPct":(cr/tok if tok else 0),
            "outputPct":(out/tok if tok else 0),"workPatterns":wp,"perModelTokens":perModelTok,
            "capturedAt":__import__("datetime").datetime.now().isoformat(timespec="seconds")}

def load_baseline():
    try: return json.load(open(BASELINE,encoding="utf-8"))
    except: return None

def save_baseline(cur):
    json.dump(cur,open(BASELINE,"w",encoding="utf-8"),ensure_ascii=False,indent=2)
    return BASELINE

def build_recommendations(cur,base):
    rec=[]  # (who, tip)
    tok=cur["totalTokens"]
    top=max(cur["perModelTokens"].items(),key=lambda x:x[1],default=(None,0))[0]
    if top and not top.startswith("deepseek") and cur["perModelTokens"][top]>tok*0.2:
        rec.append(("you",f"Primary model is {top} at {pct(cur['perModelTokens'][top],tok)} — decide from task success rate and cost, not vendor alone"))
    if cur["reasoningPct"]>0.15: rec.append(("you",f"Reasoning tokens are {pct(cur['reasoningPct']*100,100)} — lower thinking to low/medium for routine work"))
    if cur["avgTokensPerTurn"]>150000: rec.append(("you",f"Average {f(cur['avgTokensPerTurn'])} tokens per turn — trim inputs and control context length"))
    if cur["cacheReadPct"]<0.5: rec.append(("pi",f"Cache-read share is {pct(cur['cacheReadPct']*100,100)} — reuse context instead of starting new sessions"))
    if cur["outputPct"]>0.5: rec.append(("pi",f"Output share is {pct(cur['outputPct']*100,100)} — keep replies concise and structured"))
    wpc=[(c,v) for c,v in cur["workPatterns"].items() if v>0.7]
    if wpc: rec.append(("you",f"{wpc[0][0]} takes {pct(wpc[0][1]*100,100)} — effort is skewed; focus on high value or rebalance"))
    if base:
        if cur["avgTokensPerTurn"]>base["avgTokensPerTurn"]*1.10:
            rec.append(("pi",f"Average tokens per turn up {pct((cur['avgTokensPerTurn']-base['avgTokensPerTurn'])/base['avgTokensPerTurn'],1)} vs last baseline — context/output is bloating"))
        if cur["reasoningPct"]>base["reasoningPct"]+0.05:
            rec.append(("pi","Reasoning share is up vs last baseline — lower the thinking level"))
    return rec

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--save-baseline","-s",action="store_true")
    args=ap.parse_args()
    scan(); cur=compute_current(); base=load_baseline()
    tok=cur["totalTokens"]; turns=cur["totalTurns"]
    print("="*72); print("PI USAGE REPORT"); print("="*72)
    print(f"Turns {f(turns)}  Total tokens {f(tok)}")
    print()
    print("### By model"); print(f"{'model':<28} {'turns':>7} {'input':>12} {'output':>12} {'reasoning':>12} {'cacheRead':>14} {'total':>14}")
    for m,d in sorted(per_model.items(),key=lambda x:-x[1]["tok"]):
        print(f"{m[:26]:<28} {d['turns']:>7} {f(d['in']):>12} {f(d['out']):>12} {f(d['r']):>12} {f(d['cr']):>14} {f(d['tok']):>14}")
    print()
    print("### Work patterns (tokens)")
    cat=defaultdict(lambda:[0,0,0])
    for proj,d in per_proj.items():
        c=classify(proj,proj_tools[proj]); cat[c][0]+=d["tok"]; cat[c][1]+=d["turns"]; cat[c][2]+=d["sess"]
    for c,(tk,tn,ss) in sorted(cat.items(),key=lambda x:-x[1][0]):
        print(f"  {c:<16}{ss} sessions/{f(tn)} turns/{f(tk)} tokens  ({pct(tk,tok)})")
    print()
    if base:
        print("### Delta (vs last baseline)")
        d_avg=cur["avgTokensPerTurn"]-base["avgTokensPerTurn"]
        d_rp=cur["reasoningPct"]-base["reasoningPct"]
        d_cr=cur["cacheReadPct"]-base["cacheReadPct"]
        arrow=lambda x:("^" if x>0 else ("v" if x<0 else "="))
        print(f"  avg/turn {f(cur['avgTokensPerTurn'])} {arrow(d_avg)}  reasoning {cur['reasoningPct']*100:.1f}% {arrow(d_rp)}  cacheRead {cur['cacheReadPct']*100:.1f}% {arrow(d_cr)}")
    else:
        print("### Delta (vs last baseline)"); print("  (no baseline yet; run with --save-baseline to create one)")
    print()
    print("### Recommended next steps")
    recs=build_recommendations(cur,base)
    if recs:
        for who,tip in recs: print(f"  [{who}] {tip}")
    else: print("  (nothing obvious; keep going)")
    print("="*72)
    if args.save_baseline:
        p=save_baseline(cur); print(f"\nBaseline saved -> {p}")
main()
