#!/usr/bin/env python3
"""pi 用量度量 + 自我迭代闭环 — 扫描 session.jsonl，输出用量/工作模式/基线delta/推荐。
用法:
  metrics.py                当前报告 + delta(对比基线) + 推荐
  metrics.py --save-baseline 把当前数字存为新基线
"""
import json, os, glob, re, argparse, sys
from collections import defaultdict

def _sessions_root():
    c=[os.environ.get("PI_SESSIONS"), os.path.expanduser("~/.pi/agent/sessions")]
    if os.environ.get("PI_CODING_AGENT_DIR"): c.append(os.path.join(os.environ["PI_CODING_AGENT_DIR"],"sessions"))
    c+=["/mnt/d/Program Files/piagent/.pi/agent/sessions"]
    for x in c:
        if x and os.path.isdir(x): return x
    return os.path.expanduser("~/.pi/agent/sessions")
ROOT=_sessions_root()

def _config_dir():
    if os.environ.get("PI_CODING_AGENT_DIR"): return os.environ["PI_CODING_AGENT_DIR"]
    return os.path.dirname(ROOT)  # sessions 的父目录 = agent config 目录
BASELINE=os.path.join(_config_dir(), "metrics-baseline.json")

per_model=defaultdict(lambda:{"turns":0,"in":0,"out":0,"r":0,"cr":0,"tok":0,"cost":0.0})
per_proj=defaultdict(lambda:{"sess":0,"turns":0,"tok":0})
per_day=defaultdict(lambda:{"sess":0,"turns":0})
mchg=defaultdict(int); skill_cnt=defaultdict(int)
tool_cnt=defaultdict(int); proj_tools=defaultdict(lambda:defaultdict(int))

def classify(proj,t):
    pn=proj
    if any(k in pn for k in ['Linux-Work','Linux_Work','linux-','driver','debug','i.MX','i.mx']): return '驱动/调试'
    if any(k in pn for k in ['论文','paper','thesis','投稿','summe','research']): return '论文/研究'
    if any(k in pn for k in ['ppt','slide','slid']): return 'PPT'
    if any(k in pn for k in ['piagent','pi-setup','Program Files/piagent']): return 'pi 配置'
    if t.get('chrome_devtools_evaluate',0)+t.get('chrome_devtools_navigate',0)>=3: return '网页自动化'
    if t.get('WebSearch',0)>=6: return '检索/写作辅助'
    return '其他'

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
    # 工作模式
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
    rec=[]  # (who, tips)
    tok=cur["totalTokens"]
    top=max(cur["perModelTokens"].items(),key=lambda x:x[1])[0]
    if not top.startswith("deepseek") and cur["perModelTokens"][top]>tok*0.2:
        rec.append(("你",f"主力模型为 {top}，占 {pct(cur['perModelTokens'][top],tok)}——根据任务成功率和成本决定是否保留，不要仅按供应商切换"))
    if cur["reasoningPct"]>0.15: rec.append(("你",f"推理token占比 {pct(cur['reasoningPct']*100,100)}——常规任务把 thinking 降到 low/medium"))
    if cur["avgTokensPerTurn"]>150000: rec.append(("你",f"平均每轮 {f(cur['avgTokensPerTurn'])} token——精简输入/控制上下文长度"))
    if cur["cacheReadPct"]<0.5: rec.append(("pi",f"缓存读占比 {pct(cur['cacheReadPct']*100,100)}——尽量复用上下文，少开新会话"))
    if cur["outputPct"]>0.5: rec.append(("pi",f"输出占比 {pct(cur['outputPct']*100,100)}——回复精简、结构化"))
    wpc=[(c,v) for c,v in cur["workPatterns"].items() if v>0.7]
    if wpc: rec.append(("你",f"{wpc[0][0]} 占 {pct(wpc[0][1]*100,100)}——精力偏科，聚焦高价值/注意平衡"))
    if base:
        if cur["avgTokensPerTurn"]>base["avgTokensPerTurn"]*1.10:
            rec.append(("pi",f"平均每轮 token 较上次↑{pct((cur['avgTokensPerTurn']-base['avgTokensPerTurn'])/base['avgTokensPerTurn'],1)}——上下文/输出在膨胀，需精简"))
        if cur["reasoningPct"]>base["reasoningPct"]+0.05:
            rec.append(("pi",f"推理占比较上次 ↑——该降 thinking"))
    return rec

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--save-baseline","-s",action="store_true")
    args=ap.parse_args()
    scan(); cur=compute_current(); base=load_baseline()
    tok=cur["totalTokens"]; turns=cur["totalTurns"]
    print("="*72); print("PI 用量度量报告"); print("="*72)
    print(f"总轮次 {f(turns)}  总token {f(tok)}")
    print()
    print("### 按模型"); print(f"{'模型':<28} {'轮次':>7} {'输入':>12} {'输出':>12} {'推理':>12} {'缓存读':>14} {'总token':>14}")
    for m,d in sorted(per_model.items(),key=lambda x:-x[1]["tok"]):
        print(f"{m[:26]:<28} {d['turns']:>7} {f(d['in']):>12} {f(d['out']):>12} {f(d['r']):>12} {f(d['cr']):>14} {f(d['tok']):>14}")
    print()
    print("### 工作模式分类 (token)")
    cat=defaultdict(lambda:[0,0,0])
    for proj,d in per_proj.items():
        c=classify(proj,proj_tools[proj]); cat[c][0]+=d["tok"]; cat[c][1]+=d["turns"]; cat[c][2]+=d["sess"]
    for c,(tk,tn,ss) in sorted(cat.items(),key=lambda x:-x[1][0]):
        print(f"  {c:<12}{ss}会话/{f(tn)}轮/{f(tk)}token  ({pct(tk,tok)})")
    print()
    if base:
        print("### Delta（vs 上次基线）")
        d_avg=cur["avgTokensPerTurn"]-base["avgTokensPerTurn"]
        d_rp=cur["reasoningPct"]-base["reasoningPct"]
        d_cr=cur["cacheReadPct"]-base["cacheReadPct"]
        arrow=lambda x:("↑" if x>0 else ("↓" if x<0 else "="))
        print(f"  avg/轮 {f(cur['avgTokensPerTurn'])} {arrow(d_avg)}  推理占比 {cur['reasoningPct']*100:.1f}% {arrow(d_rp)}  缓存读占比 {cur['cacheReadPct']*100:.1f}% {arrow(d_cr)}")
    else:
        print("### Delta（vs 上次基线）"); print("  (暂无基线，--save-baseline 建立)")
    print()
    print("### 推荐下一步")
    recs=build_recommendations(cur,base)
    if recs:
        for who,tip in recs: print(f"  [{who}] {tip}")
    else: print("  (无明显问题，继续保持)")
    print("="*72)
    if args.save_baseline:
        p=save_baseline(cur); print(f"\n基线已保存 → {p}")
main()
