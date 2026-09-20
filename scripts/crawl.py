"""Click every link on every page, signed in and signed out, and report anything
that is not a 200 or a redirect. The 404s this catches are almost always a
relative href rendered at the wrong depth."""
import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from urllib.parse import urljoin
from fastapi.testclient import TestClient
from app.main import app


def crawl(client, label):
    seen, queue, bad, pages = set(), [("/", "(start)")], [], 0
    # Every stock page carries the same four ?span= links, so following all of
    # them is 312 pages turning into 1,248 that differ in nothing. Check a
    # sample of the query variants and every distinct path.
    QUERY_BUDGET = 40
    queries = 0
    while queue:
        url, came_from = queue.pop(0)
        if url in seen or url.startswith("/signout"):
            continue
        if "?" in url:
            if queries >= QUERY_BUDGET:
                continue
            queries += 1
        seen.add(url)
        r = client.get(url)
        # Resolve against where we landed: a redirect moves the base, and
        # resolving "stock/x" against /auth/dev invents 200 broken links.
        url = r.url.path
        seen.add(url)
        if r.status_code >= 400:
            bad.append((url, r.status_code, came_from))
            continue
        pages += 1
        if "html" not in r.headers.get("content-type", ""):
            continue
        for href in re.findall(r'href="([^"]*)"', r.text):
            if href.startswith(("http", "mailto:", "#")) or not href:
                continue
            queue.append((urljoin(url, href), url))
        for action in re.findall(r'<form[^>]*action="([^"]*)"', r.text):
            target = urljoin(url, action)
            if target not in seen:
                seen.add(target)
                post = client.post(target, data={"csrf": "x"})
                if post.status_code >= 500:
                    bad.append((f"POST {target}", post.status_code, url))
    print(f"{label}: {pages} pages ok, {len(bad)} broken")
    for url, code, src in bad:
        print(f"   {code}  {url}   (linked from {src})")
    return bad


out = TestClient(app, follow_redirects=True)
bad = crawl(out, "signed out")
inn = TestClient(app, follow_redirects=True)
inn.get("/auth/dev")
bad += crawl(inn, "signed in ")
raise SystemExit(1 if bad else 0)
