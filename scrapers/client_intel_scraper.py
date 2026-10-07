import os
import re
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
import xml.etree.ElementTree as ET
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class ClientIntelScraper:
    """
    Dedicated intelligence engine for Tanagra clients.
    Polls targeted wire feeds per client and cross-matches contract awards.
    """
    CLIENTS = [
        {"name": "Aalyria", "query": '"Aalyria"', "domain": "aalyria.com"},
        {"name": "American TeraWatt", "query": '"American TeraWatt"', "domain": "americanterawatt.com"},
        {"name": "AnySignal", "query": '"AnySignal"', "domain": "anysignal.com"},
        {"name": "Apex Space", "query": '"Apex Space" OR ("Apex" AND "satellite")', "domain": "apexspace.com"},
        {"name": "Asymm Labs", "query": '"Asymm Labs"', "domain": "asymmlabs.com"},
        {"name": "BAE Systems", "query": '"BAE Systems" AND (space OR satellite OR missile)', "domain": "baesystems.com"},
        {"name": "Earthly Dynamics", "query": '"Earthly Dynamics"', "domain": "earthlydynamics.com"},
        {"name": "Ephemeris", "query": '"Ephemeris" AND (space OR satellite OR orbit)', "domain": "ephemeris.net"},
        {"name": "HawkEye 360", "query": '"HawkEye 360" OR "HE360"', "domain": "he360.com"},
        {"name": "Inversion Space", "query": '"Inversion Space"', "domain": "inversionspace.com"},
        {"name": "Kaizen Labs", "query": '"Kaizen Labs" AND (defense OR software OR tech)', "domain": "kaizenlabs.co"},
        {"name": "Kepler Space", "query": '"Kepler Communications" OR "Kepler Space"', "domain": "kepler.space"},
        {"name": "LeoLabs", "query": '"LeoLabs"', "domain": "leolabs.space"},
        {"name": "LodeStar Space", "query": '"LodeStar Space" OR "Lodestar Space"', "domain": "lodestar.space"},
        {"name": "Northwood Space", "query": '"Northwood Space"', "domain": "northwoodspace.io"},
        {"name": "Orbital Ops", "query": '"Orbital Ops"', "domain": "orbitalops.tech"},
        {"name": "Quindar", "query": '"Quindar" AND (space OR satellite)', "domain": "quindar.space"},
        {"name": "Radiant Nuclear", "query": '"Radiant Nuclear" OR ("Radiant" AND "reactor")', "domain": "radiantnuclear.com"},
        {"name": "Rocket Lab", "query": '"Rocket Lab" OR "RocketLab"', "domain": "rocketlabusa.com"},
        {"name": "Selene Industries", "query": '"Selene Industries"', "domain": "seleneindustries.com"},
        {"name": "Sierra Space", "query": '"Sierra Space"', "domain": "sierraspace.com"},
        {"name": "Space Kinetic", "query": '"Space Kinetic"', "domain": "spacekinetic.com"},
        {"name": "Star Catcher", "query": '"Star Catcher Industries" OR ("Star Catcher" AND "space")', "domain": "star-catcher.com"},
        {"name": "Starcloud", "query": '"Starcloud" AND (space OR satellite OR compute)', "domain": "starcloud.com"},
        {"name": "Starfish Space", "query": '"Starfish Space"', "domain": "starfishspace.com"},
        {"name": "Swoop Tech", "query": '"Swoop Tech" OR site:swooptech.com', "domain": "swooptech.com"},
        {"name": "TransAstra", "query": '"TransAstra"', "domain": "transastra.com"},
        {"name": "True Anomaly", "query": '"True Anomaly"', "domain": "trueanomaly.space"},
        {"name": "Vantor (Maxar)", "query": '"Vantor" OR "Maxar Technologies" OR "Maxar Space"', "domain": "maxar.com"}
    ]

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        })

    def _clean_text(self, text: str) -> str:
        if not text:
            return ""
        clean = re.sub(r"<[^>]+>", "", text)
        clean = clean.replace("&nbsp;", " ").replace("&amp;", "&").replace("&quot;", '"').replace("&#039;", "'")
        return re.sub(r"\s+", " ", clean).strip()

    def _fetch_client_news(self, client: dict, limit: int = 10) -> List[Dict[str, Any]]:
        client_name = client["name"]
        encoded_q = requests.utils.quote(client["query"])
        feed_url = f"https://news.google.com/rss/search?q={encoded_q}&hl=en-US&gl=US&ceid=US:en"

        articles = []
        try:
            resp = self.session.get(feed_url, timeout=10)
            if resp.status_code != 200:
                return []

            root = ET.fromstring(resp.text)
            for item in root.findall(".//item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                pub_date = (item.findtext("pubDate") or "").strip()
                desc = self._clean_text(item.findtext("description") or "")

                # Split out publication source from Google News titles: "Title - Publisher"
                source = "News Wire"
                if " - " in title:
                    parts = title.rsplit(" - ", 1)
                    title = parts[0].strip()
                    source = parts[1].strip()

                if title and link:
                    articles.append({
                        "client": client_name,
                        "title": title,
                        "source": source,
                        "domain": client["domain"],
                        "pub_date": pub_date[:16] if pub_date else "Recent",
                        "description": desc[:300],
                        "url": link,
                        "type": "Trade News",
                        "ingested_at": datetime.now(timezone.utc).isoformat()
                    })
                if len(articles) >= limit:
                    break
        except Exception:
            pass

        return articles

    def cross_reference_existing_intel(self, contracts: List[dict], solicitations: List[dict]) -> List[Dict[str, Any]]:
        """Identifies any contract award or RFP explicitly naming a Tanagra client."""
        hits = []
        for client in self.CLIENTS:
            name_regex = re.compile(rf"\b{re.escape(client['name'])}\b", re.I)

            # Check DoD Contract Awards
            for c in contracts:
                text = f"{c.get('contractor', '')} {c.get('raw_text', '')}"
                if name_regex.search(text):
                    hits.append({
                        "client": client["name"],
                        "title": f"DoD Contract Award: {c.get('contractor')} ({c.get('award_amount')})",
                        "source": "Pentagon Defense.gov",
                        "domain": client["domain"],
                        "pub_date": "Contract Award",
                        "description": c.get("raw_text", "")[:300],
                        "url": "index.html",
                        "type": "Pentagon Contract Award",
                        "ingested_at": datetime.now(timezone.utc).isoformat()
                    })

            # Check Pre-Award RFPs
            for s in solicitations:
                text = f"{s.get('title', '')} {s.get('agency_office', '')}"
                if name_regex.search(text):
                    hits.append({
                        "client": client["name"],
                        "title": f"Pre-Award Solicitation: {s.get('title')}",
                        "source": s.get("source", "SAM.gov"),
                        "domain": client["domain"],
                        "pub_date": s.get("response_deadline", "Open"),
                        "description": f"Solicitation Number: {s.get('solicitation_number')} | Office: {s.get('agency_office')}",
                        "url": s.get("url", "index.html"),
                        "type": "Federal Pre-Award",
                        "ingested_at": datetime.now(timezone.utc).isoformat()
                    })
        return hits

    def scrape_all_clients(self, contracts: List[dict] = None, solicitations: List[dict] = None) -> List[Dict[str, Any]]:
        logging.info(f"Sweeping wire feeds across all {len(self.CLIENTS)} Tanagra clients...")
        all_news = []
        seen_titles = set()

        # Concurrent sweep of all 29 clients in under 5 seconds
        with ThreadPoolExecutor(max_workers=20) as executor:
            future_to_client = {executor.submit(self._fetch_client_news, c): c for c in self.CLIENTS}
            for future in as_completed(future_to_client):
                client_items = future.result()
                for item in client_items:
                    t_key = f"{item['client']}_{item['title'][:40]}".lower()
                    if t_key in seen_titles:
                        continue
                    seen_titles.add(t_key)
                    all_news.append(item)

        # Cross-reference awards
        if contracts or solicitations:
            cross_hits = self.cross_reference_existing_intel(contracts or [], solicitations or [])
            all_news.extend(cross_hits)

        logging.info(f"Captured {len(all_news)} total intelligence items for Tanagra clients.")
        return all_news
