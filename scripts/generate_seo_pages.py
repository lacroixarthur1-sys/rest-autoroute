#!/usr/bin/env python3
"""Generate static, indexable per-route landing pages from the ROUTES data
embedded in index.html, plus a hub page, sitemap.xml and robots.txt.

Reuses the main app's design system (colors, cards, icons) so these pages
read as the same product, not a separate SEO bolt-on.

Run from anywhere: python3 scripts/generate_seo_pages.py
"""
import json
import re
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = ROOT / "index.html"
DOMAIN = "https://restautoroute.fr"

CUISINE = {
    "burger": ("Burger", "i-burger"),
    "bakery": ("Boulangerie", "i-bakery"),
    "pizza": ("Pizza", "i-pizza"),
    "coffee": ("Café", "i-coffee"),
    "self": ("Self-service", "i-self"),
    "veggie": ("Bio / Veggie", "i-veggie"),
}
SERVICES = {
    "fuel": ("Carburant", "i-fuel"),
    "wc": ("Toilettes", "i-wc"),
    "shop": ("Boutique", "i-shop"),
    "playground": ("Aire de jeux", "i-play"),
    "ev": ("Borne électrique", "i-ev"),
}


def load_routes():
    html = INDEX_HTML.read_text(encoding="utf-8")
    start = html.index("var ROUTES = ") + len("var ROUTES = ")
    end = html.index("\n  var ", start)
    snippet = html[start:end].rstrip().rstrip(";")
    return json.loads(snippet)


def fmt_pk(pk):
    s = f"{pk:.1f}"
    if s.endswith(".0"):
        s = s[:-2]
    return s.replace(".", ",")


def maps_link(name, route_id):
    q = urllib.parse.quote(f"{name} aire autoroute {route_id}")
    return f"https://www.google.com/maps/search/?api=1&query={q}"


def cuisine_counts(route):
    counts = {}
    for aire in route["aires"]:
        for r in aire["restaurants"]:
            t = r.get("t")
            counts[t] = counts.get(t, 0) + 1
    return counts


def render_card(aire, route, depth):
    icon_root = "../" * depth
    r_chips = "".join(
        f'<span class="r-chip"><span class="icon-badge"><svg><use href="#{CUISINE.get(r["t"], ("", "i-self"))[1]}"/></svg></span>{r["n"]}</span>'
        for r in aire["restaurants"]
    )
    svc_items = "".join(
        f'<span class="service"><svg><use href="#{SERVICES[s][1]}"/></svg>{SERVICES[s][0]}</span>'
        for s in aire.get("services", [])
        if s in SERVICES
    )
    return f"""
      <div class="card">
        <div class="card-head">
          <div>
            <p class="aire-name">{aire["name"]}</p>
            <p class="aire-route">PK {fmt_pk(aire["pk"])} · {route["id"]}</p>
          </div>
        </div>
        <div class="restaurants">{r_chips}</div>
        <div class="services">
          {svc_items}
          <a class="service maps-link" href="{maps_link(aire["name"], route["id"])}" target="_blank" rel="noopener">Avis Google Maps ↗</a>
        </div>
      </div>"""


def render_route_page(route, all_routes):
    slug = route["id"].lower()
    forward_aires = sorted([a for a in route["aires"] if a.get("direction") == "forward"], key=lambda a: a["pk"])
    reverse_aires = sorted([a for a in route["aires"] if a.get("direction") == "reverse"], key=lambda a: a["pk"])
    n_aires = len(route["aires"])
    n_restos = sum(len(a["restaurants"]) for a in route["aires"])
    counts = cuisine_counts(route)
    cuisine_chips = "".join(
        f'<span class="chip"><svg><use href="#{CUISINE.get(t, ("", "i-self"))[1]}"/></svg>{CUISINE.get(t, (t, ""))[0]} · {c}</span>'
        for t, c in sorted(counts.items(), key=lambda x: -x[1])
    )

    title = f"Restaurant Autoroute {route['id']} : tous les restos des aires ({route['from']} → {route['to']}) | Rest'Autoroute"
    description = (
        f"Liste complète des {n_restos} restaurants sur les {n_aires} aires de l'autoroute "
        f"{route['id']} entre {route['from']} et {route['to']} : self-service, burger, pizza, "
        f"boulangerie... Trouvez où manger avant de manquer la sortie."
    )

    other_routes_chips = "".join(
        f'<a class="chip" href="../{r["id"].lower()}/">{r["id"]}</a>'
        for r in sorted(all_routes, key=lambda r: r["id"])
        if r["id"] != route["id"]
    )

    ld_json = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Rest'Autoroute", "item": f"{DOMAIN}/"},
            {"@type": "ListItem", "position": 2, "name": "Autoroutes", "item": f"{DOMAIN}/aires/"},
            {"@type": "ListItem", "position": 3, "name": route["id"], "item": f"{DOMAIN}/aires/{slug}/"},
        ],
    }

    def section(sens, aires):
        if not aires:
            return ""
        cards = "".join(render_card(a, route, depth=2) for a in aires)
        return f"""
      <div class="results-meta">
        <h2>Sens {sens}</h2>
        <h2 class="dim">{len(aires)} aires</h2>
      </div>
      <div class="grid">{cards}
      </div>"""

    forward_section = section(f"{route['from']} → {route['to']}", forward_aires)
    reverse_section = section(f"{route['to']} → {route['from']}", reverse_aires)

    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{description}">
<link rel="canonical" href="{DOMAIN}/aires/{slug}/">
<meta property="og:type" content="website">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:url" content="{DOMAIN}/aires/{slug}/">
<link rel="icon" href="../../icons/favicon-32.png" sizes="32x32">
<script async src="https://www.googletagmanager.com/gtag/js?id=G-HBTCYGW0FW"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', 'G-HBTCYGW0FW');
</script>
<script type="application/ld+json">{json.dumps(ld_json, ensure_ascii=False)}</script>
<style>
{PAGE_CSS}
</style>
</head>
<body>
{SVG_DEFS}

<div class="hero">
  <div class="brand">
    <a href="../../" style="text-decoration:none;"><div class="brand-mark"><svg viewBox="0 0 24 24"><use href="#i-road"/></svg></div></a>
    <div>
      <h1>Rest'<span>Autoroute</span></h1>
      <p class="tagline">Restaurants sur les aires de l'{route['id']}</p>
    </div>
  </div>
  <div class="theme-note"><a href="../">← Toutes les autoroutes</a></div>
</div>

<div class="page">

  <div class="console route-sign">
    <div class="route-sign-row">
      <div class="route-badge">{route['id']}</div>
      <div class="route-sign-info">
        <div class="route-sign-cities">{route['from']} → {route['to']}</div>
        <div class="route-sign-stats">{n_restos} restaurants · {n_aires} aires</div>
      </div>
    </div>
    <div class="cta-row">
      <a class="locate-cta" href="../../?locate=1">
        <svg viewBox="0 0 24 24"><use href="#i-locate"/></svg>
        Me localiser — voir les aires les plus proches
      </a>
      <a class="cta-link" href="../../?route={route['id']}">
        <svg viewBox="0 0 24 24"><use href="#i-road"/></svg>
        Ouvrir le simulateur {route['id']} en manuel
      </a>
    </div>
  </div>

  <div class="filters">
    <span class="filters-label">Types de restaurants sur l'{route['id']} :</span>
    {cuisine_chips}
  </div>
  {forward_section}
  {reverse_section}

  <div class="filters" style="margin-top:36px;">
    <span class="filters-label">Autres autoroutes :</span>
    {other_routes_chips}
  </div>

  <footer class="legal">
    Rest'Autoroute — les restaurants et aires listés ici proviennent d'OpenStreetMap et peuvent avoir changé depuis la collecte. Vérifiez sur place. <a href="../../">Retour à l'accueil</a>.
  </footer>
</div>
</body>
</html>
"""


def render_hub_page(all_routes):
    tiles = "".join(
        f"""<a class="card hub-tile" href="{r['id'].lower()}/">
          <div class="card-head">
            <div>
              <p class="aire-name">{r['id']}</p>
              <p class="aire-route">{r['from']} → {r['to']}</p>
            </div>
          </div>
          <div class="stat-row">
            <div class="stat"><span class="stat-num">{len(r['aires'])}</span><span class="stat-num-label">AIRES</span></div>
            <div class="stat"><span class="stat-num">{sum(len(a['restaurants']) for a in r['aires'])}</span><span class="stat-num-label">RESTOS</span></div>
          </div>
        </a>"""
        for r in sorted(all_routes, key=lambda r: r["id"])
    )
    title = "Restaurant Autoroute : toutes les autoroutes couvertes | Rest'Autoroute"
    description = "Trouvez les restaurants sur les aires de toutes les autoroutes françaises couvertes par Rest'Autoroute : A6, A7, A10, A71..."
    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{description}">
<link rel="canonical" href="{DOMAIN}/aires/">
<meta property="og:type" content="website">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:url" content="{DOMAIN}/aires/">
<link rel="icon" href="../icons/favicon-32.png" sizes="32x32">
<script async src="https://www.googletagmanager.com/gtag/js?id=G-HBTCYGW0FW"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', 'G-HBTCYGW0FW');
</script>
<style>
{PAGE_CSS}
{HUB_CSS}
</style>
</head>
<body>
{SVG_DEFS}
<div class="hero">
  <div class="brand">
    <a href="../" style="text-decoration:none;"><div class="brand-mark"><svg viewBox="0 0 24 24"><use href="#i-road"/></svg></div></a>
    <div>
      <h1>Rest'<span>Autoroute</span></h1>
      <p class="tagline">Choisissez votre autoroute pour voir les restaurants de ses aires.</p>
    </div>
  </div>
  <div class="theme-note"><a href="../">← Accueil</a></div>
</div>
<div class="page">
  <div class="console route-sign">
    <div class="cta-row">
      <a class="locate-cta" href="../?locate=1">
        <svg viewBox="0 0 24 24"><use href="#i-locate"/></svg>
        Me localiser — trouver mon autoroute automatiquement
      </a>
      <a class="cta-link" href="../">
        <svg viewBox="0 0 24 24"><use href="#i-road"/></svg>
        Ouvrir le simulateur en manuel
      </a>
    </div>
  </div>
  <div class="hub-grid">{tiles}</div>
  <footer class="legal"><a href="../">← Retour à Rest'Autoroute</a></footer>
</div>
</body>
</html>
"""


HUB_CSS = """
.hub-tile { text-decoration: none; color: var(--text); cursor: pointer; transition: transform 0.15s ease; }
.hub-tile:hover { transform: translateY(-2px); }
.hub-tile .aire-name { font-size: 22px; }
.hub-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 16px; }
"""

SVG_DEFS = """<svg style="position:absolute; width:0; height:0; overflow:hidden;" aria-hidden="true">
  <defs>
    <symbol id="i-road" viewBox="0 0 24 24"><path d="M4 20 L9 4 M20 20 L15 4" stroke-width="2" stroke-linecap="round"/><path d="M12 6 L12 9 M12 12.5 L12 15.5" stroke-width="2" stroke-linecap="round"/></symbol>
    <symbol id="i-burger" viewBox="0 0 24 24"><path d="M4 9 h16 M4 12 h16 M4 15 h16" stroke-width="2.2" stroke-linecap="round"/></symbol>
    <symbol id="i-bakery" viewBox="0 0 24 24"><path d="M4 15c0-5 4-9 9-9-1 3-1 6 1 9-3 2-7 2-10 0z" stroke-width="2" stroke-linejoin="round"/></symbol>
    <symbol id="i-pizza" viewBox="0 0 24 24"><path d="M12 4 L21 19 H3 Z" stroke-width="2" stroke-linejoin="round"/><circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none"/><circle cx="10" cy="15.5" r="1.2" fill="currentColor" stroke="none"/></symbol>
    <symbol id="i-coffee" viewBox="0 0 24 24"><path d="M5 9h11v5a5 5 0 0 1-5 5H10a5 5 0 0 1-5-5V9z" stroke-width="2"/><path d="M16 10h1.5a2.5 2.5 0 0 1 0 5H16" stroke-width="2"/><path d="M8 5c0 1-1 1-1 2 M12 5c0 1-1 1-1 2" stroke-width="1.6" stroke-linecap="round"/></symbol>
    <symbol id="i-self" viewBox="0 0 24 24"><path d="M6 3v8M6 3c-1.5 0-2 1.2-2 2.5S4.5 8 6 8" stroke-width="2" stroke-linecap="round"/><path d="M6 11v10" stroke-width="2" stroke-linecap="round"/><path d="M17 3c-2 0-3 2-3 5s1 3 3 3v9" stroke-width="2" stroke-linecap="round"/></symbol>
    <symbol id="i-veggie" viewBox="0 0 24 24"><path d="M12 20c-6-1-8-7-6-13 6 0 10 3 10 8" stroke-width="2" stroke-linejoin="round"/><path d="M6 7c3 2 5 6 6 13" stroke-width="2" stroke-linecap="round"/></symbol>
    <symbol id="i-fuel" viewBox="0 0 24 24"><rect x="4" y="4" width="10" height="16" rx="1" stroke-width="2"/><path d="M6 8h6" stroke-width="2"/><path d="M14 10h2l3 3v5a1.5 1.5 0 0 1-3 0v-1a1 1 0 0 0-1-1h-1" stroke-width="2" stroke-linejoin="round"/></symbol>
    <symbol id="i-wc" viewBox="0 0 24 24"><circle cx="9" cy="5" r="2" stroke-width="2"/><path d="M9 8v6M6 10l3-2 3 2M7 14l-1 6M11 14l1 6" stroke-width="2" stroke-linecap="round"/><circle cx="18" cy="5" r="2" stroke-width="2"/><path d="M15 20l1.5-7h3L21 20M15.5 13h5" stroke-width="2" stroke-linecap="round"/></symbol>
    <symbol id="i-play" viewBox="0 0 24 24"><path d="M12 3v18M6 7l6-4 6 4M6 17l6 4 6-4M4 12h16" stroke-width="2" stroke-linecap="round"/></symbol>
    <symbol id="i-ev" viewBox="0 0 24 24"><path d="M13 2 5 13h5l-1 9 8-13h-5l1-7z" stroke-width="2" stroke-linejoin="round"/></symbol>
    <symbol id="i-shop" viewBox="0 0 24 24"><path d="M5 8h14l-1 12H6L5 8z" stroke-width="2" stroke-linejoin="round"/><path d="M9 8V6a3 3 0 0 1 6 0v2" stroke-width="2"/></symbol>
    <symbol id="i-locate" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3" stroke-width="2"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3" stroke-width="2" stroke-linecap="round"/></symbol>
    <symbol id="i-info" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" stroke-width="2"/><path d="M12 11v5M12 8v.01" stroke-width="2" stroke-linecap="round"/></symbol>
  </defs>
</svg>"""

PAGE_CSS = """
  :root {
    --ink: #12151a; --surface-1: #ffffff; --surface-2: #eef0f4; --surface-3: #e2e6ec;
    --sign-blue: #1d4e89; --sign-blue-deep: #123a68; --sign-blue-pale: #e7eef7;
    --amber: #e08a1e; --amber-deep: #a8630f; --amber-pale: #fdf1de;
    --paper: #f5f2ea; --line: #ccd1da; --text: #1b2028; --text-dim: #5b6675;
    --radius: 12px; --shadow: 0 6px 18px rgba(18,21,26,0.09);
    --font-display: 'Arial Narrow', 'Roboto Condensed', 'Helvetica Neue Condensed', sans-serif;
    --font-body: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    --font-mono: ui-monospace, SFMono-Regular, 'SF Mono', Consolas, 'Roboto Mono', monospace;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --ink: #eef1f5; --surface-1: #1a1f27; --surface-2: #20262f; --surface-3: #262d38;
      --sign-blue: #4a86c9; --sign-blue-deep: #2c5d95; --sign-blue-pale: #1c2c40;
      --amber: #f0a63f; --amber-deep: #f5b25c; --amber-pale: #35291a;
      --paper: #0f1216; --line: #333b46; --text: #eef1f5; --text-dim: #99a3b1;
      --shadow: 0 6px 20px rgba(0,0,0,0.4);
    }
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body { background: var(--paper); color: var(--text); font-family: var(--font-body); line-height: 1.45; }
  a { color: inherit; }
  h1, h2, .chip, .aire-name, .stat-num-label { font-family: var(--font-display); text-transform: uppercase; }
  svg { display: block; }

  .page { max-width: 1180px; margin: 0 auto; padding: 0 20px 64px; }
  .hero { padding: 30px 20px 22px; max-width: 1180px; margin: 0 auto; display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; flex-wrap: wrap; }
  .brand { display: flex; align-items: center; gap: 14px; }
  .brand-mark { width: 46px; height: 46px; border-radius: 8px; background: linear-gradient(155deg, var(--sign-blue), var(--sign-blue-deep)); display: flex; align-items: center; justify-content: center; box-shadow: var(--shadow); flex: none; }
  .brand-mark svg { width: 26px; height: 26px; stroke: #fff; fill: none; }
  h1 { margin: 0; font-size: 30px; font-weight: 800; letter-spacing: 0.01em; line-height: 1; text-transform: none; font-family: var(--font-body); }
  h1 span { color: var(--amber); }
  .tagline { margin: 4px 0 0; font-size: 14.5px; color: var(--text-dim); max-width: 46ch; }
  .theme-note { font-size: 13px; }
  .theme-note a { color: var(--sign-blue); text-decoration: none; font-weight: 600; }

  .console { background: linear-gradient(160deg, var(--sign-blue-deep), var(--sign-blue)); border-radius: var(--radius); padding: 20px 22px; box-shadow: var(--shadow); color: #fff; margin-bottom: 22px; }
  .route-sign-row { display: flex; align-items: center; gap: 18px; flex-wrap: wrap; margin-bottom: 16px; }
  .route-badge { font-family: var(--font-display); font-size: 34px; font-weight: 800; background: #fff; color: var(--sign-blue-deep); padding: 6px 16px; border-radius: 8px; letter-spacing: 0.02em; line-height: 1; flex: none; }
  .route-sign-cities { font-size: 14px; text-transform: uppercase; letter-spacing: 0.06em; opacity: 0.85; font-family: var(--font-display); }
  .route-sign-stats { font-size: 22px; font-weight: 800; margin-top: 2px; }
  .cta-row { display: flex; flex-wrap: wrap; align-items: center; gap: 16px; margin-top: 6px; }
  .locate-cta {
    background: linear-gradient(135deg, var(--amber), var(--amber-deep));
    color: #241703; border: 2px solid rgba(255,255,255,0.55); border-radius: 999px;
    padding: 15px 26px; font-weight: 800; font-size: 16px; font-family: var(--font-body);
    display: inline-flex; align-items: center; gap: 10px; text-decoration: none;
    box-shadow: 0 10px 26px rgba(224,138,30,0.5), 0 0 0 1px rgba(0,0,0,0.05);
    transition: transform 0.15s ease, box-shadow 0.15s ease;
  }
  .locate-cta:hover { transform: translateY(-2px); box-shadow: 0 14px 32px rgba(224,138,30,0.6), 0 0 0 1px rgba(0,0,0,0.05); }
  .locate-cta:active { transform: translateY(0); }
  .locate-cta svg { width: 20px; height: 20px; stroke: #241703; fill: none; flex: none; }
  .cta-link {
    display: inline-flex; align-items: center; gap: 8px;
    background: rgba(255,255,255,0.1); color: #fff; border: 1.5px solid rgba(255,255,255,0.5);
    border-radius: 999px; padding: 10px 18px; font-size: 13.5px; font-weight: 600;
    text-decoration: none; transition: background 0.15s ease, border-color 0.15s ease;
  }
  .cta-link:hover { background: rgba(255,255,255,0.2); border-color: rgba(255,255,255,0.75); }
  .cta-link svg { width: 15px; height: 15px; stroke: currentColor; fill: none; flex: none; }

  .filters { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 4px 0 20px; }
  .filters .filters-label { font-size: 11.5px; color: var(--text-dim); letter-spacing: 0.06em; margin-right: 4px; text-transform: uppercase; }
  .chip { display: inline-flex; align-items: center; gap: 6px; padding: 7px 12px; border-radius: 999px; border: 1px solid var(--line); background: var(--surface-1); color: var(--text-dim); font-size: 12px; letter-spacing: 0.03em; text-decoration: none; }
  .chip svg { width: 14px; height: 14px; stroke: currentColor; fill: none; }

  .results-meta { display: flex; justify-content: space-between; align-items: baseline; margin: 28px 0 12px; flex-wrap: wrap; gap: 8px; }
  .results-meta h2 { font-size: 15px; margin: 0; letter-spacing: 0.04em; color: var(--sign-blue); }
  .results-meta h2.dim { color: var(--text-dim); font-weight: 500; text-transform: none; font-family: var(--font-body); font-size: 13px; }

  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px; }
  .card { background: var(--surface-1); border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; box-shadow: var(--shadow); display: flex; flex-direction: column; }
  .card-head { background: var(--sign-blue-pale); padding: 12px 16px; border-bottom: 1px solid var(--line); }
  .aire-name { font-size: 16px; font-weight: 700; color: var(--sign-blue-deep); line-height: 1.15; margin: 0; text-transform: none; }
  .aire-route { font-size: 11px; color: var(--text-dim); margin: 2px 0 0; }
  .restaurants { padding: 12px 16px 4px; display: flex; flex-wrap: wrap; gap: 6px; }
  .r-chip { display: inline-flex; align-items: center; gap: 6px; background: var(--surface-2); border-radius: 8px; padding: 5px 9px 5px 6px; font-size: 12.5px; }
  .r-chip .icon-badge { width: 20px; height: 20px; border-radius: 5px; background: var(--sign-blue); display: flex; align-items: center; justify-content: center; flex: none; }
  .r-chip .icon-badge svg { width: 12px; height: 12px; stroke: #fff; fill: none; }
  .services { padding: 10px 16px 14px; display: flex; gap: 14px; flex-wrap: wrap; margin-top: auto; border-top: 1px dashed var(--line); }
  .service { display: flex; align-items: center; gap: 5px; font-size: 11px; color: var(--text-dim); text-decoration: none; }
  .service svg { width: 15px; height: 15px; stroke: var(--text-dim); fill: none; }
  .maps-link { margin-left: auto; color: var(--sign-blue); }

  .stat-row { display: flex; gap: 18px; padding: 12px 16px 16px; }
  .stat { display: flex; flex-direction: column; }
  .stat-num { font-family: var(--font-mono); font-size: 22px; font-weight: 700; line-height: 1; }
  .stat-num-label { font-size: 10px; color: var(--text-dim); letter-spacing: 0.06em; margin-top: 3px; }

  footer.legal { max-width: 1180px; margin: 34px auto 0; padding: 16px 20px 0; border-top: 1px solid var(--line); font-size: 12px; color: var(--text-dim); }
  footer.legal a { color: var(--sign-blue); }

  @media (max-width: 640px) {
    h1 { font-size: 24px; }
    .route-badge { font-size: 26px; }
  }
"""


def build_sitemap(all_routes):
    urls = [f"{DOMAIN}/", f"{DOMAIN}/aires/"] + [
        f"{DOMAIN}/aires/{r['id'].lower()}/" for r in all_routes
    ]
    body = "".join(f"  <url><loc>{u}</loc></url>\n" for u in urls)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{body}</urlset>\n'


def build_robots():
    return f"User-agent: *\nAllow: /\n\nSitemap: {DOMAIN}/sitemap.xml\n"


def main():
    routes = load_routes()
    aires_dir = ROOT / "aires"
    aires_dir.mkdir(exist_ok=True)

    (aires_dir / "index.html").write_text(render_hub_page(routes), encoding="utf-8")

    for route in routes:
        slug = route["id"].lower()
        route_dir = aires_dir / slug
        route_dir.mkdir(exist_ok=True)
        (route_dir / "index.html").write_text(render_route_page(route, routes), encoding="utf-8")

    (ROOT / "sitemap.xml").write_text(build_sitemap(routes), encoding="utf-8")
    (ROOT / "robots.txt").write_text(build_robots(), encoding="utf-8")

    print(f"Generated {len(routes)} route pages + hub + sitemap.xml + robots.txt")


if __name__ == "__main__":
    main()
