"""Dependency-free Markdown and SVG projections of the JSON run record."""

from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING, Protocol

from blogeval.datasets import DatasetKind, QuerySet

if TYPE_CHECKING:
    from blogeval.provenance import RunProvenance
    from blogeval.runner import MethodResult


class ReportRun(Protocol):
    run_id: str
    dataset: QuerySet
    cutoffs: tuple[int, ...]
    methods: tuple[MethodResult, ...]
    provenance: RunProvenance


def _markdown(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _metric_names(run: ReportRun) -> tuple[str, ...]:
    methods = run.methods
    if not methods:
        return ()
    values = methods[0].metrics.values
    preferred: list[str] = ["coverage"]
    for cutoff in run.cutoffs:
        if run.dataset.kind is DatasetKind.KNOWN_ITEM:
            preferred.extend((f"hit@{cutoff}", f"mrr@{cutoff}"))
        else:
            preferred.append(f"recall@{cutoff}")
    return tuple(name for name in preferred if name in values)


def render_leaderboard(run: ReportRun) -> str:
    dataset = run.dataset
    methods = run.methods
    metric_names = _metric_names(run)
    lines = [
        f"# Retrieval leaderboard: {_markdown(dataset.dataset_id)}",
        "",
        f"- Run: `{_markdown(run.run_id)}`",
        f"- Content tree: `{dataset.corpus.git_tree_sha}`",
        f"- Corpus fingerprint: `{dataset.corpus.fingerprint}`",
        f"- Dataset checksum: `{dataset.checksum}`",
        f"- Label status: **{dataset.labels.status.value}**",
        (
            "- Reviewed qrels checksum: "
            + (
                f"`{dataset.labels.reviewed_qrels_checksum}`"
                if dataset.labels.reviewed_qrels_checksum is not None
                else "not reviewed"
            )
        ),
        (
            "- Publication eligible: "
            + ("yes" if run.provenance.publication_eligible else "no")
        ),
        f"- Queries: {len(dataset.qrels)}",
        f"- Recorded exclusions: {len(dataset.exclusions)}",
        "",
    ]
    if dataset.kind is DatasetKind.KNOWN_ITEM:
        lines.extend(
            [
                "## Known-item metrics",
                "",
                "| Method | Data relation | Fingerprint | "
                + " | ".join(metric_names)
                + " |",
                "|---|---|---|" + "---:|" * len(metric_names),
            ]
        )
        for method in methods:
            lines.append(
                "| "
                + " | ".join(
                    (
                        _markdown(method.method_id),
                        _markdown(method.evaluation_relation),
                        f"`{_markdown(method.fingerprint)}`",
                        *(
                            f"{float(method.metrics.values[name]):.6f}"
                            for name in metric_names
                        ),
                    )
                )
                + " |"
            )
        lines.extend(
            [
                "",
                "## Topic metrics",
                "",
                "Not evaluated in this run. Topic recall requires a separately "
                "versioned, owner-reviewed multi-document qrel set.",
            ]
        )
    else:
        lines.extend(
            [
                "## Known-item metrics",
                "",
                "Not evaluated in this run.",
                "",
                "## Topic metrics",
                "",
                "| Method | Data relation | Fingerprint | "
                + " | ".join(metric_names)
                + " |",
                "|---|---|---|" + "---:|" * len(metric_names),
            ]
        )
        for method in methods:
            lines.append(
                "| "
                + " | ".join(
                    (
                        _markdown(method.method_id),
                        _markdown(method.evaluation_relation),
                        f"`{_markdown(method.fingerprint)}`",
                        *(
                            f"{float(method.metrics.values[name]):.6f}"
                            for name in metric_names
                        ),
                    )
                )
                + " |"
            )
    lines.extend(
        [
            "",
            "Coverage is the fraction of queries for which the method returned at "
            "least one document.",
            "",
        ]
    )
    return "\n".join(lines)


def render_per_query(run: ReportRun) -> str:
    dataset = run.dataset
    lines = [
        f"# Per-query results: {_markdown(dataset.dataset_id)}",
        "",
        f"Dataset kind: **{dataset.kind.value}**",
        "",
    ]
    for method in run.methods:
        metrics_by_id = {item.query_id: item for item in method.metrics.per_query}
        lines.extend(
            [
                f"## {_markdown(method.method_id)}",
                "",
                "| Query | Relevant | First relevant rank | Retrieved |",
                "|---|---|---:|---|",
            ]
        )
        for query in method.queries:
            metric = metrics_by_id[query.query_id]
            first_rank = (
                str(metric.first_relevant_rank)
                if metric.first_relevant_rank is not None
                else "—"
            )
            lines.append(
                "| "
                + " | ".join(
                    (
                        _markdown(query.query),
                        "<br>".join(
                            _markdown(value) for value in query.relevant_doc_ids
                        ),
                        first_rank,
                        "<br>".join(
                            _markdown(value) for value in query.retrieved_doc_ids
                        )
                        or "—",
                    )
                )
                + " |"
            )
        lines.append("")
    return "\n".join(lines)


def render_metrics_svg(run: ReportRun) -> str:
    """Render a fixed-layout, accessible horizontal bar chart."""

    metric_names = _metric_names(run)
    methods = run.methods
    rows = len(methods) * len(metric_names)
    width = 1080
    row_height = 34
    top = 112
    bottom = 54
    height = top + rows * row_height + bottom
    plot_x = 360
    plot_width = 620
    elements = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}" '
            'role="img" aria-labelledby="title desc">'
        ),
        '<title id="title">Retrieval evaluation metrics</title>',
        (
            '<desc id="desc">'
            + escape(f"{run.dataset.kind.value} metrics for {len(methods)} methods")
            + "</desc>"
        ),
        '<rect width="100%" height="100%" fill="#0b1020"/>',
        (
            '<text x="40" y="46" fill="#f8fafc" font-family="system-ui, sans-serif" '
            'font-size="24" font-weight="700">'
            + escape(run.dataset.dataset_id)
            + "</text>"
        ),
        (
            '<text x="40" y="76" fill="#94a3b8" font-family="system-ui, sans-serif" '
            'font-size="14">' + escape(f"run {run.run_id}") + "</text>"
        ),
        (
            f'<line x1="{plot_x}" y1="{top - 18}" x2="{plot_x + plot_width}" '
            f'y2="{top - 18}" stroke="#334155"/>'
        ),
    ]
    palette = ("#38bdf8", "#a78bfa", "#34d399", "#fb7185", "#fbbf24")
    row = 0
    for method_index, method in enumerate(methods):
        color = palette[method_index % len(palette)]
        for metric_name in metric_names:
            y = top + row * row_height
            value = float(method.metrics.values[metric_name])
            bar_width = round(plot_width * value, 3)
            label = f"{method.method_id} · {metric_name}"
            elements.extend(
                [
                    (
                        f'<text x="40" y="{y + 18}" fill="#cbd5e1" '
                        'font-family="ui-monospace, monospace" font-size="13">'
                        + escape(label)
                        + "</text>"
                    ),
                    (
                        f'<rect x="{plot_x}" y="{y}" width="{plot_width}" '
                        'height="22" rx="4" fill="#1e293b"/>'
                    ),
                    (
                        f'<rect x="{plot_x}" y="{y}" width="{bar_width}" '
                        f'height="22" rx="4" fill="{color}"/>'
                    ),
                    (
                        f'<text x="{plot_x + plot_width + 14}" y="{y + 17}" '
                        'fill="#f8fafc" font-family="ui-monospace, monospace" '
                        f'font-size="13">{value:.6f}</text>'
                    ),
                ]
            )
            row += 1
    elements.extend(
        [
            (
                f'<text x="40" y="{height - 22}" fill="#64748b" '
                'font-family="system-ui, sans-serif" font-size="12">'
                "All bars use a 0–1 scale; source of record is run.json."
                "</text>"
            ),
            "</svg>",
            "",
        ]
    )
    return "\n".join(elements)


__all__ = ["render_leaderboard", "render_metrics_svg", "render_per_query"]
