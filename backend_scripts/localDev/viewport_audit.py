"""Responsive layout audit for the rendered static site.

Loads a sample of every page type at phone, tablet, laptop and wide viewports in Chromium,
Firefox and WebKit (WebKit approximates iOS Safari), checks each layout for horizontal overflow,
silently clipped content, over-long text lines and small touch targets, and writes full-page
screenshots plus a report. Exits 1 on any error-level finding.

Run against a served render (see README.md, "Viewport audit"):

    python backend_scripts/localDev/viewport_audit.py
    python backend_scripts/localDev/viewport_audit.py --engines chromium --widths 320,390,2560
"""

import argparse
import asyncio
import json
import sys
import urllib.parse
from pathlib import Path

from playwright.async_api import async_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]

# (name, width, height, phone). Phone viewports get a touch, mobile-UA context.
VIEWPORTS = [
    ("phone-320", 320, 568, True),
    ("phone-360", 360, 800, True),
    ("phone-375", 375, 667, True),
    ("phone-390", 390, 844, True),
    ("phone-412", 412, 915, True),
    ("phone-landscape", 844, 390, True),
    ("tablet-768", 768, 1024, True),
    ("tablet-820", 820, 1180, True),
    ("tablet-1024", 1024, 768, False),
    ("laptop-1280", 1280, 800, False),
    ("laptop-1366", 1366, 768, False),
    ("laptop-1440", 1440, 900, False),
    ("laptop-1536", 1536, 864, False),
    ("wide-1920", 1920, 1080, False),
    ("wide-2560", 2560, 1440, False),
    ("wide-3440", 3440, 1440, False),
]

# Declining every Klaro service up front keeps the consent banner off the screenshots.
KLARO_SERVICES = ["simple-analytics", "keystoneGuru", "twitch", "youtube", "wowhead"]

# Containers that clip on purpose (marquee, truncated labels, offcanvas rails).
CLIP_ALLOW = [
    ".trends-bar", ".text-truncate", "#sidenav-main", "#sidenav-right", ".fixed-plugin",
    ".bootstrap-select", ".dataTables_scrollHead", ".dt-scroll-head", "canvas",
]

PROBE_JS = """
({isPhone, wide, clipAllow}) => {
  const doc = document.documentElement;
  const W = doc.clientWidth;
  const label = el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
    [...el.classList].slice(0, 3).map(c => '.' + c).join('');
  const visible = el => {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== 'hidden' && cs.display !== 'none';
  };
  const inFixedOrScroll = el => {
    for (let p = el; p && p !== document.body; p = p.parentElement) {
      const cs = getComputedStyle(p);
      if (cs.position === 'fixed') return true;
      if (p !== el && ['auto', 'scroll', 'hidden', 'clip'].includes(cs.overflowX)) return true;
    }
    return false;
  };
  const allowed = el => clipAllow.some(sel => el.closest(sel));
  const out = {overflow: doc.scrollWidth - W, offscreen: [], clipped: [], prose: [], targets: []};

  // Outermost elements that stick out past the right edge without a scroll box to hold them.
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.right <= W + 1 || !visible(el) || inFixedOrScroll(el)) continue;
    const parent = el.parentElement;
    if (parent && parent !== document.body && parent.getBoundingClientRect().right > W + 1) continue;
    out.offscreen.push(`${label(el)} right=${Math.round(r.right)}`);
  }

  // Boxes that cut content off sideways with no way to scroll to it.
  for (const el of document.querySelectorAll('main *, #page-top-chrome *')) {
    const cs = getComputedStyle(el);
    if (!['hidden', 'clip'].includes(cs.overflowX) || cs.textOverflow === 'ellipsis') continue;
    if (el.clientWidth <= 2 || el.scrollWidth <= el.clientWidth + 2 || !visible(el) || allowed(el)) continue;
    out.clipped.push(`${label(el)} ${el.clientWidth}/${el.scrollWidth}`);
  }

  if (wide) {
    for (const p of document.querySelectorAll('main p')) {
      if (!visible(p) || p.textContent.trim().length < 120) continue;
      const probe = document.createElement('span');
      probe.textContent = '0';
      probe.style.cssText = 'position:absolute;visibility:hidden';
      p.appendChild(probe);
      const ch = probe.getBoundingClientRect().width || 8;
      probe.remove();
      const chars = Math.round(p.getBoundingClientRect().width / ch);
      if (chars > 80) out.prose.push(`${label(p)} ~${chars}ch`);
    }
  }

  if (isPhone) {
    const sel = 'a[href], button, input:not([type=hidden]), select, [role=button], [role=tab]';
    for (const el of document.querySelectorAll(sel)) {
      if (!visible(el) || el.closest('p, li > p, td') || allowed(el)) continue;
      const r = el.getBoundingClientRect();
      if (r.right < 0 || r.left > W) continue;
      if (r.width < 24 || r.height < 24) {
        out.targets.push(`${label(el)} ${Math.round(r.width)}x${Math.round(r.height)}`);
      }
    }
  }

  for (const k of ['offscreen', 'clipped', 'prose', 'targets']) {
    out[k + 'Count'] = out[k].length;
    out[k] = [...new Set(out[k])].slice(0, 8);
  }
  return out;
}
"""


def default_pages():
    """One rendered sample per page type, so every template is exercised."""
    pages = ["/index.html", "/404.html"]
    pages += sorted(f"/pages/{p.name}" for p in (REPO_ROOT / "pages").glob("*.html"))
    for role_dir in sorted((REPO_ROOT / "classes").glob("*")):
        specs = sorted(role_dir.glob("*.html"))
        if specs:
            pages.append(f"/classes/{role_dir.name}/{specs[0].name}")
    for folder in ["dungeons", "items", "consumables", "streamers"]:
        first = sorted((REPO_ROOT / folder).glob("*.html"))
        if not first:
            raise SystemExit(f"No rendered pages in {folder}/. Render them first (see README.md).")
        pages.append(f"/{folder}/{first[0].name}")
    return pages


async def audit_page(context, base_url, path, vp, out_dir, engine, screenshots):
    name, width, height, is_phone = vp
    page = await context.new_page()
    console_errors = []
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: console_errors.append(str(e)))
    try:
        await page.set_viewport_size({"width": width, "height": height})
        await page.goto(base_url + path, wait_until="load", timeout=45000)
        await page.wait_for_timeout(1200)
        result = await page.evaluate(PROBE_JS, {
            "isPhone": is_phone, "wide": width >= 1920, "clipAllow": CLIP_ALLOW,
        })
        if screenshots:
            shot = out_dir / "shots" / engine / name / (path.strip("/").replace("/", "__") + ".jpg")
            shot.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(shot), full_page=True, type="jpeg", quality=60)
    except Exception as exc:  # a page that fails to load is itself a finding
        result = {"overflow": 0, "offscreen": [], "clipped": [], "prose": [], "targets": [],
                  "offscreenCount": 0, "clippedCount": 0, "proseCount": 0, "targetsCount": 0,
                  "loadError": str(exc).splitlines()[0]}
    finally:
        await page.close()
    result["consoleErrors"] = console_errors[:5]
    result.update(engine=engine, viewport=name, page=path)
    return result


def is_error(r):
    return bool(r.get("loadError") or r["overflow"] > 0 or r["offscreenCount"]
                or r["clippedCount"] or r["proseCount"])


async def run(args):
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    widths = {int(w) for w in args.widths.split(",")} if args.widths else None
    viewports = [v for v in VIEWPORTS if widths is None or v[1] in widths]
    # Leading slash optional: Git Bash rewrites a leading "/" argument into a Windows path.
    pages = ["/" + p.strip().lstrip("/") for p in args.pages.split(",")] if args.pages else default_pages()
    consent = urllib.parse.quote(json.dumps({s: False for s in KLARO_SERVICES}))
    results = []

    async with async_playwright() as pw:
        for engine in args.engines.split(","):
            browser = await getattr(pw, engine).launch()
            for is_phone in (True, False):
                group = [v for v in viewports if v[3] == is_phone]
                if not group:
                    continue
                opts = {"has_touch": is_phone}
                if is_phone and engine != "firefox":  # Firefox has no is_mobile emulation
                    opts["is_mobile"] = True
                context = await browser.new_context(**opts)
                await context.add_cookies([{"name": "klaro", "value": consent, "url": args.base_url}])
                sem = asyncio.Semaphore(args.concurrency)

                async def one(path, vp):
                    async with sem:
                        return await audit_page(context, args.base_url, path, vp, out_dir,
                                                engine, not args.no_screenshots)

                batch = await asyncio.gather(*(one(p, v) for p in pages for v in group))
                results.extend(batch)
                await context.close()
                print(f"{engine} {'phone/tablet' if is_phone else 'desktop'}: "
                      f"{sum(is_error(r) for r in batch)} of {len(batch)} with errors")
            await browser.close()

    (out_dir / "results.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    write_report(results, out_dir / "report.md")
    errors = [r for r in results if is_error(r)]
    print(f"\n{len(errors)} of {len(results)} checks with errors. Report: {out_dir / 'report.md'}")
    return 1 if errors else 0


def write_report(results, path):
    lines = ["# Viewport audit", "",
             "| page | engine | viewport | overflow px | offscreen | clipped | prose | small targets |",
             "|---|---|---|---|---|---|---|---|"]
    flagged = [r for r in results if is_error(r) or r["targetsCount"] or r["consoleErrors"]]
    for r in sorted(flagged, key=lambda r: (r["page"], r["engine"], r["viewport"])):
        lines.append(f"| {r['page']} | {r['engine']} | {r['viewport']} | {r['overflow']} | "
                     f"{r['offscreenCount']} | {r['clippedCount']} | {r['proseCount']} | "
                     f"{r['targetsCount']} |")
    lines += ["", "## Details", ""]
    for r in sorted(flagged, key=lambda r: (r["page"], r["engine"], r["viewport"])):
        lines.append(f"### {r['page']} · {r['engine']} · {r['viewport']}")
        if r.get("loadError"):
            lines.append(f"- load error: {r['loadError']}")
        for key in ["offscreen", "clipped", "prose", "targets", "consoleErrors"]:
            for item in r.get(key, []):
                lines.append(f"- {key}: `{item}`")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://127.0.0.1:8099")
    parser.add_argument("--engines", default="chromium,firefox,webkit")
    parser.add_argument("--widths", help="comma-separated viewport widths to keep, e.g. 320,390,1920")
    parser.add_argument("--pages", help="comma-separated site paths such as pages/comps.html; default one per page type")
    parser.add_argument("--out", default=str(REPO_ROOT / "tmp" / "viewport_audit"))
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--no-screenshots", action="store_true")
    sys.exit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
