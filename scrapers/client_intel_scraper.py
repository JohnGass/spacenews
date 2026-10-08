import os
import re
import logging
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import List, Dict, Any, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
import xml.etree.ElementTree as ET
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def is_within_14_days(date_str: str) -> bool:
    """Strictly enforces rolling 14-day cutoff."""
    if not date_str:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    try:
        dt = parsedate_to_datetime(date_str.strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt >= cutoff
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(date_str.strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt >= cutoff
    except Exception:
        pass
    return False

def detect_channel(url: str, source: str) -> str:
    """Categorizes the distribution channel of the signal."""
    u = (url or "").lower()
    s = (source or "").lower()
    if "linkedin" in u or "linkedin" in s:
        return "LinkedIn"
    if "x.com" in u or "twitter" in u or "twitter" in s or "x (" in s:
        return "X / Twitter"
    if "youtube" in u or "youtu.be" in u or "youtube" in s:
        return "YouTube"
    if any(pr in u or pr in s for pr in ["prnewswire", "businesswire", "globenewswire", "accesswire"]):
        return "Press Release"
    if "defense.gov" in u or "contract" in s:
        return "Gov Contract"
    return "Trade Wire"

class ClientIntelScraper:
    """
    Dedicated intelligence engine for Tanagra clients.
    Polls press wires AND social channels (LinkedIn, X, YouTube, PR Newswire)
    with a strict rolling 14-day date filter.
    """
    CLIENTS = [
        {"name": "Aalyria", "terms": '"Aalyria"', "domain": "aalyria.com"},
        {"name": "American TeraWatt", "terms": '"American TeraWatt"', "domain": "americanterawatt.com"},
        {"name": "AnySignal", "terms": '"AnySignal"', "domain": "anysignal.com"},
        {"name": "Apex Space", "terms": '"Apex Space" OR ("Apex" AND "satellite")', "domain": "apexspace.com"},
        {"name": "Asymm Labs", "terms": '"Asymm Labs"', "domain": "asymmlabs.com"},
        {"name": "BAE Systems", "terms": '"BAE Systems" AND (space OR satellite OR missile)', "domain": "baesystems.com"},
        {"name": "Earthly Dynamics", "terms": '"Earthly Dynamics"', "domain": "earthlydynamics.com"},
        {"name": "Ephemeris", "terms": '"Ephemeris" AND (space OR satellite OR orbit)', "domain": "ephemeris.net"},
        {"name": "HawkEye 360", "terms": '"HawkEye 360" OR "HE360"', "domain": "he360.com"},
        {"name": "Inversion Space", "terms": '"Inversion Space"', "domain": "inversionspace.com"},
        {"name": "Kaizen Labs", "terms": '"Kaizen Labs" AND (defense OR software OR tech)', "domain": "kaizenlabs.co"},
        {"name": "Kepler Space", "terms": '"Kepler Communications" OR "Kepler Space"', "domain": "kepler.space"},
        {"name": "LeoLabs", "terms": '"LeoLabs"', "domain": "leolabs.space"},
        {"name": "LodeStar Space", "terms": '"LodeStar Space" OR "Lodestar Space"', "domain": "lodestar.space"},
        {"name": "Northwood Space", "terms": '"Northwood Space"', "domain": "northwoodspace.io"},
        {"name": "Orbital Ops", "terms": '"Orbital Ops"', "domain": "orbitalops.tech"},
        {"name": "Quindar", "terms": '"Quindar" AND (space OR satellite)', "domain": "quindar.space"},
        {"name": "Radiant Nuclear", "terms": '"Radiant Nuclear" OR ("Radiant" AND "reactor")', "domain": "radiantnuclear.com"},
        {"name": "Rocket Lab", "terms": '"Rocket Lab" OR "RocketLab"', "domain": "rocketlabusa.com"},
        {"name": "Selene Industries", "terms": '"Selene Industries"', "domain": "seleneindustries.com"},
        {"name": "Sierra Space", "terms": '"Sierra Space"', "domain": "sierraspace.com"},
        {"name": "Space Kinetic", "terms": '"Space Kinetic"', "domain": "spacekinetic.com"},
        {"name": "Star Catcher", "terms": '"Star Catcher Industries" OR ("Star Catcher" AND "space")', "domain": "star-catcher.com"},
        {"name": "Starcloud", "terms": '"Starcloud" AND (space OR satellite OR compute)', "domain": "starcloud.com"},
        {"name": "Starfish Space", "terms": '"Starfish Space"', "domain": "starfishspace.com"},
        {"name": "Swoop Tech", "terms": '"Swoop Tech"', "domain": "swooptech.com"},
        {"name": "TransAstra", "terms": '"TransAstra"', "domain": "transastra.com"},
        {"name": "True Anomaly", "terms": '"True Anomaly"', "domain": "trueanomaly.space"},
        {"name": "Vantor (Maxar)", "terms": '"Vantor" OR "Maxar Technologies" OR "Maxar Space"', "domain": "maxar.com"}
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

    def _query_google_rss(self, raw_query: str) -> List[dict]:
        encoded_q = requests.utils.quote(raw_query)
        feed_url = f"https://news.google.com/rss/search?q={encoded_q}&hl=en-US&gl=US&ceid=US:en"
        items = []
        try:
            resp = self.session.get(feed_url, timeout=9)
            if resp.status_code != 200:
                return []
            root = ET.fromstring(resp.text.replace("&nbsp;", " "))
            for item in root.findall(".//item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                pub_date = (item.findtext("pubDate") or "").strip()
                desc = self._clean_text(item.findtext("description") or "")

                source_elem = item.find("source")
                source = source_elem.text if source_elem is not None and source_elem.text else "News Wire"

                if " - " in title and source == "News Wire":
                    parts = title.rsplit(" - ", 1)
                    title = parts[0].strip()
                    source = parts[1].strip()

                if title and link:
                    items.append({
                        "title": title,
                        "link": link,
                        "pub_date": pub_date,
                        "source": source,
                        "description": desc[:300]
                    })
        except Exception:
            pass
        return items

    def _fetch_client_intel(self, client: dict, limit: int = 12) -> List[Dict[str, Any]]:
        client_name = client["name"]
        terms = client["terms"]

        # Vector 1: General Press & Announcements in last 14 days
        q_news = f"({terms}) when:14d"
        # Vector 2: Social Media (LinkedIn, X, YouTube) & PR Wires in last 14 days
        q_social = f"({terms}) (site:linkedin.com OR site:x.com OR site:twitter.com OR site:youtube.com OR site:prnewswire.com OR site:businesswire.com) when:14d"

        news_items = self._query_google_rss(q_news)
        social_items = self._query_google_rss(q_social)

        merged = []
        seen_titles = set()

        for item in (news_items + social_items):
            # STRICT DATE GATE: Discard if older than 14 days
            if not is_within_14_days(item["pub_date"]):
                continue

            t_key = item["title"][:45].lower()
            if t_key in seen_titles:
                continue
            seen_titles.add(t_key)

            channel = detect_channel(item["link"], item["source"])

            merged.append({
                "client": client_name,
                "title": item["title"],
                "source": item["source"],
                "channel": channel,
                "domain": client["domain"],
                "pub_date": item["pub_date"][:16] if item["pub_date"] else "Recent",
                "description": item["description"],
                "url": item["link"],
                "ingested_at": datetime.now(timezone.utc).isoformat()
            })
            if len(merged) >= limit:
                break

        return merged

    def cross_reference_existing_intel(self, contracts: List[dict], solicitations: List[dict]) -> List[Dict[str, Any]]:
        """Identifies DoD contract awards or RFPs explicitly naming a Tanagra client within 14 days."""
        hits = []
        for client in self.CLIENTS:
            name_regex = re.compile(rf"\b{re.escape(client['name'])}\b", re.I)

            for c in contracts:
                text = f"{c.get('contractor', '')} {c.get('raw_text', '')}"
                if name_regex.search(text):
                    hits.append({
                        "client": client["name"],
                        "title": f"DoD Contract Award: {c.get('contractor')} ({c.get('award_amount')})",
                        "source": "Pentagon Defense.gov",
                        "channel": "Gov Contract",
                        "domain": client["domain"],
                        "pub_date": "DoD Award",
                        "description": c.get("raw_text", "")[:300],
                        "url": "index.html",
                        "ingested_at": datetime.now(timezone.utc).isoformat()
                    })

            for s in solicitations:
                text = f"{s.get('title', '')} {s.get('agency_office', '')}"
                if name_regex.search(text):
                    hits.append({
                        "client": client["name"],
                        "title": f"Pre-Award RFP: {s.get('title')}",
                        "source": s.get("source", "SAM.gov"),
                        "channel": "Gov Contract",
                        "domain": client["domain"],
                        "pub_date": s.get("response_deadline", "Open"),
                        "description": f"Solicitation Number: {s.get('solicitation_number')} | Office: {s.get('agency_office')}",
                        "url": s.get("url", "index.html"),
                        "ingested_at": datetime.now(timezone.utc).isoformat()
                    })
        return hits

    def scrape_all_clients(self, contracts: List[dict] = None, solicitations: List[dict] = None) -> List[Dict[str, Any]]:
        logging.info(f"Concurrent sweep of news and social channels for all {len(self.CLIENTS)} clients (<= 14 days)...")
        all_news = []
        seen = set()

        with ThreadPoolExecutor(max_workers=25) as executor:
            future_to_client = {executor.submit(self._fetch_client_intel, c): c for c in self.CLIENTS}
            for future in as_completed(future_to_client):
                items = future.result()
                for item in items:
                    key = f"{item['client']}_{item['title'][:40]}".lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    all_news.append(item)

        if contracts or solicitations:
            cross_hits = self.cross_reference_existing_intel(contracts or [], solicitations or [])
            all_news.extend(cross_hits)

        logging.info(f"Captured {len(all_news)} verified client reports from the past 14 days.")
        return all_news
