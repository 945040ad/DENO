import httpx
import pytest
import respx

from deno_sources.website import MAX_BYTES, SiteUnavailable, extract, fetch_site, find_site

PUBLIC = "93.184.216.34"


def resolver(table: dict[str, list[str]]):  # type: ignore[no-untyped-def]
    async def resolve(host: str) -> list[str]:
        if host not in table:
            raise OSError("NXDOMAIN")
        return table[host]

    return resolve


PAGE = """<html><head><title>Fallback</title>
<meta property="og:title" content="Tripnest - offline trip planner">
<meta name="description" content="Plan, track and journal trips without a connection.">
<script>steal()</script><style>.x{}</style></head>
<body><nav>Home Login</nav><main><h1>Your trips, offline</h1><h2>Budget tracking</h2>
<p>Keep every booking, ticket and photo in one app.</p>
<section id="pricing"><h3>Plans</h3><p>Free</p><p>Pro $4/month</p></section></main>
<footer>© 2026</footer></body></html>"""


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Check https://tripnest.app/features, it's my app", "https://tripnest.app/features"),
        ("my site tripnest.app is live", "https://tripnest.app"),
        ("http://tripnest.app", "http://tripnest.app"),
        ("repo https://github.com/a/b and site https://tripnest.app", "https://tripnest.app"),
        ("only https://github.com/a/b", None),
        ("edit main.py and config.json", None),
        ("mail me at me@tripnest.app", None),
        ("A tool that scores LinkedIn drafts", None),
    ],
)
def test_find_site(text: str, expected: str | None) -> None:
    assert find_site(text) == expected


def test_extract_keeps_product_text_and_drops_scripts_and_chrome() -> None:
    facts = extract(PAGE, "https://tripnest.app/")
    assert facts.title == "Tripnest - offline trip planner"
    assert facts.description == "Plan, track and journal trips without a connection."
    assert facts.headings[:2] == ["Your trips, offline", "Budget tracking"]
    assert "Pro $4/month" in facts.pricing
    assert "steal()" not in facts.text and "Home Login" not in facts.text and "© 2026" not in facts.text
    assert "Keep every booking" in facts.text
    assert not extract(PAGE.replace("<p>Keep", "<p>" + "Plan trips offline. " * 12 + "Keep"), "https://t/").thin


def test_javascript_only_page_is_thin() -> None:
    assert extract('<html><body><div id="root"></div></body></html>', "https://spa.app/").thin


@respx.mock
async def test_fetch_connects_to_the_checked_address_with_real_hostname() -> None:
    respx.get(f"https://{PUBLIC}/robots.txt").respond(404)
    page = respx.get(f"https://{PUBLIC}/").respond(200, text=PAGE, headers={"Content-Type": "text/html; charset=utf-8"})
    facts = await fetch_site("http://tripnest.app", resolver=resolver({"tripnest.app": [PUBLIC]}))
    req = page.calls.last.request
    assert req.headers["Host"] == "tripnest.app"
    assert req.extensions["sni_hostname"] == "tripnest.app"
    assert facts.url == "https://tripnest.app/" and facts.title.startswith("Tripnest")


@pytest.mark.parametrize(
    "addresses",
    [["127.0.0.1"], ["169.254.169.254"], ["10.0.0.5"], ["192.168.1.1"], ["::1"], [PUBLIC, "10.0.0.1"], ["0.0.0.0"]],  # noqa: S104
)
async def test_non_public_addresses_are_refused(addresses: list[str]) -> None:
    with pytest.raises(SiteUnavailable, match="isn't a public website"):
        await fetch_site("https://evil.example", resolver=resolver({"evil.example": addresses}))


@pytest.mark.parametrize(
    ("url", "phrase"),
    [
        ("https://169.254.169.254/computeMetadata/v1/", "bare IP"),
        ("https://[::1]/", "bare IP"),
        ("https://tripnest.app:8443/", "standard port"),
        ("https://user:pw@tripnest.app/", "username or password"),
        ("ftp://tripnest.app/", "only http"),
        ("https://metadata.google.internal/", "isn't a public website"),
        ("https://localhost/", "isn't a public website"),
    ],
)
async def test_dangerous_links_are_refused_before_any_request(url: str, phrase: str) -> None:
    with respx.mock(assert_all_called=False) as router:
        with pytest.raises(SiteUnavailable, match=phrase):
            await fetch_site(url, resolver=resolver({"tripnest.app": [PUBLIC]}))
        assert not router.calls


@respx.mock
async def test_redirect_into_private_network_is_refused() -> None:
    respx.get(f"https://{PUBLIC}/robots.txt").respond(404)
    respx.get(f"https://{PUBLIC}/").respond(302, headers={"Location": "https://internal.corp/admin"})
    table = {"tripnest.app": [PUBLIC], "internal.corp": ["10.1.2.3"]}
    with pytest.raises(SiteUnavailable, match="isn't a public website"):
        await fetch_site("https://tripnest.app", resolver=resolver(table))


@respx.mock
async def test_redirects_are_followed_and_rechecked() -> None:
    other = "151.101.1.1"
    respx.get(f"https://{PUBLIC}/robots.txt").respond(404)
    respx.get(f"https://{PUBLIC}/").respond(301, headers={"Location": "https://www.tripnest.app/home"})
    respx.get(f"https://{other}/robots.txt").respond(404)
    respx.get(f"https://{other}/home").respond(200, text=PAGE, headers={"Content-Type": "text/html"})
    table = {"tripnest.app": [PUBLIC], "www.tripnest.app": [other]}
    facts = await fetch_site("https://tripnest.app", resolver=resolver(table))
    assert facts.url == "https://www.tripnest.app/home"


@respx.mock
async def test_robots_disallow_is_respected() -> None:
    respx.get(f"https://{PUBLIC}/robots.txt").respond(200, text="User-agent: *\nDisallow: /")
    page = respx.get(f"https://{PUBLIC}/").respond(200, text=PAGE, headers={"Content-Type": "text/html"})
    with pytest.raises(SiteUnavailable, match="automated readers"):
        await fetch_site("https://tripnest.app", resolver=resolver({"tripnest.app": [PUBLIC]}))
    assert not page.called


@respx.mock
async def test_non_html_and_errors_are_explained() -> None:
    respx.get(f"https://{PUBLIC}/robots.txt").respond(404)
    respx.get(f"https://{PUBLIC}/file.pdf").respond(200, content=b"%PDF", headers={"Content-Type": "application/pdf"})
    respx.get(f"https://{PUBLIC}/gone").respond(404)
    respx.get(f"https://{PUBLIC}/slow").mock(side_effect=httpx.ReadTimeout("slow"))
    r = resolver({"tripnest.app": [PUBLIC]})
    with pytest.raises(SiteUnavailable, match="not HTML"):
        await fetch_site("https://tripnest.app/file.pdf", resolver=r)
    with pytest.raises(SiteUnavailable, match="404"):
        await fetch_site("https://tripnest.app/gone", resolver=r)
    with pytest.raises(SiteUnavailable, match="too long"):
        await fetch_site("https://tripnest.app/slow", resolver=r)
    with pytest.raises(SiteUnavailable, match="doesn't exist"):
        await fetch_site("https://nope.example", resolver=r)


@respx.mock
async def test_body_is_capped() -> None:
    respx.get(f"https://{PUBLIC}/robots.txt").respond(404)
    huge = "<html><body><main>" + "x" * (MAX_BYTES * 3) + "</main></body></html>"
    respx.get(f"https://{PUBLIC}/").respond(200, text=huge, headers={"Content-Type": "text/html"})
    facts = await fetch_site("https://tripnest.app", resolver=resolver({"tripnest.app": [PUBLIC]}))
    assert len(facts.text) < 7000
