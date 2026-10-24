"""Reference screens next to the app at 390 px, for the redesign (docs/design.md).

python scripts/screenshots.py design-check design-check/1-grundlage

Seeds data close to the examples in docs/design/screens/ (a WG with six weekly rounds,
seen by Jonas), renders the matching pages, photographs both sides with headless Chrome
and writes an index.html that shows every pair side by side.
"""

import base64
import hashlib
import html as html_lib
import json
import random
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app import create_app
from app.clock import FrozenClock
from app.config import TestConfig
from app.extensions import db
from app.services import invitations, settings
from app.services import voting as voting_service
from tests.conftest import IsolatedClient
from tests.factories import add_member, make_group, make_user, tick, vote

ROOT = Path(__file__).resolve().parent.parent
SCREENS = ROOT / "docs" / "design" / "screens"
WIDTH = 390
ECHARTS_URL = "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"
ECHARTS_SRI = "Mx5lkUEQPM1pOJCwFtUICyX45KNojXbkWdYhkKUKsbv391mavbfoAmONbzkgYPzR"
CACHE = Path.home() / ".cache" / "spassvogel"
RANGES = ("1w", "4w", "3m", "1y", "all")


@dataclass
class Page:
    name: str
    reference: str | None  # file in docs/design/screens, None for pages without a design
    html: str
    height: int
    graph: dict[str, Any] = field(default_factory=dict)  # range → graph.json


# Who gets how many ups, so the order resembles the reference.
STRENGTH = {"Felix": 0.7, "Lena": 0.64, "Jonas": 0.56, "Sophie": 0.52, "Ali": 0.45, "Tim": 0.36}

# Sunday noon in the weekly window (Berlin), six rounds ending Mon 19.10.2026 (KW 43).
FIRST_SUNDAY = datetime(2026, 9, 13, 10, 0, tzinfo=UTC)


def render() -> list[Page]:
    clock = FrozenClock(datetime(2026, 9, 12, 10, 0, tzinfo=UTC))
    app = create_app(TestConfig, clock=clock)
    app.test_client_class = IsolatedClient
    pages: list[Page] = []
    rng = random.Random(43)
    with app.app_context():
        db.create_all()
        users = {name: make_user(f"{name.lower()}@example.org", name) for name in STRENGTH}
        jonas = users["Jonas"]
        group = make_group(jonas, "WG Hinterhof")
        group.is_anonymous = False
        db.session.commit()
        for user in users.values():
            if user is not jonas:
                add_member(group, user)
        invitations.invite(group, jonas, "paul.w@example.org")  # expires before the shots
        for week in range(6):
            clock.set(FIRST_SUNDAY + timedelta(days=7 * week))
            tick()
            _random_votes(group, users, rng)
            clock.set(FIRST_SUNDAY + timedelta(days=7 * week + 1, hours=2))
            tick()

        # Sunday 25.10., 20:47 h before the window closes: Jonas has rated three of five.
        clock.set(datetime(2026, 10, 25, 15, 13, tzinfo=UTC))
        tick()
        for name, choice in (("Felix", "down"), ("Lena", "up"), ("Ali", "up")):
            vote(group, jonas, users[name], choice)
        reason = "Pfandautomat-Witz zum dritten Mal"
        voting_service.set_reason(group, jonas, users["Felix"].id, reason)
        for voter in ("Felix", "Lena", "Tim"):
            vote(group, users[voter], jonas, "up")
        client = _client(app, jonas)
        pages.append(_page(client, "ranking", "ranking.html", f"/g/{group.id}/", 1000, graph=True))
        pages.append(_page(client, "voting", "voting.html", f"/g/{group.id}/vote", 900))

        # Wednesday 28.10., 3 days 14:22 h before the next window.
        clock.set(datetime(2026, 10, 26, 12, 0, tzinfo=UTC))
        tick()
        clock.set(datetime(2026, 10, 28, 8, 38, tzinfo=UTC))
        invitations.invite(group, jonas, "mara.k@example.org")
        closed = _page(
            client, "voting-geschlossen", "voting-geschlossen.html", f"/g/{group.id}/vote", 900
        )
        pages.append(closed)
        settings.change(group, jonas, replace(settings.upcoming(group), is_anonymous=True))
        pages.append(
            _page(client, "einstellungen", "einstellungen.html", f"/g/{group.id}/settings", 1700)
        )

        stammtisch = make_group(jonas, "Stammtisch Dienstag")
        for name in ("Mara", "Paul", "Kim"):
            add_member(stammtisch, make_user(f"{name.lower()}@example.org", name))
        pages.append(
            _page(
                client,
                "ranking-neue-gruppe",
                "ranking-neue-gruppe.html",
                f"/g/{stammtisch.id}/",
                1000,
                graph=True,
            )
        )
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
    return pages


def _random_votes(group: Any, users: dict[str, Any], rng: random.Random) -> None:
    for voter_name, voter in users.items():
        for target_name, target in users.items():
            if voter_name != target_name and rng.random() < 0.5:
                choice = "up" if rng.random() < STRENGTH[target_name] else "down"
                vote(group, voter, target, choice)


def _client(app: Any, user: Any) -> Any:
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = user.get_id()
    return client


def _page(
    client: Any, name: str, reference: str | None, url: str, height: int, graph: bool = False
) -> Page:
    page = Page(name, reference, client.get(url).get_data(as_text=True), height)
    if graph:
        base = url.rstrip("/")
        page.graph = {r: client.get(f"{base}/graph.json?range={r}").get_json() for r in RANGES}
    return page


def echarts() -> Path:
    """ECharts from the CDN, checked against the same SRI hash as in the templates."""
    path = CACHE / "echarts-5.5.1.min.js"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(ECHARTS_URL, timeout=30) as response:
            data = response.read()
        digest = base64.b64encode(hashlib.sha384(data).digest()).decode()
        if digest != ECHARTS_SRI:
            raise SystemExit("ECharts vom CDN passt nicht zum SRI-Hash.")
        path.write_bytes(data)
    return path


def localize_with_graph(page: Page, localize: Any) -> str:
    """Like screenshots.localize, but keeps the graph: ECharts from the cache, graph.json
    answered by a stub. Only for the screenshot copy, never served by the app."""
    html = page.html.replace(ECHARTS_URL, echarts().as_uri())
    html = localize(html)
    if page.graph:
        data = json.dumps(page.graph)
        stub = (
            "<script>window.fetch = async (url) => ({ ok: true, json: async () => "
            f"({data})[new URL(url, location.href).searchParams.get('range') || '4w'] }});</script>"
        )
        html = html.replace("</head>", f"{stub}</head>", 1)
    return html


def write_index(out: Path, pages: list[Page]) -> Path:
    rows = []
    for page in pages:
        reference = (
            f'<img src="{page.name}/referenz.png" alt="Referenz">'
            if page.reference
            else "<p>kein Entwurf</p>"
        )
        rows.append(
            f"<section><h2>{html_lib.escape(page.name)}</h2><div class='pair'>"
            f"<figure><figcaption>Referenz</figcaption>{reference}</figure>"
            "<figure><figcaption>Ist</figcaption>"
            f"<img src='{page.name}/ist.png' alt='Ist'></figure>"
            "</div></section>"
        )
    index = out / "index.html"
    index.write_text(
        "<!doctype html><meta charset='utf-8'><title>Design-Check</title>"
        "<style>body{font-family:system-ui;margin:24px;background:#ddd}"
        ".pair{display:flex;gap:24px;align-items:flex-start}"
        "figure{margin:0}img{width:390px;border:1px solid #999;background:#fff}"
        "h2{margin:32px 0 8px}</style>"
        f"<h1>{html_lib.escape(out.name)}</h1>{''.join(rows)}"
    )
    return index


def crop(png: Path, height: int) -> None:
    """Chrome shoots at least 600 px wide; keep the 390 px of the page (macOS sips)."""
    if shutil.which("sips"):
        subprocess.run(
            ["sips", "-c", str(height), str(WIDTH), "--cropOffset", "0", "0", str(png)],
            check=True,
            capture_output=True,
        )


def run(out: Path, chrome: str, shoot: Any, localize: Any, only: set[str] | None) -> Path:
    pages = [p for p in render() if not only or p.name in only]
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    for page in pages:
        folder = out / page.name
        folder.mkdir(exist_ok=True)
        source = folder / "ist.html"
        source.write_text(localize_with_graph(page, localize))
        shoot(chrome, source, folder / "ist.png", WIDTH, page.height)
        crop(folder / "ist.png", page.height)
        if page.reference:
            reference = folder / "referenz.html"
            reference.write_text((SCREENS / page.reference).read_text())
            shoot(chrome, reference, folder / "referenz.png", WIDTH, page.height)
            crop(folder / "referenz.png", page.height)
    return write_index(out, pages)
