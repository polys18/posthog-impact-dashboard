"""Engineering Impact Dashboard for PostHog."""

import json

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from analyze import compute_scores, get_pr_details_for_engineer, load_data

st.set_page_config(page_title="PostHog Engineering Impact", layout="wide")

# --- Load and compute ---
@st.cache_data
def get_data():
    data = load_data()
    scores = compute_scores(data)
    return data, scores


data, scores = get_data()
top5 = scores.head(5)

# --- Header ---
st.title("PostHog Engineering Impact Dashboard")
st.caption("Last 90 days | Data from github.com/PostHog/posthog")

st.markdown(
    """
**How we measure impact:** Engineers are scored across three dimensions —
**PR Impact** (50%): complexity, breadth across codebase areas, and review discussion depth.
**Review Influence** (30%): volume and substantiveness of code reviews given.
**Scope** (20%): number of distinct product areas contributed to.
Raw counts like lines of code are deliberately capped to avoid rewarding bulk changes.
"""
)

st.divider()

# --- Top 5 Overview ---
col_chart, col_table = st.columns([3, 2])

with col_chart:
    fig_bar = px.bar(
        top5,
        x="impact_score",
        y="author",
        orientation="h",
        color="impact_score",
        color_continuous_scale="Tealgrn",
        labels={"impact_score": "Impact Score", "author": "Engineer"},
        title="Top 5 Most Impactful Engineers",
    )
    fig_bar.update_layout(
        yaxis={"categoryorder": "total ascending"},
        showlegend=False,
        coloraxis_showscale=False,
        height=350,
        margin=dict(l=0, r=20, t=40, b=0),
    )
    st.plotly_chart(fig_bar, use_container_width=True)

with col_table:
    display_df = top5[["author", "pr_count", "reviews_given", "unique_areas", "impact_score"]].copy()
    display_df.columns = ["Engineer", "PRs Merged", "Reviews Given", "Areas Touched", "Impact Score"]
    display_df["Impact Score"] = display_df["Impact Score"].round(1)
    display_df = display_df.reset_index(drop=True)
    display_df.index = display_df.index + 1  # 1-indexed rank
    display_df.index.name = "Rank"
    st.markdown("#### Summary")
    st.dataframe(display_df, use_container_width=True, height=350)

# --- Radar Chart: Score Breakdown ---
st.divider()

col_radar, col_detail = st.columns([2, 3])

with col_radar:
    categories = ["PR Impact", "Review Influence", "Scope"]
    fig_radar = go.Figure()
    colors = px.colors.qualitative.Set2
    for i, (_, row) in enumerate(top5.iterrows()):
        values = [row["pr_impact_norm"], row["review_influence_norm"], row["scope_norm"]]
        fig_radar.add_trace(go.Scatterpolar(
            r=values + [values[0]],  # close the polygon
            theta=categories + [categories[0]],
            fill="toself",
            name=row["author"],
            line_color=colors[i % len(colors)],
            opacity=0.7,
        ))
    fig_radar.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        title="Score Breakdown",
        height=400,
        margin=dict(l=40, r=40, t=60, b=40),
    )
    st.plotly_chart(fig_radar, use_container_width=True)

with col_detail:
    st.markdown("#### Notable PRs")
    selected = st.selectbox(
        "Select engineer",
        options=top5["author"].tolist(),
    )
    if selected:
        notable_prs = get_pr_details_for_engineer(data, selected)
        for _, pr in notable_prs.iterrows():
            areas_str = ", ".join(pr["areas"][:3])
            st.markdown(
                f"- **[#{int(pr['number'])}](https://github.com/PostHog/posthog/pull/{int(pr['number'])})** "
                f"{pr['title'][:80]}  \n"
                f"  `+{pr['additions']}/-{pr['deletions']}` across {pr['changed_files']} files "
                f"| {pr['review_comments']} review comments | Areas: {areas_str}"
            )

# --- Footer with context ---
st.divider()
total_engineers = len(scores)
total_prs = int(scores["pr_count"].sum())
total_reviews = int(scores["reviews_given"].sum())
c1, c2, c3 = st.columns(3)
c1.metric("Total Engineers", total_engineers)
c2.metric("Total PRs Merged", total_prs)
c3.metric("Total Reviews", total_reviews)
