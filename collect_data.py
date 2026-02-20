"""Collect GitHub data from PostHog/posthog for the last 90 days.

Uses a two-phase approach:
1. REST pulls list API for all merged PRs (bulk, ~50 requests)
2. GraphQL API for reviews + files of top contributors (separate rate limit)
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone

import requests

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
REPO_OWNER = "PostHog"
REPO_NAME = "posthog"
BASE_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"
GRAPHQL_URL = "https://api.github.com/graphql"
HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}
CUTOFF = datetime.now(timezone.utc) - timedelta(days=90)


def api_get(url, params=None):
    while True:
        r = requests.get(url, headers=HEADERS, params=params)
        if r.status_code == 403 and "rate limit" in r.text.lower():
            reset = int(r.headers.get("X-RateLimit-Reset", time.time() + 60))
            wait = max(reset - int(time.time()), 1) + 5
            print(f"  Rate limited, waiting {wait}s...", flush=True)
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r


def graphql(query, variables=None):
    while True:
        r = requests.post(
            GRAPHQL_URL,
            headers={"Authorization": f"bearer {GITHUB_TOKEN}"},
            json={"query": query, "variables": variables or {}},
        )
        if r.status_code == 403:
            reset = int(r.headers.get("X-RateLimit-Reset", time.time() + 60))
            wait = max(reset - int(time.time()), 1) + 5
            print(f"  GraphQL rate limited, waiting {wait}s...", flush=True)
            time.sleep(wait)
            continue
        r.raise_for_status()
        data = r.json()
        if "errors" in data:
            print(f"  GraphQL errors: {data['errors']}", flush=True)
        return data


def fetch_all_merged_prs():
    """Fetch merged PRs via REST pulls list API (bulk)."""
    print("Phase 1: Fetching merged PRs via REST API...", flush=True)
    all_prs = []
    page = 1
    while True:
        r = api_get(f"{BASE_URL}/pulls", params={
            "state": "closed", "sort": "updated", "direction": "desc",
            "per_page": 100, "page": page,
        })
        pulls = r.json()
        if not pulls:
            break

        stop = False
        for pr in pulls:
            updated = datetime.fromisoformat(pr["updated_at"].replace("Z", "+00:00"))
            if updated < CUTOFF:
                stop = True
                break
            if pr.get("merged_at"):
                merged = datetime.fromisoformat(pr["merged_at"].replace("Z", "+00:00"))
                if merged >= CUTOFF:
                    all_prs.append(pr)

        print(f"  Page {page}: {len(all_prs)} merged PRs collected", flush=True)
        if stop:
            break
        page += 1

    print(f"Total merged PRs: {len(all_prs)}", flush=True)
    return all_prs


def fetch_reviews_graphql(pr_numbers):
    """Fetch reviews for PRs using GraphQL (much more efficient)."""
    print(f"\nPhase 2: Fetching reviews via GraphQL for {len(pr_numbers)} PRs...", flush=True)
    reviews = []

    # Process in batches of 25 PRs per query
    batch_size = 25
    for batch_start in range(0, len(pr_numbers), batch_size):
        batch = pr_numbers[batch_start:batch_start + batch_size]
        if (batch_start // batch_size) % 10 == 0:
            print(f"  GraphQL batch {batch_start // batch_size + 1}/{(len(pr_numbers) + batch_size - 1) // batch_size}...", flush=True)

        # Build aliases for each PR
        aliases = []
        for i, num in enumerate(batch):
            aliases.append(f"""
                pr_{i}: pullRequest(number: {num}) {{
                    number
                    author {{ login }}
                    reviews(first: 50) {{
                        nodes {{
                            author {{ login }}
                            state
                            body
                        }}
                    }}
                    files(first: 100) {{
                        nodes {{
                            path
                        }}
                    }}
                }}
            """)

        query = f"""
        query {{
            repository(owner: "{REPO_OWNER}", name: "{REPO_NAME}") {{
                {"".join(aliases)}
            }}
        }}
        """

        result = graphql(query)
        repo_data = result.get("data", {}).get("repository", {})

        for i, num in enumerate(batch):
            pr_data = repo_data.get(f"pr_{i}")
            if not pr_data:
                continue

            pr_author = (pr_data.get("author") or {}).get("login", "unknown")

            # Reviews
            for rev in (pr_data.get("reviews", {}).get("nodes") or []):
                reviewer = (rev.get("author") or {}).get("login", "unknown")
                if reviewer.endswith("[bot]"):
                    continue
                reviews.append({
                    "pr_number": num,
                    "pr_author": pr_author,
                    "reviewer": reviewer,
                    "state": rev.get("state", ""),
                    "body_length": len(rev.get("body", "") or ""),
                })

        time.sleep(0.5)  # be nice to GraphQL API

    print(f"Collected {len(reviews)} reviews via GraphQL.", flush=True)
    return reviews


def fetch_files_graphql(pr_numbers):
    """Fetch file paths for PRs using GraphQL."""
    print(f"\nPhase 3: Fetching files via GraphQL for {len(pr_numbers)} PRs...", flush=True)
    pr_files = {}

    batch_size = 25
    for batch_start in range(0, len(pr_numbers), batch_size):
        batch = pr_numbers[batch_start:batch_start + batch_size]
        if (batch_start // batch_size) % 10 == 0:
            print(f"  Files batch {batch_start // batch_size + 1}/{(len(pr_numbers) + batch_size - 1) // batch_size}...", flush=True)

        aliases = []
        for i, num in enumerate(batch):
            aliases.append(f"""
                pr_{i}: pullRequest(number: {num}) {{
                    number
                    files(first: 100) {{
                        nodes {{
                            path
                        }}
                    }}
                }}
            """)

        query = f"""
        query {{
            repository(owner: "{REPO_OWNER}", name: "{REPO_NAME}") {{
                {"".join(aliases)}
            }}
        }}
        """

        result = graphql(query)
        repo_data = result.get("data", {}).get("repository", {})

        for i, num in enumerate(batch):
            pr_data = repo_data.get(f"pr_{i}")
            if not pr_data:
                continue
            files = [n["path"] for n in (pr_data.get("files", {}).get("nodes") or []) if n]
            pr_files[num] = files

        time.sleep(0.5)

    print(f"Got file lists for {len(pr_files)} PRs.", flush=True)
    return pr_files


def categorize_file(filepath):
    parts = filepath.split("/")
    if not parts:
        return "root"
    if parts[0] == "products" and len(parts) >= 2:
        return f"products/{parts[1]}"
    if parts[0] == "frontend":
        if len(parts) >= 3 and parts[1] == "src":
            return f"frontend/{parts[2]}"
        return "frontend"
    if parts[0] == "posthog" and len(parts) >= 2:
        return f"posthog/{parts[1]}"
    if parts[0] in ("ee", "plugin-server", "rust", "hogvm", "dags"):
        return parts[0]
    return parts[0]


def collect_all():
    # Phase 1: REST API for all merged PRs
    prs_raw = fetch_all_merged_prs()

    # Build PR records, filter bots
    prs = []
    author_pr_counts = {}
    for pr in prs_raw:
        author = pr.get("user", {}).get("login", "unknown")
        user_type = pr.get("user", {}).get("type", "")
        if user_type == "Bot" or author.endswith("[bot]") or author in ("dependabot", "github-actions"):
            continue

        prs.append({
            "number": pr["number"],
            "title": pr.get("title", ""),
            "author": author,
            "merged_at": pr.get("merged_at"),
            "additions": pr.get("additions", 0),
            "deletions": pr.get("deletions", 0),
            "changed_files": pr.get("changed_files", 0),
            "comments": pr.get("comments", 0),
            "review_comments": pr.get("review_comments", 0),
            "labels": [l["name"] for l in pr.get("labels", [])],
            "files": [],
            "areas": [],
        })
        author_pr_counts[author] = author_pr_counts.get(author, 0) + 1

    print(f"\n{len(prs)} non-bot PRs from {len(author_pr_counts)} engineers.", flush=True)

    # Phase 2: GraphQL for reviews (all PRs — GraphQL has separate limit)
    all_pr_numbers = [pr["number"] for pr in prs]
    reviews = fetch_reviews_graphql(all_pr_numbers)

    # Phase 3: GraphQL for files (top 40 contributors only)
    top_authors = sorted(author_pr_counts, key=author_pr_counts.get, reverse=True)[:40]
    top_pr_nums = [pr["number"] for pr in prs if pr["author"] in top_authors]
    pr_files = fetch_files_graphql(top_pr_nums)

    # Merge files back into PR records
    pr_lookup = {pr["number"]: pr for pr in prs}
    for num, files in pr_files.items():
        if num in pr_lookup:
            pr_lookup[num]["files"] = files
            pr_lookup[num]["areas"] = list(set(categorize_file(fp) for fp in files))

    for pr in prs:
        if not pr["areas"]:
            pr["areas"] = ["unknown"]

    # Save
    output = {
        "prs": prs,
        "reviews": reviews,
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }
    with open("/Users/polys/impact-dashboard/data.json", "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nDone! Saved {len(prs)} PRs and {len(reviews)} reviews to data.json", flush=True)


if __name__ == "__main__":
    collect_all()
