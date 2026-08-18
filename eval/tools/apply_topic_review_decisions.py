"""Merge exported judging decisions back into the pending review manifest.

Only `judgement`, `additional_relevant_doc_ids`, and `candidate_pool_complete` are
written. Everything the seal checksums - candidate generation, corpus, seed checksum,
blind IDs, query text, labels - is left byte-identical, and the file is re-serialized
in the exact form `generate-topic-review` emits.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

VALID = {"relevant", "not-relevant"}

decisions_path = Path(sys.argv[1])
worktree = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.cwd()
review_path = worktree / "eval/querysets/topic-smoke-v1.review.json"

decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
review = json.loads(review_path.read_text(encoding="utf-8"))

judgements = decisions.get("judgements", {})
additions = decisions.get("additions", {})
complete = decisions.get("complete", {})

pooled = {c["doc_id"] for q in review["queries"] for c in q["candidates"]}
known_blind = {c["blind_id"] for q in review["queries"] for c in q["candidates"]}
corpus_ids = {
    entry["doc_id"]
    for entry in json.loads(
        (worktree / "agent/.index/catalog.json").read_text(encoding="utf-8")
    )["documents"]
}

errors: list[str] = []
for blind_id, value in judgements.items():
    if blind_id not in known_blind:
        errors.append(f"unknown blind id {blind_id}")
    if value not in VALID:
        errors.append(f"illegal judgement {value!r} for {blind_id}")
for query_id, doc_ids in additions.items():
    for doc_id in doc_ids:
        if doc_id in pooled:
            errors.append(f"{query_id}: {doc_id} is already a pooled candidate")
        elif doc_id not in corpus_ids:
            errors.append(f"{query_id}: {doc_id} is not in the published mirror")
if errors:
    raise SystemExit("refusing to apply:\n  " + "\n  ".join(errors))

pending = 0
for query in review["queries"]:
    for candidate in query["candidates"]:
        value = judgements.get(candidate["blind_id"])
        candidate["judgement"] = value if value else "pending"
        pending += value is None
    query["additional_relevant_doc_ids"] = sorted(
        set(additions.get(query["query_id"], []))
    )
    query["candidate_pool_complete"] = bool(complete.get(query["query_id"], False))

review_path.write_text(
    json.dumps(review, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

incomplete = sum(not q["candidate_pool_complete"] for q in review["queries"])
print(
    json.dumps(
        {
            "written": str(review_path),
            "pending_judgement_count": pending,
            "incomplete_pool_count": incomplete,
            "relevant_label_count": sum(v == "relevant" for v in judgements.values()),
        }
    )
)
