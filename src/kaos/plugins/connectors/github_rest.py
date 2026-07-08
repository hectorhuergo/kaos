"""GitHub REST activity source: reads a repository's recent commits and issues.

Uses the GitHub REST API via httpx (no extra dependency). It yields normalized
`GitHubItem`s in chronological order so the Resume Agent can summarize the recent
development activity of a repo. Authentication uses a GitHub token (the same
`KAOS_GITHUB_TOKEN` used for GitHub Models works if it has repo read access).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx

from kaos.plugins.connectors.github_connector import (
    COMMIT,
    ISSUE,
    PULL_REQUEST,
    GitHubItem,
)

GITHUB_API = "https://api.github.com"


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0] if text.strip() else ""


class GitHubRestSource:
    """A bounded `GitHubActivitySource` over a repository's recent activity."""

    def __init__(
        self,
        token: str,
        repo: str,
        *,
        limit: int = 30,
        include_issues: bool = True,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._token = token
        self._repo = repo  # "owner/name"
        self._limit = limit
        self._include_issues = include_issues
        self._timeout = timeout
        self._client = client
        self._owns_client = client is None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _fetch_commits(self, client: httpx.AsyncClient) -> list[GitHubItem]:
        resp = await client.get(
            f"{GITHUB_API}/repos/{self._repo}/commits",
            params={"per_page": self._limit},
            headers=self._headers(),
        )
        resp.raise_for_status()
        items: list[GitHubItem] = []
        for raw in resp.json():
            commit = raw.get("commit", {})
            author_meta = commit.get("author", {})
            login = (raw.get("author") or {}).get("login")
            items.append(
                GitHubItem(
                    item_id=str(raw.get("sha", "")),
                    kind=COMMIT,
                    author=str(login or author_meta.get("name", "unknown")),
                    text=_first_line(str(commit.get("message", ""))),
                    url=str(raw.get("html_url", "")),
                    timestamp=author_meta.get("date"),
                )
            )
        return items

    async def _fetch_issues(self, client: httpx.AsyncClient) -> list[GitHubItem]:
        # The issues endpoint returns both issues and pull requests.
        resp = await client.get(
            f"{GITHUB_API}/repos/{self._repo}/issues",
            params={"state": "all", "per_page": self._limit, "sort": "updated"},
            headers=self._headers(),
        )
        resp.raise_for_status()
        items: list[GitHubItem] = []
        for raw in resp.json():
            kind = PULL_REQUEST if "pull_request" in raw else ISSUE
            user = (raw.get("user") or {}).get("login", "unknown")
            number = raw.get("number", "")
            title = raw.get("title", "")
            items.append(
                GitHubItem(
                    item_id=f"{kind}-{number}",
                    kind=kind,
                    author=str(user),
                    text=f"#{number} {title}",
                    url=str(raw.get("html_url", "")),
                    timestamp=raw.get("created_at"),
                )
            )
        return items

    async def items(self) -> AsyncIterator[GitHubItem]:
        client = self._get_client()
        collected = await self._fetch_commits(client)
        if self._include_issues:
            collected += await self._fetch_issues(client)
        # Chronological order (oldest first); items without a timestamp sort last.
        collected.sort(key=lambda i: i.timestamp or "")
        for item in collected:
            yield item

    async def close(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None


