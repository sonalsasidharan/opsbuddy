"""Find which Git commit a pod is running, and who wrote it (GitHub API).

Pod -> commit link: the image tag must end in a commit SHA, e.g.
`payment-service:3f2a9c1` or `ghcr.io/acme/payments:release-3f2a9c1d4e...`.
Pod -> repo link: `repos.json` (service prefix -> "owner/repo"), the
OPSBUDDY_REPOS env var (same JSON), or, failing both, an image path like
`ghcr.io/owner/repo`.
Set GITHUB_TOKEN for private repos and higher rate limits.
"""
import json
import os
import re
from pathlib import Path

import requests

API = "https://api.github.com"
SHA_TAG = re.compile(r"(?:^|[-_.])([0-9a-f]{7,40})$")


def extract_sha(image: str | None) -> str | None:
    """Return the commit SHA at the end of an image tag, or None."""
    if not image:
        return None
    ref = image.split("@")[0]
    last = ref.rsplit("/", 1)[-1]
    if ":" not in last:
        return None
    tag = last.split(":", 1)[1]
    m = SHA_TAG.search(tag)
    if not m:
        return None
    sha = m.group(1)
    # Pure-digit tags such as 20261124 are dates or build numbers, not SHAs.
    if len(sha) < 40 and not re.search(r"[a-f]", sha):
        return None
    return sha


def load_repo_map() -> dict:
    repo_map = {}
    path = Path(__file__).with_name("repos.json")
    if path.exists():
        try:
            repo_map.update(json.loads(path.read_text(encoding="utf-8-sig")))
        except (OSError, ValueError):
            pass
    env = os.environ.get("OPSBUDDY_REPOS")
    if env:
        try:
            repo_map.update(json.loads(env))
        except ValueError:
            pass
    return repo_map


def resolve_repo(pod_name: str, image: str | None) -> str | None:
    for prefix, repo in load_repo_map().items():
        if pod_name.startswith(prefix):
            return repo
    if image and image.startswith("ghcr.io/"):
        parts = image.split("@")[0].split(":")[0].split("/")
        if len(parts) >= 3:
            return f"{parts[1]}/{parts[2]}"
    return None


def has_token() -> bool:
    return bool(os.environ.get("GITHUB_TOKEN"))


def _get(path: str, params: dict | None = None):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "opsbuddy"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return requests.get(f"{API}{path}", headers=headers, params=params, timeout=15)


def _shape(c: dict) -> dict:
    commit = c.get("commit", {})
    author = commit.get("author", {}) or {}
    gh_user = c.get("author") or {}
    return {
        "sha": c.get("sha", ""),
        "short": c.get("sha", "")[:7],
        "author": author.get("name") or "Unknown",
        "login": gh_user.get("login"),
        "date": author.get("date"),
        "message": (commit.get("message") or "").splitlines()[0] if commit.get("message") else "",
        "url": c.get("html_url"),
    }


def fetch_commit_info(repo: str, sha: str) -> dict:
    """Returns {"commit": {...}, "previous": [...]} or {"error": "..."}."""
    try:
        r = _get(f"/repos/{repo}/commits/{sha}")
        if r.status_code == 404:
            hint = "" if has_token() else " If the repo is private, set GITHUB_TOKEN."
            return {"error": f"GitHub has no commit {sha[:7]} in {repo}.{hint}"}
        if r.status_code in (403, 429):
            return {"error": "GitHub rate limit reached. Set GITHUB_TOKEN or try again later."}
        if r.status_code == 401:
            return {"error": "GitHub rejected the token (401)."}
        r.raise_for_status()
        commit = _shape(r.json())
        previous = []
        lr = _get(f"/repos/{repo}/commits", {"sha": commit["sha"], "per_page": 4})
        if lr.ok:
            previous = [_shape(c) for c in lr.json()[1:4]]
        return {"commit": commit, "previous": previous}
    except requests.RequestException as e:
        return {"error": f"Could not reach GitHub: {e.__class__.__name__}"}
