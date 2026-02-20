"""Analyze GitHub data and compute engineer impact scores."""

import json

import pandas as pd


def load_data(path="data.json"):
    with open(path) as f:
        return json.load(f)


BOT_ACCOUNTS = {
    "greptile-apps", "copilot-pull-request-reviewer", "cubic-dev-ai",
    "graphite-app", "chatgpt-codex-connector", "github-advanced-security",
    "dependabot", "github-actions", "posthog-bot",
}


def compute_scores(data):
    """Compute impact scores for each engineer.

    Three dimensions:
    1. PR Impact: weighted by files changed, breadth (areas touched), review discussion
    2. Review Influence: reviews given, weighted by substantiveness
    3. Scope of Ownership: distinct product areas contributed to
    """
    prs = pd.DataFrame(data["prs"])
    reviews = pd.DataFrame(data["reviews"])

    # Filter out bots
    prs = prs[~prs["author"].isin(BOT_ACCOUNTS)]
    if not reviews.empty:
        reviews = reviews[~reviews["reviewer"].isin(BOT_ACCOUNTS)]

    if prs.empty:
        return pd.DataFrame()

    # --- 1. PR Impact ---
    # Score each PR, then aggregate per author
    prs["area_count"] = prs["areas"].apply(len)
    prs["pr_score"] = (
        prs["changed_files"].clip(upper=50) * 0.3  # files changed (capped)
        + prs["area_count"] * 5  # breadth bonus
        + prs["review_comments"] * 2  # discussion depth
        + (prs["additions"] + prs["deletions"]).clip(upper=2000) * 0.01  # size (capped)
    )

    pr_impact = prs.groupby("author").agg(
        pr_count=("number", "count"),
        total_pr_score=("pr_score", "sum"),
        avg_pr_score=("pr_score", "mean"),
        total_additions=("additions", "sum"),
        total_deletions=("deletions", "sum"),
        total_files_changed=("changed_files", "sum"),
        total_review_comments_received=("review_comments", "sum"),
    ).reset_index()

    # --- 2. Review Influence ---
    if not reviews.empty:
        # Weight reviews: substantive comments (body_length > 20) count more
        reviews["review_weight"] = reviews["body_length"].apply(
            lambda x: 3 if x > 100 else (2 if x > 20 else 1)
        )
        review_influence = reviews.groupby("reviewer").agg(
            reviews_given=("pr_number", "count"),
            substantive_reviews=("review_weight", lambda x: (x >= 2).sum()),
            total_review_weight=("review_weight", "sum"),
        ).reset_index().rename(columns={"reviewer": "author"})
    else:
        review_influence = pd.DataFrame(columns=["author", "reviews_given", "substantive_reviews", "total_review_weight"])

    # --- 3. Scope of Ownership ---
    all_areas = prs.explode("areas").dropna(subset=["areas"])
    scope = all_areas.groupby("author")["areas"].nunique().reset_index()
    scope.columns = ["author", "unique_areas"]

    # --- Merge and compute composite ---
    df = pr_impact.merge(review_influence, on="author", how="outer")
    df = df.merge(scope, on="author", how="outer")
    df = df.fillna(0)

    # Normalize each dimension to 0-100 scale
    def normalize(series):
        mn, mx = series.min(), series.max()
        if mx == mn:
            return pd.Series([50] * len(series), index=series.index)
        return ((series - mn) / (mx - mn)) * 100

    df["pr_impact_norm"] = normalize(df["total_pr_score"])
    df["review_influence_norm"] = normalize(df["total_review_weight"])
    df["scope_norm"] = normalize(df["unique_areas"])

    # Composite score (weighted)
    df["impact_score"] = (
        df["pr_impact_norm"] * 0.50
        + df["review_influence_norm"] * 0.30
        + df["scope_norm"] * 0.20
    )

    df = df.sort_values("impact_score", ascending=False)
    return df


def get_top_engineers(df, n=5):
    return df.head(n)


def get_pr_details_for_engineer(data, author):
    """Get notable PRs for a specific engineer."""
    prs = pd.DataFrame(data["prs"])
    engineer_prs = prs[prs["author"] == author].copy()
    engineer_prs["area_count"] = engineer_prs["areas"].apply(len)
    engineer_prs["pr_score"] = (
        engineer_prs["changed_files"].clip(upper=50) * 0.3
        + engineer_prs["area_count"] * 5
        + engineer_prs["review_comments"] * 2
        + (engineer_prs["additions"] + engineer_prs["deletions"]).clip(upper=2000) * 0.01
    )
    return engineer_prs.sort_values("pr_score", ascending=False).head(5)


if __name__ == "__main__":
    data = load_data()
    df = compute_scores(data)
    top = get_top_engineers(df)
    print("\nTop 5 Most Impactful Engineers (last 90 days):\n")
    for i, row in top.iterrows():
        print(f"  {row['author']:25s} | Score: {row['impact_score']:.1f} | "
              f"PRs: {int(row['pr_count'])} | Reviews: {int(row['reviews_given'])} | "
              f"Areas: {int(row['unique_areas'])}")
