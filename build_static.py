"""Build a static HTML dashboard from the collected data."""

import json

import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from analyze import compute_scores, get_pr_details_for_engineer, load_data

data = load_data()
scores = compute_scores(data)
top5 = scores.head(5)
top10 = scores.head(10)

# --- Build HTML ---
html_parts = []

# Bar chart: top 5
fig_bar = px.bar(
    top5.iloc[::-1],  # reverse for horizontal
    x="impact_score",
    y="author",
    orientation="h",
    color="impact_score",
    color_continuous_scale="Tealgrn",
    labels={"impact_score": "Impact Score", "author": ""},
    title="Top 5 Most Impactful Engineers",
)
fig_bar.update_layout(
    showlegend=False,
    coloraxis_showscale=False,
    height=350,
    margin=dict(l=10, r=20, t=50, b=10),
    font=dict(size=14),
)
bar_html = fig_bar.to_html(full_html=False, include_plotlyjs=False)

# Radar chart
categories = ["PR Impact", "Review Influence", "Scope"]
fig_radar = go.Figure()
colors = px.colors.qualitative.Set2
for i, (_, row) in enumerate(top5.iterrows()):
    values = [row["pr_impact_norm"], row["review_influence_norm"], row["scope_norm"]]
    fig_radar.add_trace(go.Scatterpolar(
        r=values + [values[0]],
        theta=categories + [categories[0]],
        fill="toself",
        name=row["author"],
        line_color=colors[i % len(colors)],
        opacity=0.7,
    ))
fig_radar.update_layout(
    polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
    title="Score Breakdown by Dimension",
    height=400,
    margin=dict(l=60, r=60, t=60, b=40),
    font=dict(size=13),
)
radar_html = fig_radar.to_html(full_html=False, include_plotlyjs=False)

# Stacked bar for dimension comparison across top 10
fig_dims = go.Figure()
fig_dims.add_trace(go.Bar(
    y=top10["author"], x=top10["pr_impact_norm"] * 0.5,
    name="PR Impact (50%)", orientation="h", marker_color="#2ec4b6",
))
fig_dims.add_trace(go.Bar(
    y=top10["author"], x=top10["review_influence_norm"] * 0.3,
    name="Review Influence (30%)", orientation="h", marker_color="#e71d36",
))
fig_dims.add_trace(go.Bar(
    y=top10["author"], x=top10["scope_norm"] * 0.2,
    name="Scope (20%)", orientation="h", marker_color="#ff9f1c",
))
fig_dims.update_layout(
    barmode="stack",
    title="Impact Score Composition (Top 10)",
    xaxis_title="Weighted Score Contribution",
    height=420,
    margin=dict(l=10, r=20, t=50, b=40),
    font=dict(size=13),
    yaxis=dict(categoryorder="total ascending"),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
)
dims_html = fig_dims.to_html(full_html=False, include_plotlyjs=False)

# Notable PRs for top 5
notable_html = ""
for _, row in top5.iterrows():
    author = row["author"]
    prs_detail = get_pr_details_for_engineer(data, author)
    notable_html += f'<div class="engineer-prs"><h4>{author}</h4><ul>'
    for _, pr in prs_detail.iterrows():
        areas = ", ".join(pr["areas"][:3]) if isinstance(pr["areas"], list) else "unknown"
        notable_html += (
            f'<li><a href="https://github.com/PostHog/posthog/pull/{int(pr["number"])}" target="_blank">'
            f'#{int(pr["number"])}</a> {pr["title"][:80]} '
            f'<span class="pr-stats">+{pr["additions"]}/-{pr["deletions"]} | '
            f'{pr["changed_files"]} files | {pr["review_comments"]} review comments</span></li>'
        )
    notable_html += "</ul></div>"

# Summary table
table_rows = ""
for rank, (_, row) in enumerate(top5.iterrows(), 1):
    table_rows += f"""<tr>
        <td>{rank}</td>
        <td><strong>{row['author']}</strong></td>
        <td>{int(row['pr_count'])}</td>
        <td>{int(row['reviews_given'])}</td>
        <td>{int(row['unique_areas'])}</td>
        <td><strong>{row['impact_score']:.1f}</strong></td>
    </tr>"""

# Stats
total_engineers = len(scores)
total_prs = int(scores["pr_count"].sum())
total_reviews = int(scores["reviews_given"].sum())

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PostHog Engineering Impact Dashboard</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f1117; color: #fafafa; padding: 20px 40px; }}
        h1 {{ font-size: 1.8rem; margin-bottom: 4px; }}
        .subtitle {{ color: #888; font-size: 0.9rem; margin-bottom: 16px; }}
        .methodology {{ background: #1a1c23; border-left: 3px solid #2ec4b6; padding: 12px 16px; margin-bottom: 20px; font-size: 0.85rem; line-height: 1.5; color: #ccc; }}
        .methodology strong {{ color: #fafafa; }}
        .grid {{ display: grid; grid-template-columns: 3fr 2fr; gap: 20px; margin-bottom: 20px; }}
        .grid-equal {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
        th {{ background: #1a1c23; padding: 8px 12px; text-align: left; color: #888; font-weight: 500; }}
        td {{ padding: 8px 12px; border-bottom: 1px solid #262730; }}
        .stats {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 20px; }}
        .stat {{ background: #1a1c23; padding: 16px; border-radius: 8px; text-align: center; }}
        .stat-value {{ font-size: 1.8rem; font-weight: 700; color: #2ec4b6; }}
        .stat-label {{ font-size: 0.8rem; color: #888; margin-top: 4px; }}
        .notable-section {{ margin-top: 20px; }}
        .notable-section h3 {{ margin-bottom: 12px; font-size: 1.1rem; }}
        .engineer-prs {{ margin-bottom: 12px; }}
        .engineer-prs h4 {{ color: #2ec4b6; margin-bottom: 4px; font-size: 0.95rem; }}
        .engineer-prs ul {{ list-style: none; padding-left: 0; }}
        .engineer-prs li {{ font-size: 0.82rem; margin-bottom: 3px; padding: 3px 0; border-bottom: 1px solid #1a1c23; }}
        .engineer-prs a {{ color: #6ea8fe; text-decoration: none; }}
        .pr-stats {{ color: #666; font-size: 0.75rem; }}
        .divider {{ border: none; border-top: 1px solid #262730; margin: 16px 0; }}
    </style>
</head>
<body>
    <h1>PostHog Engineering Impact Dashboard</h1>
    <p class="subtitle">Last 90 days &middot; Data from github.com/PostHog/posthog &middot; {total_prs} PRs by {total_engineers} engineers</p>

    <div class="methodology">
        <strong>How we measure impact:</strong>
        <strong>PR Impact</strong> (50%) &mdash; complexity, breadth across codebase areas, and review discussion depth.
        <strong>Review Influence</strong> (30%) &mdash; volume and substantiveness of code reviews given to others.
        <strong>Scope</strong> (20%) &mdash; number of distinct product areas contributed to.
        Raw metrics like lines of code are capped to avoid rewarding bulk changes.
    </div>

    <div class="stats">
        <div class="stat"><div class="stat-value">{total_engineers}</div><div class="stat-label">Active Engineers</div></div>
        <div class="stat"><div class="stat-value">{total_prs:,}</div><div class="stat-label">PRs Merged</div></div>
        <div class="stat"><div class="stat-value">{total_reviews:,}</div><div class="stat-label">Code Reviews</div></div>
    </div>

    <div class="grid">
        <div>{bar_html}</div>
        <div>
            <table>
                <thead><tr><th>#</th><th>Engineer</th><th>PRs</th><th>Reviews</th><th>Areas</th><th>Score</th></tr></thead>
                <tbody>{table_rows}</tbody>
            </table>
        </div>
    </div>

    <hr class="divider">

    <div class="grid-equal">
        <div>{radar_html}</div>
        <div>{dims_html}</div>
    </div>

    <hr class="divider">

    <div class="notable-section">
        <h3>Most Impactful PRs by Top Engineers</h3>
        {notable_html}
    </div>
</body>
</html>"""

# Write output
with open("/Users/polys/impact-dashboard/index.html", "w") as f:
    f.write(html)

print("Built index.html")
