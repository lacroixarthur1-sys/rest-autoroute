#!/usr/bin/env python3
"""Generate static, indexable per-route landing pages from the ROUTES data
embedded in index.html, plus a hub page, per-aire pages, sitemap.xml and
robots.txt.

Reuses the main app's design system (colors, cards, icons) so these pages
read as the same product, not a separate SEO bolt-on.

Run from anywhere: python3 scripts/generate_seo_pages.py
"""
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = ROOT / "index.html"
DOMAIN = "https://restautoroute.fr"
GEOCODE_CACHE_PATH = ROOT / "scripts" / "geocode_cache.json"
EV_CACHE_PATH = ROOT / "scripts" / "ev_cache.json"
NOMINATIM_UA = "RestAutorouteBot/1.0 (contact: lacroix.arthur1@gmail.com)"
FORMSPREE_URL = "https://formspree.io/f/xdenkryr"

WIDGETS_JS = """
  function reportAireError(btn, ev, aireName, routeId, pageUrl) {
    if (ev) { ev.preventDefault(); ev.stopPropagation(); }
    if (btn.disabled) return;
    btn.disabled = true;
    btn.textContent = 'Envoi...';
    fetch('""" + FORMSPREE_URL + """', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify({
        type: "Signalement d'erreur",
        _subject: "Signalement Rest'Autoroute : " + aireName,
        aire: aireName,
        autoroute: routeId,
        page: pageUrl
      })
    }).then(function (r) {
      btn.textContent = r.ok ? 'Signalé, merci ✓' : 'Erreur, réessayez';
      btn.disabled = r.ok;
    }).catch(function () {
      btn.textContent = 'Erreur, réessayez';
      btn.disabled = false;
    });
  }

  function sendFeedback(btn) {
    var wrap = btn.closest('.feedback-widget');
    wrap.querySelectorAll('.feedback-btn').forEach(function (b) { b.disabled = true; });
    fetch('""" + FORMSPREE_URL + """', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify({
        type: 'Sondage : site utile ?',
        _subject: "Rest'Autoroute — sondage : " + btn.dataset.val,
        reponse: btn.dataset.val,
        page: location.href
      })
    }).then(function (r) {
      wrap.querySelector('.feedback-q').style.display = 'none';
      wrap.querySelectorAll('.feedback-btn').forEach(function (b) { b.style.display = 'none'; });
      var t = wrap.querySelector('.feedback-thanks');
      t.textContent = r.ok ? 'Merci pour votre retour !' : "Erreur d'envoi, réessayez plus tard.";
      t.hidden = false;
    }).catch(function () {
      var t = wrap.querySelector('.feedback-thanks');
      t.textContent = "Erreur d'envoi, réessayez plus tard.";
      t.hidden = false;
      wrap.querySelectorAll('.feedback-btn').forEach(function (b) { b.style.display = 'none'; });
    });
  }
"""

WIDGETS_CSS = """
  .report-btn {
    -webkit-appearance: none; appearance: none; background: none; border: none;
    font-family: inherit; font-size: 11px; color: var(--text-dim); cursor: pointer;
    display: flex; align-items: center; gap: 5px; text-align: left;
    padding: 0 16px 12px; margin: -4px 0 0;
  }
  .report-btn:hover:not(:disabled) { color: var(--sign-blue); }
  .report-btn:disabled { cursor: default; opacity: 0.75; }

  .feedback-widget {
    max-width: 1180px; margin: 28px auto 0; padding: 16px 20px; border-top: 1px solid var(--line);
    display: flex; align-items: center; gap: 12px; flex-wrap: wrap; font-size: 13px; color: var(--text-dim);
  }
  .feedback-btn {
    -webkit-appearance: none; appearance: none; cursor: pointer; font-family: inherit; font-size: 13px;
    padding: 6px 14px; border-radius: 999px; border: 1px solid var(--line); background: var(--surface-1); color: var(--text);
  }
  .feedback-btn:hover:not(:disabled) { border-color: var(--sign-blue); color: var(--sign-blue); }
  .feedback-btn:disabled { opacity: 0.6; cursor: default; }
  .feedback-thanks { font-weight: 600; color: var(--sign-blue); }
"""

FEEDBACK_WIDGET_HTML = """
  <div class="feedback-widget">
    <span class="feedback-q">Ce site vous a-t-il été utile ?</span>
    <button class="feedback-btn" type="button" data-val="Oui" onclick="sendFeedback(this)">👍 Oui</button>
    <button class="feedback-btn" type="button" data-val="Non" onclick="sendFeedback(this)">👎 Non</button>
    <span class="feedback-thanks" hidden></span>
  </div>
"""

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


def slugify(name):
    name = name.replace("œ", "oe").replace("Œ", "Oe").replace("æ", "ae").replace("Æ", "Ae")
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    n = re.sub(r"[^a-zA-Z0-9]+", "-", n).strip("-").lower()
    return n or "aire"


def assign_slugs(route):
    seen = {}
    for aire in route["aires"]:
        base = slugify(aire["name"])
        if base in seen:
            seen[base] += 1
            aire["_slug"] = f"{base}-{seen[base]}"
        else:
            seen[base] = 1
            aire["_slug"] = base


def load_geocode_cache():
    if GEOCODE_CACHE_PATH.exists():
        return json.loads(GEOCODE_CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def save_geocode_cache(cache):
    GEOCODE_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def geocode(lat, lng, cache):
    key = f"{lat:.5f},{lng:.5f}"
    if key in cache:
        return cache[key]
    url = (
        "https://nominatim.openstreetmap.org/reverse?"
        + urllib.parse.urlencode({"lat": lat, "lon": lng, "format": "jsonv2", "zoom": 14, "accept-language": "fr"})
    )
    req = urllib.request.Request(url, headers={"User-Agent": NOMINATIM_UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        addr = data.get("address", {})
        commune = addr.get("village") or addr.get("town") or addr.get("city") or addr.get("hamlet") or addr.get("municipality")
        department = addr.get("state_district") or addr.get("county")
        town = addr.get("municipality")
        if town == commune:
            town = None
        result = {"commune": commune, "department": department, "town": town}
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
        result = {"commune": None, "department": None, "town": None}
    cache[key] = result
    time.sleep(1.1)
    return result


def fmt_pk(pk):
    s = f"{pk:.1f}"
    if s.endswith(".0"):
        s = s[:-2]
    return s.replace(".", ",")


def maps_link(name, route_id):
    q = urllib.parse.quote(f"{name} aire autoroute {route_id}")
    return f"https://www.google.com/maps/search/?api=1&query={q}"


def route_sort_key(route):
    return int(re.sub(r"\D", "", route["id"]) or 0)


def cuisine_counts(route):
    counts = {}
    for aire in route["aires"]:
        for r in aire["restaurants"]:
            t = r.get("t")
            counts[t] = counts.get(t, 0) + 1
    return counts


def render_card(aire, route, link=True, official_link=None):
    r_chips = "".join(
        f'<span class="r-chip"><span class="icon-badge"><svg><use href="#{CUISINE.get(r["t"], ("", "i-self"))[1]}"/></svg></span>{r["n"]}</span>'
        for r in aire["restaurants"]
    )
    svc_items = "".join(
        f'<span class="service"><svg><use href="#{SERVICES[s][1]}"/></svg>{SERVICES[s][0]}</span>'
        for s in aire.get("services", [])
        if s in SERVICES
    )
    if official_link:
        name_html = f'<a class="aire-link" href="{official_link}" target="_blank" rel="noopener">{aire["name"]}</a>'
    elif link:
        name_html = f'<a class="aire-link" href="{aire["_slug"]}/">{aire["name"]}</a>'
    else:
        name_html = aire["name"]
    page_url = f"{DOMAIN}/aires/{route['id'].lower()}/{aire['_slug']}/"
    report_onclick = (
        "reportAireError(this, event, "
        f"{json.dumps(aire['name'])}, {json.dumps(route['id'])}, {json.dumps(page_url)})"
    )
    return f"""
      <div class="card">
        <div class="card-head">
          <div>
            <p class="aire-name">{name_html}</p>
            <p class="aire-route">PK {fmt_pk(aire["pk"])} · {route["id"]}</p>
          </div>
        </div>
        <div class="restaurants">{r_chips}</div>
        <div class="services">
          {svc_items}
          <a class="service maps-link" href="{maps_link(aire["name"], route["id"])}" target="_blank" rel="noopener">Avis Google Maps ↗</a>
        </div>
        <button class="report-btn" type="button" onclick='{report_onclick}'>🚩 Signaler une erreur sur cette aire</button>
      </div>"""


def find_neighbors(aire, route):
    same_dir = sorted(
        [a for a in route["aires"] if a["direction"] == aire["direction"]], key=lambda a: a["pk"]
    )
    idx = next(i for i, a in enumerate(same_dir) if a["_slug"] == aire["_slug"])
    prev_a = same_dir[idx - 1] if idx > 0 else None
    next_a = same_dir[idx + 1] if idx < len(same_dir) - 1 else None
    return prev_a, next_a


def build_faq(aire, route, prev_a, next_a, destination, origin, sens_label):
    resto_list = ", ".join(f"{r['n']} ({CUISINE.get(r['t'], (r['t'],))[0]})" for r in aire["restaurants"])
    n = len(aire["restaurants"])
    svc_labels = [SERVICES[s][0] for s in aire.get("services", []) if s in SERVICES]
    geo = aire.get("_geo") or {}
    commune, department, town = geo.get("commune"), geo.get("department"), geo.get("town")

    faq = []
    faq.append((
        f"Combien de restaurants sur {aire['name']} ?",
        f"{n} restaurant{'s' if n > 1 else ''} sur {aire['name']} : {resto_list}.",
    ))
    faq.append((
        f"Quels services sont disponibles sur {aire['name']} ?",
        (f"En plus de la restauration : {', '.join(svc_labels).lower()}."
         if svc_labels else
         "Aucun service annexe (carburant, borne électrique...) recensé sur cette aire, hors restauration."),
    ))
    faq.append((
        f"{aire['name']} est-elle une aire de repos ou une aire de service ?",
        f"Dans le langage courant, {aire['name']} est souvent appelée aire de repos. Elle compte "
        f"{n} restaurant{'s' if n > 1 else ''}"
        + (f" et propose {', '.join(l.lower() for l in svc_labels)}" if svc_labels else "")
        + ", ce qui en fait techniquement une aire de service.",
    ))
    if next_a:
        dist = abs(next_a["pk"] - aire["pk"])
        faq.append((
            f"Quelle est la prochaine aire avec restaurant sur l'{route['id']} en direction de {destination} ?",
            f"{next_a['name']}, à {fmt_pk(dist)} km, avec {len(next_a['restaurants'])} restaurant{'s' if len(next_a['restaurants']) > 1 else ''}.",
        ))
    else:
        faq.append((
            f"Y a-t-il une autre aire avec restaurant après {aire['name']} vers {destination} ?",
            f"Non, {aire['name']} est la dernière aire avec restaurant sur l'{route['id']} avant d'arriver à {destination}.",
        ))
    if prev_a:
        dist = abs(aire["pk"] - prev_a["pk"])
        faq.append((
            f"Quelle est l'aire avec restaurant précédente, en venant de {origin} ?",
            f"{prev_a['name']}, {fmt_pk(dist)} km avant {aire['name']}.",
        ))
    faq.append((
        f"Dans quel sens se trouve {aire['name']} sur l'{route['id']} ?",
        f"{aire['name']} est au PK {fmt_pk(aire['pk'])} de l'{route['id']}, dans le sens {sens_label}.",
    ))
    if commune:
        loc = f"sur la commune de {commune}"
        if town:
            loc += f", à proximité de {town}"
        if department:
            loc += f" (département : {department})"
        faq.append((f"Où se trouve exactement {aire['name']} ?", f"{aire['name']} se situe {loc}."))

    ev = aire.get("_ev")
    if ev:
        connectors_str = ", ".join(ev["connectors"]) if ev["connectors"] else "type non précisé"
        extra = []
        extra.append("accès libre" if ev["n_open"] >= ev["n_reserved"] else "accès réservé (badge/abonnement) pour la plupart")
        extra.append("24h/24 7j/7" if ev["hours_247"] else "horaires variables selon les stations")
        if ev["all_free"]:
            extra.append("gratuit")
        elif ev["cb_payment"]:
            extra.append("paiement par carte bancaire possible")
        if ev["pmr"] == "accessible":
            extra.append("accessible PMR")
        faq.append((
            f"Peut-on recharger une voiture électrique près de {aire['name']} ?",
            f"Oui, {ev['n_points']} point{'s' if ev['n_points'] > 1 else ''} de recharge "
            f"({ev['n_stations']} station{'s' if ev['n_stations'] > 1 else ''}) sont recensés à moins d'1 km, "
            f"jusqu'à {ev['max_power_kw']} kW ({connectors_str}), {', '.join(extra)}. Source : base nationale IRVE.",
        ))
    else:
        faq.append((
            f"Peut-on recharger une voiture électrique près de {aire['name']} ?",
            f"Aucune borne de recharge n'est recensée à moins d'1 km de {aire['name']} dans la base nationale IRVE.",
        ))
    return faq


def render_aire_page(aire, route, all_routes):
    route_slug = route["id"].lower()
    aire_slug = aire["_slug"]
    r_chips = "".join(
        f'<span class="r-chip"><span class="icon-badge"><svg><use href="#{CUISINE.get(r["t"], ("", "i-self"))[1]}"/></svg></span>{r["n"]}</span>'
        for r in aire["restaurants"]
    )
    svc_items = "".join(
        f'<span class="service"><svg><use href="#{SERVICES[s][1]}"/></svg>{SERVICES[s][0]}</span>'
        for s in aire.get("services", [])
        if s in SERVICES
    )
    resto_names = ", ".join(r["n"] for r in aire["restaurants"])
    sens = "forward" if aire.get("direction") == "forward" else "reverse"
    sens_label = f"{route['from']} → {route['to']}" if sens == "forward" else f"{route['to']} → {route['from']}"
    destination = route["to"] if sens == "forward" else route["from"]
    origin = route["from"] if sens == "forward" else route["to"]
    ev = aire.get("_ev")

    title = (
        f"Restaurant {aire['name']} ({route['id']}) : {resto_names}"
        + (" + borne de recharge électrique" if ev else "")
        + " | Rest'Autoroute"
    )
    description = (
        f"{aire['name']}, aire de repos avec restaurant sur l'autoroute {route['id']} "
        f"(PK {fmt_pk(aire['pk'])}, sens {sens_label}) : "
        f"{resto_names}."
        + (f" Borne de recharge électrique à proximité ({ev['n_points']} points, jusqu'à {ev['max_power_kw']} kW)." if ev else "")
        + " Horaires, avis et services (carburant, boutique, aire de jeux...)."
    )

    other_aires = [a for a in route["aires"] if a["_slug"] != aire_slug]
    other_chips = "".join(
        f'<a class="chip" href="../{a["_slug"]}/">{a["name"]}</a>' for a in sorted(other_aires, key=lambda a: a["pk"])
    )

    prev_a, next_a = find_neighbors(aire, route)
    n_svc = len([s for s in aire.get("services", []) if s in SERVICES])
    svc_labels = [SERVICES[s][0] for s in aire.get("services", []) if s in SERVICES]
    n_resto = len(aire["restaurants"])
    geo = aire.get("_geo") or {}
    commune, department, town = geo.get("commune"), geo.get("department"), geo.get("town")
    lead_text = (
        f"{aire['name']} est une aire de repos (aire d'autoroute {route['id']}) au PK {fmt_pk(aire['pk'])}, "
        f"dans le sens {sens_label}. Elle compte {n_resto} restaurant{'s' if n_resto > 1 else ''}"
        f"{' et propose ' + ', '.join(l.lower() for l in svc_labels) if svc_labels else ''}."
    )
    if commune:
        lead_text += f" Elle se situe sur la commune de {commune}"
        if town:
            lead_text += f", à proximité de {town}"
        if department:
            lead_text += f" (département : {department})"
        lead_text += "."

    n_aires_route = len(route["aires"])
    n_restos_route = sum(len(a["restaurants"]) for a in route["aires"])
    corridor_text = (
        f"Sur l'{route['id']} ({route['from']} → {route['to']}), Rest'Autoroute référence "
        f"{n_aires_route} aires avec restaurant ({n_restos_route} restaurants au total), "
        f"réparties dans les deux sens de circulation."
    )

    practical_parts = []
    if next_a:
        practical_parts.append(
            f"En direction de {destination}, la prochaine aire avec restaurant est "
            f"<a href=\"../{next_a['_slug']}/\">{next_a['name']}</a>, à {fmt_pk(abs(next_a['pk'] - aire['pk']))} km."
        )
    else:
        practical_parts.append(f"C'est la dernière aire avec restaurant sur l'{route['id']} avant {destination}.")
    if prev_a:
        practical_parts.append(
            f"En venant de {origin}, l'aire précédente avec restaurant est "
            f"<a href=\"../{prev_a['_slug']}/\">{prev_a['name']}</a>, {fmt_pk(abs(aire['pk'] - prev_a['pk']))} km plus tôt."
        )
    else:
        practical_parts.append(f"C'est la première aire avec restaurant en venant de {origin}.")
    practical_html = " ".join(practical_parts)

    faq = build_faq(aire, route, prev_a, next_a, destination, origin, sens_label)
    glossary_link = '<a href="../../../aire-de-repos/">aire de repos</a>'
    faq_html = "".join(
        f'<details class="faq-item"><summary>{q}</summary><p>'
        + (a.replace("aire de repos", glossary_link, 1) if "aire de repos ou une aire de service" in q else a)
        + "</p></details>"
        for q, a in faq
    )
    if ev:
        connectors_str = ", ".join(ev["connectors"]) if ev["connectors"] else "non précisé"
        operators_str = ", ".join(ev["operators"]) if ev["operators"] else "non précisé"
        access_str = (
            f"{ev['n_open']} en accès libre" + (f" · {ev['n_reserved']} sur badge/abonnement" if ev["n_reserved"] else "")
            if ev["n_open"] or ev["n_reserved"] else "non précisé"
        )
        hours_str = "24h/24, 7j/7" if ev["hours_247"] else "variables selon les stations"
        if ev["all_free"]:
            payment_str = "gratuit"
        elif ev["any_free"]:
            payment_str = "gratuit sur certaines stations, CB possible sur les autres" if ev["cb_payment"] else "gratuit sur certaines stations"
        elif ev["cb_payment"]:
            payment_str = "carte bancaire (sans abonnement)"
        else:
            payment_str = "badge / appli opérateur"
        pmr_str = {"accessible": "oui", "not_accessible": "non", "unknown": "non précisé"}[ev["pmr"]]
        reservation_str = "possible sur certaines stations" if ev["reservation"] else "non"
        specs = [
            ("Points de recharge", f"{ev['n_points']} ({ev['n_stations']} station{'s' if ev['n_stations'] > 1 else ''})"),
            ("Puissance max.", f"{ev['max_power_kw']} kW"),
            ("Prises", connectors_str),
            ("Opérateur(s)", operators_str),
            ("Accès", access_str),
            ("Horaires", hours_str),
            ("Paiement", payment_str),
            ("Réservation", reservation_str),
            ("Accessible PMR", pmr_str),
        ]
        specs_html = "".join(f'<div class="ev-spec"><span class="ev-spec-k">{k}</span><span class="ev-spec-v">{v}</span></div>' for k, v in specs)
        ev_html = (
            '<div class="ev-box"><p class="ev-title">⚡ Recharge électrique à proximité (moins d\'1 km)</p>'
            f'<div class="ev-specs">{specs_html}</div>'
            "<p class=\"ev-source\">Source : base nationale IRVE (data.gouv.fr) — infos statiques déclarées par les opérateurs, "
            "pas de disponibilité en temps réel.</p></div>"
        )
    else:
        ev_html = (
            '<div class="ev-box ev-none"><p class="ev-title">⚡ Recharge électrique</p>'
            "<p class=\"ev-detail\">Aucune borne recensée à moins d'1 km dans la base nationale IRVE.</p></div>"
        )

    ld_json = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Rest'Autoroute", "item": f"{DOMAIN}/"},
            {"@type": "ListItem", "position": 2, "name": "Autoroutes", "item": f"{DOMAIN}/aires/"},
            {"@type": "ListItem", "position": 3, "name": route["id"], "item": f"{DOMAIN}/aires/{route_slug}/"},
            {"@type": "ListItem", "position": 4, "name": aire["name"], "item": f"{DOMAIN}/aires/{route_slug}/{aire_slug}/"},
        ],
    }
    faq_ld_json = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {"@type": "Answer", "text": a},
            }
            for q, a in faq
        ],
    }

    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{description}">
<link rel="canonical" href="{DOMAIN}/aires/{route_slug}/{aire_slug}/">
<meta property="og:type" content="website">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:url" content="{DOMAIN}/aires/{route_slug}/{aire_slug}/">
<link rel="icon" href="../../../icons/favicon-32.png" sizes="32x32">
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-8743184001828384" crossorigin="anonymous"></script>
<script async src="https://www.googletagmanager.com/gtag/js?id=G-HBTCYGW0FW"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', 'G-HBTCYGW0FW');
</script>
<script>{WIDGETS_JS}</script>
<script type="application/ld+json">{json.dumps(ld_json, ensure_ascii=False)}</script>
<script type="application/ld+json">{json.dumps(faq_ld_json, ensure_ascii=False)}</script>
<style>
{PAGE_CSS}
</style>
</head>
<body>
{SVG_DEFS}

<div class="hero">
  <div class="brand">
    <a href="../../../" style="text-decoration:none;"><div class="brand-mark"><svg viewBox="0 0 24 24"><use href="#i-road"/></svg></div></a>
    <div>
      <p class="brand-name">Rest'<span>Autoroute</span></p>
      <p class="tagline">{aire["name"]} — Autoroute {route['id']}</p>
    </div>
  </div>
  <div class="theme-note"><a href="../">← Toutes les aires de l'{route['id']}</a></div>
</div>

<div class="page">

  <div class="console route-sign">
    <div class="route-sign-row">
      <div class="route-badge">{route['id']}</div>
      <div class="route-sign-info">
        <h1 class="route-h1">Restaurant {aire['name']}</h1>
        <div class="route-sign-cities">Sens {sens_label}</div>
        <div class="route-sign-stats">PK {fmt_pk(aire['pk'])} · {len(aire['restaurants'])} restaurant{"s" if len(aire['restaurants']) > 1 else ""}</div>
      </div>
    </div>
    <div class="cta-row">
      <a class="locate-cta" href="../../../?locate=1">
        <svg viewBox="0 0 24 24"><use href="#i-locate"/></svg>
        Me localiser — trouver l'aire d'autoroute à proximité
      </a>
      <a class="cta-link" href="../../../?route={route['id']}">
        <svg viewBox="0 0 24 24"><use href="#i-road"/></svg>
        Ouvrir le simulateur {route['id']} en manuel
      </a>
      <a class="cta-link" href="{aire["official"]}" target="_blank" rel="noopener">
        <svg viewBox="0 0 24 24"><use href="#i-info"/></svg>
        Fiche officielle de l'aire ↗
      </a>
    </div>
  </div>

  <p class="lead">{lead_text}</p>

  <div class="grid">{render_card(aire, route, link=False, official_link=aire["official"])}</div>

  {ev_html}

  <p class="practical">{practical_html}</p>

  <p class="context">{corridor_text}</p>

  <div class="faq">
    <h2 class="faq-title">Questions fréquentes</h2>
    {faq_html}
  </div>

  <div class="filters" style="margin-top:36px;">
    <span class="filters-label">Autres aires sur l'{route['id']} :</span>
    {other_chips}
  </div>

  <footer class="legal">
    Rest'Autoroute — les restaurants et aires listés ici proviennent d'OpenStreetMap et peuvent avoir changé depuis la collecte. Vérifiez sur place. <a href="../../../">Retour à l'accueil</a> · <a href="../">Toutes les aires de l'{route['id']}</a>.
  </footer>
  {FEEDBACK_WIDGET_HTML}
</div>
</body>
</html>
"""


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
        f"Liste complète des {n_restos} restaurants sur les aires de repos et de service de l'autoroute "
        f"{route['id']} entre {route['from']} et {route['to']} : self-service, burger, pizza, "
        f"boulangerie... Trouvez où manger avant de manquer la sortie."
    )

    other_routes_chips = "".join(
        f'<a class="chip" href="../{r["id"].lower()}/">{r["id"]}</a>'
        for r in sorted(all_routes, key=route_sort_key)
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
        cards = "".join(render_card(a, route) for a in aires)
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
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-8743184001828384" crossorigin="anonymous"></script>
<script async src="https://www.googletagmanager.com/gtag/js?id=G-HBTCYGW0FW"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', 'G-HBTCYGW0FW');
</script>
<script>{WIDGETS_JS}</script>
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
      <p class="brand-name">Rest'<span>Autoroute</span></p>
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
        <h1 class="route-h1">Restaurant Aire d'Autoroute {route['id']}</h1>
        <div class="route-sign-cities">{route['from']} → {route['to']}</div>
        <div class="route-sign-stats">{n_restos} restaurants · {n_aires} aires</div>
      </div>
    </div>
    <div class="cta-row">
      <a class="locate-cta" href="../../?locate=1">
        <svg viewBox="0 0 24 24"><use href="#i-locate"/></svg>
        Me localiser — trouver l'aire d'autoroute à proximité
      </a>
      <a class="cta-link" href="../../?route={route['id']}">
        <svg viewBox="0 0 24 24"><use href="#i-road"/></svg>
        Ouvrir le simulateur {route['id']} en manuel
      </a>
    </div>
  </div>

  <p class="lead">Toutes les aires de repos et aires de service avec restaurant sur l'{route['id']}.</p>

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
  {FEEDBACK_WIDGET_HTML}
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
        for r in sorted(all_routes, key=route_sort_key)
    )
    title = "Restaurant Aire d'Autoroute : toutes les autoroutes couvertes | Rest'Autoroute"
    description = "Trouvez une aire d'autoroute à proximité avec restaurant (aire de repos ou de service), sur toutes les autoroutes françaises couvertes par Rest'Autoroute : A6, A7, A10, A71..."
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
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-8743184001828384" crossorigin="anonymous"></script>
<script async src="https://www.googletagmanager.com/gtag/js?id=G-HBTCYGW0FW"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', 'G-HBTCYGW0FW');
</script>
<script>{WIDGETS_JS}</script>
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
      <p class="brand-name">Rest'<span>Autoroute</span></p>
      <p class="tagline">Choisissez votre autoroute pour voir les restaurants de ses aires.</p>
    </div>
  </div>
  <div class="theme-note"><a href="../">← Accueil</a></div>
</div>
<div class="page">
  <div class="console route-sign">
    <h1 class="route-h1" style="font-size:19px; margin-bottom:14px;">Restaurant Aire d'Autoroute : toutes les autoroutes couvertes</h1>
    <div class="cta-row">
      <a class="locate-cta" href="../?locate=1">
        <svg viewBox="0 0 24 24"><use href="#i-locate"/></svg>
        Me localiser — trouver l'aire d'autoroute à proximité
      </a>
      <a class="cta-link" href="../">
        <svg viewBox="0 0 24 24"><use href="#i-road"/></svg>
        Ouvrir le simulateur en manuel
      </a>
    </div>
  </div>
  <div class="hub-grid">{tiles}</div>
  <footer class="legal"><a href="../">← Retour à Rest'Autoroute</a> · <a href="../aire-de-repos/">Aire de repos ou aire de service : la différence</a></footer>
  {FEEDBACK_WIDGET_HTML}
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
  .brand-name { margin: 0; font-size: 30px; font-weight: 800; letter-spacing: 0.01em; line-height: 1; text-transform: none; font-family: var(--font-body); }
  .brand-name span { color: var(--amber); }
  .route-h1 { color: #fff; font-size: 17px; margin: 0 0 2px; font-weight: 700; letter-spacing: 0.02em; }
  .tagline { margin: 4px 0 0; font-size: 14.5px; color: var(--text-dim); max-width: 46ch; }
  .theme-note { font-size: 13px; }
  .theme-note a { color: var(--sign-blue); text-decoration: none; font-weight: 600; }

  .console { background: linear-gradient(160deg, var(--sign-blue-deep), var(--sign-blue)); border-radius: var(--radius); padding: 20px 22px; box-shadow: var(--shadow); color: #fff; margin-bottom: 22px; }
  .route-sign-row { display: flex; align-items: center; gap: 18px; flex-wrap: wrap; margin-bottom: 16px; }
  .route-badge { font-family: var(--font-display); font-size: 34px; font-weight: 800; background: #fff; color: var(--sign-blue-deep); padding: 6px 16px; border-radius: 8px; letter-spacing: 0.02em; line-height: 1; flex: none; }
  .route-sign-cities { font-size: 14px; text-transform: uppercase; letter-spacing: 0.06em; opacity: 0.85; font-family: var(--font-display); }
  .route-sign-stats { font-size: 22px; font-weight: 800; margin-top: 2px; }
  .cta-row { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 6px; }
  .locate-cta, .cta-link {
    flex: 1 1 200px;
    display: inline-flex; align-items: center; justify-content: center; gap: 9px;
    padding: 14px 20px; border-radius: 12px; font-family: var(--font-body);
    font-weight: 700; font-size: 14px; text-decoration: none; text-align: center;
    transition: transform 0.15s ease, box-shadow 0.15s ease, background 0.15s ease, border-color 0.15s ease;
  }
  .locate-cta {
    background: linear-gradient(135deg, var(--amber), var(--amber-deep));
    color: #241703; border: 2px solid rgba(255,255,255,0.55);
    box-shadow: 0 10px 26px rgba(224,138,30,0.5), 0 0 0 1px rgba(0,0,0,0.05);
  }
  .locate-cta:hover { transform: translateY(-2px); box-shadow: 0 14px 32px rgba(224,138,30,0.6), 0 0 0 1px rgba(0,0,0,0.05); }
  .locate-cta:active { transform: translateY(0); }
  .locate-cta svg { width: 19px; height: 19px; stroke: #241703; fill: none; flex: none; }
  .cta-link {
    background: rgba(255,255,255,0.1); color: #fff; border: 2px solid rgba(255,255,255,0.5);
  }
  .cta-link:hover { background: rgba(255,255,255,0.2); border-color: rgba(255,255,255,0.75); transform: translateY(-2px); }
  .cta-link:active { transform: translateY(0); }
  .cta-link svg { width: 17px; height: 17px; stroke: currentColor; fill: none; flex: none; }

  .filters { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 4px 0 20px; }
  .filters .filters-label { font-size: 11.5px; color: var(--text-dim); letter-spacing: 0.06em; margin-right: 4px; text-transform: uppercase; }
  .chip { display: inline-flex; align-items: center; gap: 6px; padding: 7px 12px; border-radius: 999px; border: 1px solid var(--line); background: var(--surface-1); color: var(--text-dim); font-size: 12px; letter-spacing: 0.03em; text-decoration: none; }
  .chip svg { width: 14px; height: 14px; stroke: currentColor; fill: none; }

  .lead { color: var(--text-dim); font-size: 14px; margin: 0 0 16px; }
  .practical { font-size: 13.5px; color: var(--text-dim); margin: 22px 0 0; line-height: 1.6; }
  .practical a { color: var(--sign-blue); font-weight: 600; text-decoration: none; }
  .practical a:hover { text-decoration: underline; }
  .context { font-size: 13.5px; color: var(--text-dim); margin: 10px 0 0; line-height: 1.6; }

  .ev-box { background: var(--surface-1); border: 1px solid var(--line); border-radius: var(--radius); padding: 14px 16px; margin-top: 16px; }
  .ev-box.ev-none { opacity: 0.75; }
  .ev-title { font-weight: 700; font-size: 13.5px; margin: 0 0 10px; color: var(--sign-blue-deep); }
  .ev-detail { font-size: 13px; color: var(--text-dim); margin: 0; line-height: 1.5; }
  .ev-source { font-size: 11px; color: var(--text-dim); margin: 10px 0 0; opacity: 0.8; }
  .ev-specs { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 10px 18px; }
  .ev-spec { display: flex; flex-direction: column; gap: 2px; }
  .ev-spec-k { font-size: 10.5px; color: var(--text-dim); letter-spacing: 0.04em; text-transform: uppercase; }
  .ev-spec-v { font-size: 13.5px; font-weight: 600; }


  .faq { margin-top: 28px; }
  .faq-title { font-size: 15px; letter-spacing: 0.04em; color: var(--sign-blue); margin: 0 0 10px; }
  .faq-item { background: var(--surface-1); border: 1px solid var(--line); border-radius: 10px; padding: 12px 16px; margin-bottom: 8px; }
  .faq-item summary { cursor: pointer; font-weight: 600; font-size: 13.5px; list-style: none; }
  .faq-item summary::-webkit-details-marker { display: none; }
  .faq-item summary::before { content: "+ "; color: var(--sign-blue); font-weight: 800; }
  .faq-item[open] summary::before { content: "– "; }
  .faq-item p { font-size: 13px; color: var(--text-dim); margin: 8px 0 0; line-height: 1.55; }

  .results-meta { display: flex; justify-content: space-between; align-items: baseline; margin: 28px 0 12px; flex-wrap: wrap; gap: 8px; }
  .results-meta h2 { font-size: 15px; margin: 0; letter-spacing: 0.04em; color: var(--sign-blue); }
  .results-meta h2.dim { color: var(--text-dim); font-weight: 500; text-transform: none; font-family: var(--font-body); font-size: 13px; }

  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px; }
  .card { background: var(--surface-1); border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; box-shadow: var(--shadow); display: flex; flex-direction: column; }
  .card-head { background: var(--sign-blue-pale); padding: 12px 16px; border-bottom: 1px solid var(--line); }
  .aire-name { font-size: 16px; font-weight: 700; color: var(--sign-blue-deep); line-height: 1.15; margin: 0; text-transform: none; }
  .aire-link { text-decoration: none; }
  .aire-link:hover { text-decoration: underline; }
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
""" + WIDGETS_CSS


def render_glossary_page(all_routes):
    title = "Aire de repos : définition, différence avec une aire de service | Rest'Autoroute"
    description = (
        "Qu'est-ce qu'une aire de repos ? Différence avec une aire de service, comment trouver "
        "l'aire de repos avec restaurant la plus proche de vous, sur les 48 autoroutes couvertes "
        "par Rest'Autoroute."
    )
    route_chips = "".join(
        f'<a class="chip" href="../aires/{r["id"].lower()}/">{r["id"]}</a>'
        for r in sorted(all_routes, key=route_sort_key)
    )
    faq = [
        (
            "Qu'est-ce qu'une aire de repos ?",
            "Une aire de repos est un espace aménagé le long d'une autoroute pour permettre aux "
            "automobilistes de faire une pause : parking, tables de pique-nique, toilettes. Dans le "
            "langage courant, le terme désigne aussi les aires avec restaurant et carburant, plus "
            "précisément appelées aires de service.",
        ),
        (
            "Quelle est la différence entre une aire de repos et une aire de service ?",
            "Une aire de repos, au sens strict, ne propose que du stationnement et des sanitaires, sans "
            "commerce. Une aire de service ajoute au moins une station-service, et souvent un "
            "restaurant, une boutique ou une borne de recharge électrique. Toutes les aires référencées "
            "sur Rest'Autoroute ont au moins un restaurant : ce sont donc, au sens strict, des aires de "
            "service — même si beaucoup d'automobilistes continuent de les appeler aires de repos.",
        ),
        (
            "Comment trouver l'aire de repos avec restaurant la plus proche de moi ?",
            "Utilisez le bouton « Me localiser » sur la page d'accueil de Rest'Autoroute : le site utilise "
            "votre position pour identifier l'aire avec restaurant la plus proche sur votre trajet, dans "
            "les deux sens de circulation.",
        ),
        (
            "Toutes les aires de repos ont-elles un restaurant ?",
            "Non. Certaines aires de repos ne proposent que des toilettes et un parking, sans aucun "
            "commerce. Rest'Autoroute référence uniquement les aires qui ont au moins un restaurant, sur "
            "48 autoroutes françaises.",
        ),
        (
            "Comment trouver une aire de repos sur mon trajet d'autoroute ?",
            "Choisissez votre autoroute dans le simulateur de la page d'accueil, ou indiquez votre trajet "
            "complet (ville de départ et d'arrivée) pour voir toutes les aires avec restaurant sur votre "
            "parcours, classées par kilomètre.",
        ),
    ]
    faq_html = "".join(f'<details class="faq-item"><summary>{q}</summary><p>{a}</p></details>' for q, a in faq)

    ld_json = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Rest'Autoroute", "item": f"{DOMAIN}/"},
            {"@type": "ListItem", "position": 2, "name": "Aire de repos", "item": f"{DOMAIN}/aire-de-repos/"},
        ],
    }
    faq_ld_json = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
            for q, a in faq
        ],
    }

    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{description}">
<link rel="canonical" href="{DOMAIN}/aire-de-repos/">
<meta property="og:type" content="website">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:url" content="{DOMAIN}/aire-de-repos/">
<link rel="icon" href="../icons/favicon-32.png" sizes="32x32">
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-8743184001828384" crossorigin="anonymous"></script>
<script async src="https://www.googletagmanager.com/gtag/js?id=G-HBTCYGW0FW"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', 'G-HBTCYGW0FW');
</script>
<script>{WIDGETS_JS}</script>
<script type="application/ld+json">{json.dumps(ld_json, ensure_ascii=False)}</script>
<script type="application/ld+json">{json.dumps(faq_ld_json, ensure_ascii=False)}</script>
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
      <p class="brand-name">Rest'<span>Autoroute</span></p>
      <p class="tagline">Aire de repos, aire de service : la différence, et où trouver un restaurant.</p>
    </div>
  </div>
  <div class="theme-note"><a href="../">← Accueil</a></div>
</div>
<div class="page">
  <div class="console route-sign">
    <h1 class="route-h1" style="font-size:19px; margin-bottom:14px;">Aire de repos : le guide complet</h1>
    <div class="cta-row">
      <a class="locate-cta" href="../?locate=1">
        <svg viewBox="0 0 24 24"><use href="#i-locate"/></svg>
        Me localiser — trouver l'aire de repos à proximité
      </a>
      <a class="cta-link" href="../aires/">
        <svg viewBox="0 0 24 24"><use href="#i-road"/></svg>
        Voir toutes les autoroutes
      </a>
    </div>
  </div>

  <p class="lead">
    Une <strong>aire de repos</strong> est un espace aménagé en bord d'autoroute pour faire une pause :
    parking, sanitaires, parfois des tables de pique-nique. Dans le langage courant, on appelle souvent
    « aire de repos » n'importe quelle aire d'autoroute — y compris celles qui ont un restaurant, une
    station-service ou une boutique, techniquement appelées <strong>aires de service</strong>.
    Rest'Autoroute référence uniquement les aires avec au moins un restaurant, sur 48 autoroutes
    françaises.
  </p>

  <p class="context">
    Vous cherchez l'aire de repos avec restaurant la plus proche de votre position, ou sur votre
    trajet ? Utilisez le bouton « Me localiser » ci-dessus, ou choisissez directement votre autoroute :
  </p>

  <div class="filters" style="margin-top:14px;">{route_chips}</div>

  <div class="faq">
    <p class="faq-title">QUESTIONS FRÉQUENTES</p>
    {faq_html}
  </div>

  <footer class="legal"><a href="../">← Retour à Rest'Autoroute</a></footer>
  {FEEDBACK_WIDGET_HTML}
</div>
</body>
</html>
"""


def build_sitemap(all_routes):
    urls = [f"{DOMAIN}/", f"{DOMAIN}/aires/", f"{DOMAIN}/aire-de-repos/"]
    for r in all_routes:
        slug = r["id"].lower()
        urls.append(f"{DOMAIN}/aires/{slug}/")
        for aire in r["aires"]:
            urls.append(f"{DOMAIN}/aires/{slug}/{aire['_slug']}/")
    body = "".join(f"  <url><loc>{u}</loc></url>\n" for u in urls)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{body}</urlset>\n'


def build_robots():
    return f"User-agent: *\nAllow: /\n\nSitemap: {DOMAIN}/sitemap.xml\n"


def main():
    routes = load_routes()
    for route in routes:
        assign_slugs(route)

    geo_cache = load_geocode_cache()
    total_aires = sum(len(r["aires"]) for r in routes)
    done = 0
    for route in routes:
        for aire in route["aires"]:
            aire["_geo"] = geocode(aire["lat"], aire["lng"], geo_cache)
            done += 1
            if done % 25 == 0:
                print(f"Geocoded {done}/{total_aires} aires...")
    save_geocode_cache(geo_cache)

    ev_cache = json.loads(EV_CACHE_PATH.read_text(encoding="utf-8")) if EV_CACHE_PATH.exists() else {}
    for route in routes:
        for aire in route["aires"]:
            aire["_ev"] = ev_cache.get(f"{aire['lat']:.5f},{aire['lng']:.5f}")

    aires_dir = ROOT / "aires"
    aires_dir.mkdir(exist_ok=True)

    (aires_dir / "index.html").write_text(render_hub_page(routes), encoding="utf-8")

    glossary_dir = ROOT / "aire-de-repos"
    glossary_dir.mkdir(exist_ok=True)
    (glossary_dir / "index.html").write_text(render_glossary_page(routes), encoding="utf-8")

    n_aire_pages = 0
    for route in routes:
        slug = route["id"].lower()
        route_dir = aires_dir / slug
        route_dir.mkdir(exist_ok=True)
        (route_dir / "index.html").write_text(render_route_page(route, routes), encoding="utf-8")

        for aire in route["aires"]:
            aire_dir = route_dir / aire["_slug"]
            aire_dir.mkdir(exist_ok=True)
            (aire_dir / "index.html").write_text(render_aire_page(aire, route, routes), encoding="utf-8")
            n_aire_pages += 1

    (ROOT / "sitemap.xml").write_text(build_sitemap(routes), encoding="utf-8")
    (ROOT / "robots.txt").write_text(build_robots(), encoding="utf-8")

    print(f"Generated {len(routes)} route pages + {n_aire_pages} aire pages + hub + sitemap.xml + robots.txt")


if __name__ == "__main__":
    main()
