"""Render the pending topic review as a self-contained judging page.

Reads the blind pool and the published mirror, writes one HTML file. The page never
reveals which method retrieved a candidate; it only shows the blind ID, the document,
and the two judgement buttons. Decisions are exported as a small JSON file that
apply_topic_review_decisions.py merges back into the review manifest.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

WORKTREE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
REVIEW = WORKTREE / "eval/querysets/topic-smoke-v1.review.json"
INDEX = WORKTREE / "agent/.index"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.cwd() / "topic-review.html"

review = json.loads(REVIEW.read_text(encoding="utf-8"))
catalog = json.loads((INDEX / "catalog.json").read_text(encoding="utf-8"))

meta = {entry["doc_id"]: entry for entry in catalog["documents"]}

pooled = {c["doc_id"] for q in review["queries"] for c in q["candidates"]}
docs: dict[str, dict[str, object]] = {}
for doc_id in sorted(pooled):
    entry = meta[doc_id]
    docs[doc_id] = {
        "title": entry.get("title") or doc_id,
        "category": entry.get("category", ""),
        "date": entry.get("date", ""),
        "description": entry.get("description", ""),
        "tags": entry.get("tags", []),
        "body": (INDEX / "posts" / doc_id).read_text(encoding="utf-8"),
    }

corpus = [
    {
        "doc_id": entry["doc_id"],
        "title": entry.get("title") or entry["doc_id"],
        "description": entry.get("description", ""),
        "pooled": entry["doc_id"] in pooled,
    }
    for entry in sorted(catalog["documents"], key=lambda e: e["doc_id"])
]

queries = [
    {
        "query_id": q["query_id"],
        "query": q["query"],
        "candidates": [
            {
                "blind_id": c["blind_id"],
                "doc_id": c["doc_id"],
                "judgement": c["judgement"],
            }
            for c in q["candidates"]
        ],
        "additional_relevant_doc_ids": q["additional_relevant_doc_ids"],
        "candidate_pool_complete": q["candidate_pool_complete"],
    }
    for q in review["queries"]
]

payload = json.dumps(
    {"queries": queries, "docs": docs, "corpus": corpus},
    ensure_ascii=False,
)

HTML = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<title>topic-smoke-v1 관련성 채점</title>
<style>
:root{--bg:#fbfbfa;--fg:#1a1a19;--mut:#6b6b68;--line:#e3e3e0;--card:#fff;
--yes:#1f7a4d;--yes-bg:#e6f4ec;--no:#a33;--no-bg:#fbeaea;--acc:#2c5fd6}
@media(prefers-color-scheme:dark){:root{--bg:#17171a;--fg:#e8e8e6;--mut:#9a9a97;
--line:#2e2e33;--card:#1f1f23;--yes:#5cc98d;--yes-bg:#17301f;--no:#e08585;
--no-bg:#301818;--acc:#7aa2f7}}
*{box-sizing:border-box}
body{margin:0;font:15px/1.6 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",sans-serif;
background:var(--bg);color:var(--fg)}
header{position:sticky;top:0;z-index:10;background:var(--bg);border-bottom:1px solid var(--line);
padding:12px 20px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
h1{font-size:15px;margin:0;font-weight:600}
select{font:inherit;padding:5px 8px;background:var(--card);color:var(--fg);
border:1px solid var(--line);border-radius:6px}
.bar{flex:1;min-width:160px;height:6px;background:var(--line);border-radius:3px;overflow:hidden}
.bar>i{display:block;height:100%;background:var(--acc);width:0;transition:width .2s}
.count{font-variant-numeric:tabular-nums;color:var(--mut);font-size:13px}
button{font:inherit;cursor:pointer;border:1px solid var(--line);background:var(--card);
color:var(--fg);border-radius:6px;padding:6px 12px}
button:hover{border-color:var(--acc)}
main{max-width:820px;margin:0 auto;padding:20px}
.q{font-size:20px;font-weight:600;margin:0 0 4px}
.hint{color:var(--mut);font-size:13px;margin:0 0 20px}
kbd{font:12px ui-monospace,monospace;background:var(--line);border-radius:4px;padding:1px 5px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:16px;margin-bottom:12px}
.card.on{border-color:var(--acc);box-shadow:0 0 0 3px color-mix(in srgb,var(--acc) 18%,transparent)}
.card.yes{border-left:4px solid var(--yes);background:var(--yes-bg)}
.card.no{border-left:4px solid var(--no);background:var(--no-bg);opacity:.72}
.t{font-weight:600;margin:0 0 4px}
.m{color:var(--mut);font-size:12.5px;margin:0 0 8px;word-break:break-all}
.d{margin:0 0 12px}
.acts{display:flex;gap:8px;align-items:center}
.acts .sp{flex:1}
button.y.act{background:var(--yes);border-color:var(--yes);color:#fff}
button.n.act{background:var(--no);border-color:var(--no);color:#fff}
details>summary{cursor:pointer;color:var(--acc);font-size:13.5px;margin-bottom:8px}
pre.body{white-space:pre-wrap;word-break:break-word;font:13px/1.65 ui-monospace,monospace;
background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:12px;
max-height:460px;overflow:auto;margin:0}
.panel{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:16px;margin:28px 0}
.panel h3{margin:0 0 10px;font-size:15px}
input[type=search]{width:100%;font:inherit;padding:8px 10px;background:var(--bg);
color:var(--fg);border:1px solid var(--line);border-radius:6px;margin-bottom:10px}
.hits{max-height:260px;overflow:auto}
.hit{display:flex;gap:10px;align-items:flex-start;padding:7px 0;border-top:1px solid var(--line)}
.hit .g{flex:1;min-width:0}
.hit .g div:first-child{font-size:13.5px}
.hit .g div:last-child{color:var(--mut);font-size:12px;word-break:break-all}
.chip{display:inline-flex;align-items:center;gap:8px;background:var(--yes-bg);
color:var(--yes);border-radius:999px;padding:4px 10px;font-size:13px;margin:0 6px 6px 0}
.chip button{border:0;background:0;color:inherit;padding:0;font-size:15px;line-height:1}
label.cp{display:flex;gap:9px;align-items:flex-start;margin-top:14px;font-size:14px}
footer{border-top:1px solid var(--line);margin-top:32px;padding:20px 0;
display:flex;gap:12px;align-items:center;flex-wrap:wrap}
footer .sp{flex:1}
button.primary{background:var(--acc);border-color:var(--acc);color:#fff;font-weight:600}
.warn{color:var(--mut);font-size:13px}
</style></head><body>
<header>
  <h1>관련성 채점</h1>
  <select id="pick"></select>
  <div class="bar"><i id="fill"></i></div>
  <span class="count" id="count"></span>
  <button id="jump">다음 미판정</button>
</header>
<main>
  <p class="q" id="qtext"></p>
  <p class="hint">이 질문을 한 사람에게 <b>답이 되는 글이면 관련</b>, 아니면 관련없음.
  주제가 스치기만 하는 글은 관련없음입니다.
  <kbd>J</kbd>/<kbd>K</kbd> 이동 · <kbd>R</kbd> 관련 · <kbd>N</kbd> 관련없음 · <kbd>Space</kbd> 본문</p>
  <div id="cards"></div>

  <div class="panel">
    <h3>후보에 없는 관련 문서 추가</h3>
    <p class="warn">여섯 방법 모두가 놓친 글이 있다면 여기서 찾아 추가하세요. 이미 후보에 있는 글은 추가할 수 없습니다.</p>
    <input type="search" id="q" placeholder="제목 또는 경로 검색 (335개 전체)">
    <div class="hits" id="hits"></div>
    <div id="added" style="margin-top:12px"></div>
  </div>

  <label class="cp"><input type="checkbox" id="complete">
    <span><b>이 질문의 관련 문서 집합이 충분히 완결됐다고 판단합니다.</b><br>
    <span class="warn">재현율(recall) 계산의 근거가 되는 선언입니다. 모든 후보를 판정하고, 놓친 글을 찾아본 뒤 체크하세요.</span></span>
  </label>

  <footer>
    <span class="count" id="total"></span>
    <span class="sp"></span>
    <button id="export" class="primary">판정 결과 내보내기</button>
  </footer>
</main>
<script>
const DATA = __PAYLOAD__;
const KEY = "topic-smoke-v1-decisions";
let state = JSON.parse(localStorage.getItem(KEY) || "null");
if (!state) {
  state = {judgements:{}, additions:{}, complete:{}};
  for (const q of DATA.queries) {
    for (const c of q.candidates)
      if (c.judgement !== "pending") state.judgements[c.blind_id] = c.judgement;
    state.additions[q.query_id] = q.additional_relevant_doc_ids.slice();
    state.complete[q.query_id] = q.candidate_pool_complete;
  }
}
const save = () => localStorage.setItem(KEY, JSON.stringify(state));

let qi = 0, ci = 0;
const $ = id => document.getElementById(id);
const cur = () => DATA.queries[qi];

$("pick").innerHTML = DATA.queries
  .map((q,i) => `<option value="${i}">${q.query}</option>`).join("");
$("pick").onchange = e => { qi = +e.target.value; ci = 0; render(); };

function judged(q) {
  return q.candidates.filter(c => state.judgements[c.blind_id]).length;
}

function render() {
  const q = cur();
  $("pick").value = qi;
  $("qtext").textContent = q.query;
  const done = judged(q), n = q.candidates.length;
  $("fill").style.width = (done/n*100) + "%";
  $("count").textContent = `${done} / ${n}`;
  const all = DATA.queries.reduce((a,x) => a + x.candidates.length, 0);
  const allDone = DATA.queries.reduce((a,x) => a + judged(x), 0);
  $("total").textContent = `전체 ${allDone} / ${all} 판정 · 완결 선언 `
    + `${Object.values(state.complete).filter(Boolean).length} / ${DATA.queries.length}`;

  $("cards").innerHTML = q.candidates.map((c,i) => {
    const d = DATA.docs[c.doc_id], j = state.judgements[c.blind_id];
    const cls = ["card", i===ci?"on":"", j==="relevant"?"yes":j==="not-relevant"?"no":""]
      .filter(Boolean).join(" ");
    const tags = (d.tags||[]).length ? " · " + d.tags.join(", ") : "";
    return `<div class="${cls}" data-i="${i}" id="c${i}">
      <p class="t">${esc(d.title)}</p>
      <p class="m">${esc(d.category)} · ${esc(d.date)}${esc(tags)}<br>${esc(c.doc_id)}</p>
      <p class="d">${esc(d.description)}</p>
      <details><summary>본문 보기</summary><pre class="body">${esc(d.body)}</pre></details>
      <div class="acts">
        <button class="y ${j==="relevant"?"act":""}" data-j="relevant" data-i="${i}">관련</button>
        <button class="n ${j==="not-relevant"?"act":""}" data-j="not-relevant" data-i="${i}">관련없음</button>
        <span class="sp"></span>
        ${j ? `<button data-clear="${i}">되돌리기</button>` : ""}
      </div></div>`;
  }).join("");

  $("complete").checked = !!state.complete[q.query_id];
  renderAdded();
  search();
}

const esc = s => String(s ?? "").replace(/[&<>]/g, m => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[m]));

$("cards").onclick = e => {
  const b = e.target.closest("button");
  if (b) {
    const i = +(b.dataset.i ?? b.dataset.clear);
    const c = cur().candidates[i];
    if (b.dataset.clear !== undefined) delete state.judgements[c.blind_id];
    else state.judgements[c.blind_id] = b.dataset.j;
    ci = i; save(); render();
    if (b.dataset.clear === undefined) next();
    return;
  }
  const card = e.target.closest(".card");
  if (card && !e.target.closest("details")) { ci = +card.dataset.i; render(); }
};

function focus() {
  const el = $("c"+ci);
  if (el) el.scrollIntoView({block:"center", behavior:"smooth"});
}
function next() {
  const q = cur();
  for (let k=1; k<=q.candidates.length; k++) {
    const i = (ci+k) % q.candidates.length;
    if (!state.judgements[q.candidates[i].blind_id]) { ci = i; render(); focus(); return; }
  }
}
$("jump").onclick = next;

document.onkeydown = e => {
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.metaKey || e.ctrlKey) return;
  const q = cur(), c = q.candidates[ci];
  const k = e.key.toLowerCase();
  if (k === "j") { ci = Math.min(ci+1, q.candidates.length-1); render(); focus(); }
  else if (k === "k") { ci = Math.max(ci-1, 0); render(); focus(); }
  else if (k === "r" || k === "n") {
    state.judgements[c.blind_id] = k === "r" ? "relevant" : "not-relevant";
    save(); render(); next();
  } else if (e.key === " ") {
    const d = $("c"+ci).querySelector("details");
    d.open = !d.open; e.preventDefault();
  } else return;
  e.preventDefault();
};

$("complete").onchange = e => {
  state.complete[cur().query_id] = e.target.checked; save(); render();
};

function search() {
  const term = $("q").value.trim().toLowerCase();
  const added = state.additions[cur().query_id];
  const hits = DATA.corpus
    .filter(d => !d.pooled && !added.includes(d.doc_id))
    .filter(d => !term || d.title.toLowerCase().includes(term)
      || d.doc_id.toLowerCase().includes(term)
      || d.description.toLowerCase().includes(term))
    .slice(0, 40);
  $("hits").innerHTML = hits.length
    ? hits.map(d => `<div class="hit"><div class="g"><div>${esc(d.title)}</div>
        <div>${esc(d.doc_id)}</div></div>
        <button data-add="${esc(d.doc_id)}">추가</button></div>`).join("")
    : `<p class="warn">${term ? "검색 결과 없음" : "검색어를 입력하세요"}</p>`;
}
$("q").oninput = search;
$("hits").onclick = e => {
  const b = e.target.closest("button[data-add]");
  if (!b) return;
  state.additions[cur().query_id].push(b.dataset.add);
  state.additions[cur().query_id].sort();
  save(); renderAdded(); search();
};
function renderAdded() {
  const a = state.additions[cur().query_id];
  $("added").innerHTML = a.length
    ? a.map(id => `<span class="chip">${esc(id)}<button data-del="${esc(id)}">×</button></span>`).join("")
    : `<span class="warn">추가된 문서 없음</span>`;
}
$("added").onclick = e => {
  const b = e.target.closest("button[data-del]");
  if (!b) return;
  const a = state.additions[cur().query_id];
  a.splice(a.indexOf(b.dataset.del), 1);
  save(); renderAdded(); search();
};

$("export").onclick = () => {
  const blob = new Blob([JSON.stringify(state, null, 2)], {type:"application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "topic-decisions.json";
  a.click();
};

render();
</script></body></html>
"""

OUT.write_text(HTML.replace("__PAYLOAD__", payload), encoding="utf-8")
print(f"{OUT}  ({OUT.stat().st_size / 1024:.0f} KB)")
