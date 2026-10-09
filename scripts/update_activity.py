"""Render the public GitHub activity into two self-contained SVGs. No dependencies."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from html import escape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
USER = "GioOtto"


def fetch(url: str, *, api: bool = False) -> str:
    headers = {"User-Agent": "GioOtto-profile-activity"}
    # Only the REST API receives a token. The calendar is always read signed out.
    if api:
        headers["Accept"] = "application/vnd.github+json"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
        if token := os.environ.get("GITHUB_TOKEN"):
            headers["Authorization"] = f"Bearer {token}"
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers=headers), timeout=30) as response:
                return response.read().decode("utf-8")
        except (HTTPError, URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError("Unreachable")


class Calendar(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.dates: dict[str, date] = {}
        self.counts: dict[str, int] = {}
        self.target: str | None = None
        self.label: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "td" and attributes.get("data-date"):
            self.dates[attributes["id"]] = date.fromisoformat(attributes["data-date"])
        if tag == "tool-tip" and attributes.get("for", "").startswith("contribution-day-"):
            self.target = attributes["for"]
            self.label = []

    def handle_data(self, data: str) -> None:
        if self.target:
            self.label.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "tool-tip" and self.target:
            match = re.match(r"(No|[\d,]+) contributions? on\b", "".join(self.label).strip())
            if not match:
                raise ValueError("GitHub's contribution calendar format has changed")
            count = match[1]
            self.counts[self.target] = 0 if count == "No" else int(count.replace(",", ""))
            self.target = None


def calendar(start: date, end: date) -> dict[date, int]:
    page = fetch(f"https://github.com/users/{USER}/contributions")
    parsed = Calendar()
    parsed.feed(page)
    days = {day: parsed.counts[key] for key, day in parsed.dates.items()
            if start <= day <= end and key in parsed.counts}
    if len(days) != (end - start).days + 1:
        raise ValueError("Incomplete public contribution calendar; keeping the previous SVGs")
    return days


def search(query: str, *, page: int = 1, page_size: int = 100) -> dict:
    url = "https://api.github.com/search/issues?" + urlencode({
        "q": query, "per_page": page_size, "page": page,
    })
    result = json.loads(fetch(url, api=True))
    if result.get("incomplete_results"):
        raise ValueError("GitHub returned incomplete PR statistics")
    return result


def pull_requests(start: date, end: date) -> tuple[int, int, int]:
    query = f"author:{USER} is:pr is:public created:{start.isoformat()}..{end.isoformat()}"
    total = search(query, page_size=1)["total_count"]
    merged = search(query + " is:merged", page_size=1)["total_count"]
    opened = search(query + " is:open", page_size=1)["total_count"]
    if not 0 <= merged + opened <= total:
        raise ValueError("PR statistics changed during collection; try again")
    return total, merged, opened


def render(days: dict[date, int], prs: tuple[int, int, int], *, dark: bool) -> str:
    start, end = min(days), max(days)
    total, merged, opened = prs
    colors = ({"bg": "0d1117", "text": "e6edf3", "muted": "8b949e", "line": "21262d",
               "green": "3fb950", "wash": "122c20", "purple": "a78bfa"} if dark else
              {"bg": "ffffff", "text": "1f2328", "muted": "656d76", "line": "d8dee4",
               "green": "1a7f37", "wash": "dafbe1", "purple": "8250df"})
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="278" viewBox="0 0 800 278" role="img" aria-labelledby="title description">',
        '<title id="title">GioOtto / GitHub activity</title>',
        f'<desc id="description">{sum(days.values()):,} contributions, {total} public pull requests opened, {merged} of those merged, and {sum(n > 0 for n in days.values())} active days, from {start.isoformat()} to {end.isoformat()}. Weekly contributions are on the left; pull request status is on the right.</desc>',
        '<style>text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-variant-numeric:tabular-nums}</style>',
        f'<rect x=".5" y=".5" width="799" height="277" rx="10" fill="#{colors["bg"]}" stroke="#{colors["line"]}"/>',
    ]

    def text(x: float, y: float, value: str, *, size: int = 11, color: str = "muted",
             anchor: str = "start", mono: bool = False) -> None:
        parts.append(f'<text x="{x:g}" y="{y:g}" font-size="{size}" fill="#{colors[color]}" text-anchor="{anchor}" class="{"mono" if mono else ""}">{escape(value)}</text>')

    def line(x1: float, y1: float, x2: float, y2: float) -> None:
        parts.append(f'<line x1="{x1:g}" y1="{y1:g}" x2="{x2:g}" y2="{y2:g}" stroke="#{colors["line"]}"/>')

    text(28, 30, "GioOtto / activity", size=11, color="text", mono=True)
    text(772, 30, "LAST 12 MONTHS", anchor="end", mono=True)
    metrics = [(sum(days.values()), "Contributions"), (total, "Public PRs opened"),
               (merged, "Of those, merged"), (sum(n > 0 for n in days.values()), "Active days")]
    for index, (value, label) in enumerate(metrics):
        x = 28 + index * 192
        text(x, 77, f"{value:,}", size=29, color="text", mono=True)
        text(x, 100, label, size=12)
    line(28, 119, 772, 119)
    text(28, 145, "Contributions / week", size=12)
    text(630, 145, "PR status", size=12)
    line(604, 139, 604, 251)

    weeks: dict[date, int] = defaultdict(int)
    for day, count in sorted(days.items()):
        weeks[day - timedelta(days=day.weekday())] += count
    values = list(weeks.values())
    maximum = max(values) or 1
    x0, width, bottom, height = 28, 548, 230, 63
    step = width / len(values)
    for fraction in (0, .5, 1):
        line(x0, bottom - height * fraction, x0 + width, bottom - height * fraction)
    for index, (week, count) in enumerate(weeks.items()):
        bar_height = height * count / maximum if count else 2
        x = x0 + index * step + 1
        fill = colors["green"] if count else colors["wash"]
        label = f"Week of {week.isoformat()}: {count} contributions"
        parts.append(f'<rect x="{x:.2f}" y="{bottom - bar_height:.2f}" width="{step - 2:.2f}" height="{bar_height:.2f}" rx="1.5" fill="#{fill}"><title>{label}</title></rect>')
    text(576, 158, f"peak {maximum} / wk", anchor="end", size=10, mono=True)
    text(x0, 251, start.strftime("%b %Y"), size=10, mono=True)
    text(x0 + width, 251, end.strftime("%b %Y"), anchor="end", size=10, mono=True)

    statuses = [("Open", opened, "green"), ("Merged", merged, "purple"),
                ("Closed", total - merged - opened, "muted")]
    largest = max(opened, merged, total - merged - opened, 1)
    for index, (label, count, color) in enumerate(statuses):
        x = 630 + index * 51
        bar_height = 46 * count / largest if count else 2
        text(x + 14, 174, str(count), color="text", size=12, anchor="middle", mono=True)
        parts.append(f'<rect x="{x}" y="{230 - bar_height:g}" width="28" height="{bar_height:g}" rx="3" fill="#{colors[color]}" opacity="{1 if count else .25}"><title>{count} {label.lower()} public pull requests created in this period</title></rect>')
        text(x + 14, 251, label, size=10, anchor="middle")
    parts.append("</svg>\n")
    return "\n".join(parts)


def main() -> None:
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=364)
    days = calendar(start, end)
    prs = pull_requests(start, end)
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    for theme in ("light", "dark"):
        (assets / f"activity-{theme}.svg").write_text(
            render(days, prs, dark=theme == "dark"), encoding="utf-8")
    print(f"Updated {start}..{end}: {sum(days.values())} contributions, {prs[0]} public PRs, {prs[1]} merged")


if __name__ == "__main__":
    main()
