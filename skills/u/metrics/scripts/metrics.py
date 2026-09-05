#!/usr/bin/env python3
"""pi 用量度量 — 扫描 session .jsonl，聚合模型/项目/时间，输出可改进信号。"""
import json, os, glob, re
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
skill_cnt = defaultdict(int)
tool_cnt = defaultdict(int)
proj_tools = defaultdict(lambda: defaultdict(int))

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
                        for seg in (m.get("content") or []):
                            if isinstance(seg,dict):
                                txt = seg.get("text","")
                                if seg.get("type")=="toolCall":
                                    tool_cnt[seg.get("name","?")]+=1
                                    proj_tools[proj][seg.get("name","?")]+=1
                            else:
                                txt = str(seg)
                            for sm in re.findall(r'<skill\s+name="([^"]+)"', txt):
                                skill_cnt[sm]+=1
                        if m.get("role")!="assistant": continue
                        u=m.get("usage") or {}; mdl=m.get("model","?")
                        pm=per_model[mdl]; pm["turns"]+=1
                        pm["in"]+=u.get("input",0); pm["out"]+=u.get("output",0)
                        pm["r"]+=u.get("reasoning",0); pm["cr"]+=u.get("cacheRead",0)
                        pm["tok"]+=u.get("totalTokens",0)
                        pm["cost"]+=(u.get("cost") or {}).get("total",0) or 0
                        per_proj[proj]["turns"]+=1; per_proj[proj]["tok"]+=u.get("totalTokens",0)
                        per_day[o.get("timestamp","")[:10]]["turns"]+=1


def classify(proj, t):
    pn=proj
    kl={'linux-work':'驱动/调试','Linux-Work':'驱动/调试','driver':'驱动/调试','i.mx':'驱动/调试'}
    if any(k in pn for k in ['Linux-Work','Linux_Work','linux-','driver','debug','i.MX','i.mx']): return '驱动/调试'
    if any(k in pn for k in ['论文','paper','thesis','投稿','summe','research']): return '论文/研究'
    if any(k in pn for k in ['ppt','slide','slid']): return 'PPT'
    if any(k in pn for k in ['piagent','pi-setup','pi-setup','Program Files/piagent']): return 'pi 配置'
    if t.get('chrome_devtools_evaluate',0)+t.get('chrome_devtools_navigate',0)>=3: return '网页自动化'
    if t.get('WebSearch',0)>=6: return '检索/写作辅助'
    return '其他'

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
for pp,d in sorted(per_proj.items(),key=lambda x:-x[1]["tok"])[:8]:
    print(f"  {pp[:42]:<43}{d['sess']}会话/{f(d['turns'])}轮/{f(d['tok'])}token")
print()

cat=defaultdict(lambda:[0,0,0])  # tok,turns,sess
for proj,d in per_proj.items():
    c=classify(proj, proj_tools[proj])
    cat[c][0]+=d["tok"]; cat[c][1]+=d["turns"]; cat[c][2]+=d["sess"]
tot=sum(v[0] for v in cat.values())
print("### 工作模式分类 (token)")
for c,(tk,tn,ss) in sorted(cat.items(), key=lambda x:-x[1][0]):
    print(f"  {c:<12}{ss}会话/{f(tn)}轮/{f(tk)}token  ({p(tk,tot)})")
print()
print("### 模型切换次数")
for m,n in sorted(mchg.items(),key=lambda x:-x[1])[:5]: print(f"  {m}: {n}次")
print()
print("### 技能使用 (top)")
if skill_cnt:
    for k,v in sorted(skill_cnt.items(),key=lambda x:-x[1])[:12]: print(f"  {k}: {v}次")
else:
    print("  (无)")
print()
print("### 工具/扩展调用 (top)")
if tool_cnt:
    for k,v in sorted(tool_cnt.items(),key=lambda x:-x[1])[:15]: print(f"  {k}: {v}")
else:
    print("  (无)")
print()
print("### 活跃日期 (近7天)")
for d in sorted(per_day.keys())[-7:]: print(f"  {d}: {per_day[d]['sess']}会话/{f(per_day[d]['turns'])}轮")
print()
print("### 每日趋势 (近10天)")
maxd=max([per_day[d]["turns"] for d in per_day] or [1])
for d in sorted(per_day.keys())[-10:]:
    bar="#"*max(1,int(per_day[d]["turns"]/max(1,maxd)*30))
    print(f"  {d} {f(per_day[d]['turns']):>6} {bar}")
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
