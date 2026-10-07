import os
import re
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Set
import xml.etree.ElementTree as ET
import requests
from scrapers.filter_rules import evaluate_relevance

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class SpaceNewsScraper:
    """
    Broad-spectrum Space Intelligence Ingestion Engine.
    Aggregates across 16 premier national security, commercial, launch, 
    allied/international, and analytical space reporting feeds.
    """
    FEEDS = [
        # --- Strategic Analysis & Doctrine ---
        {"name": "The Space Review", "url": "https://www.thespacereview.com/feed.xml", "tier": "Strategic Analysis"},
        
        # --- Launch Operations & Technical Investigative ---
        {"name": "Ars Technica Space", "url": "https://arstechnica.com/space/feed/", "tier": "Technical & Launch"},
        {"name": "Spaceflight Now", "url": "https://spaceflightnow.com/feed/", "tier": "Mission Ops"},
        
        # --- National Security, Pentagon & Policy ---
        {"name": "Breaking Defense", "url": "https://breakingdefense.com/category/space/feed/", "tier": "National Security Space"},
        {"name": "Air & Space Forces", "url": "https://www.airandspaceforces.com/category/space/feed/", "tier": "USSF & Force Design"},
        {"name": "Defense News", "url": "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml", "tier": "Defense Acquisition"},
        {"name": "Defense One", "url": "https://www.defenseone.com/rss/all/", "tier": "Pentagon Strategy"},
        {"name": "C4ISRNET", "url": "https://www.c4isrnet.com/arc/outboundfeeds/rss/?outputType=xml", "tier": "Space C2 & Sensors"},
        {"name": "SpacePolicyOnline", "url": "https://spacepolicyonline.com/feed/", "tier": "Policy & Hill"},

        # --- Commercial Industry & Satellite Communications ---
        {"name": "SpaceNews", "url": "https://spacenews.com/feed/", "tier": "Global Space Industry"},
        {"name": "Payload Space", "url": "https://payloadspace.com/feed/", "tier": "Space Economy & Venture"},
        {"name": "SatNews", "url": "https://news.satnews.com/feed/", "tier": "Satellite & Payloads"},
        {"name": "Via Satellite", "url": "https://www.satellitetoday.com/feed/", "tier": "COMSATCOM & Commercial"},

        # --- Allied & International ---
        {"name": "European Spaceflight", "url": "https://europeanspaceflight.com/feed/", "tier": "European Launch & Industry"},
        {"name": "SpaceRef", "url": "https://spaceref.com/feed/", "tier": "Global Exploration"},
        {"name": "NASA News", "url": "https://www.nasa.gov/news-release/feed/", "tier": "Civil Agency"}
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

    def _classify_topic(self, title: str, description: str) -> str:
        corpus = f"{title} {description}"

        # 1. Executive / C-Suite / Corporate M&A moves ALWAYS route to Commercial
        exec_pattern = re.compile(
            r"\b(names|appoints|taps|hires|named|executive|c-suite|ceo|coo|cfo|cto|president|"
            r"board\s+of\s+directors|merger|merges|acquires|acquisition|earnings|quarterly|"
            r"revenue|profit|loss|shares|nasdaq|nyse|valuation|spac|funding\s+round|series\s+[a-d])\b",
            re.IGNORECASE
        )
        if exec_pattern.search(title):
            return "Commercial"

        # 2. Strategic Geopolitical Competitors
        if re.search(r"\b(china|chinese|cnsa|beijing|tiangong|chang'e|long\s*march|casc|casic|landspace|deep\s*blue|yuanwang|tianwen)\b", corpus, re.I):
            return "China"
        if re.search(r"\b(russia|russian|roscosmos|moscow|angara|soyuz|vostochny|plesetsk|glonass)\b", corpus, re.I):
            return "Russia"

        # 3. Policy, Hill & Regulatory
        if re.search(r"\b(congress|senate|house|hasc|sasc|appropriations|ndaa|lawmaker|capitol\s*hill|legislation|white\s*house|space\s*council|faa|fcc|treaty|budget|regulatory)\b", corpus, re.I):
            return "Policy & Hill"

        # 4. Launch & Propulsion (Rockets, Boosters, Launch Events - strictly excludes loose 'orbit')
        if re.search(r"\b(launch|launches|launched|launching|rocket|booster|liftoff|starship|falcon\s*9|falcon\s*heavy|new\s*glenn|vulcan|sls|super\s*heavy|electron|static\s*fire|engine\s*test|hot\s*fire|pad\s*[0-9a-zA-Z]+|spaceport|cape\s*canaveral|vandenberg|kourou)\b", corpus, re.I):
            return "Launch"

        # 5. Spacecraft & In-Orbit Operations (Sensors, Tracking, RF, SDA, RPO)
        if re.search(r"\b(spacecraft|satellite|satellites|constellation|bus|rf-sensor|sensor|sensors|payload|on-orbit|in-orbit|orbital\s*target|orbital\s*debris|rendezvous|docking|proximity|rpo|space\s*domain\s*awareness|sda|ssa|space\s*tracking|maneuver|deorbit|flight\s*operations)\b", corpus, re.I):
            return "Spacecraft & Ops"

        # 6. Novel Technology & Research
        if re.search(r"\b(optical\s*comm|laser|quantum|nuclear|solar\s*array|ai|edge\s*compute|isam|in-space\s*servicing|refueling|materials|additive)\b", corpus, re.I):
            return "Technology"

        # 7. Commercial Space Ventures & Startups
        if re.search(r"\b(commercial|venture|startup|investment|spacex|blue\s*origin|rocket\s*lab|astrobotic|axiom|planet\s*labs|spire|capella|hawkeye)\b", corpus, re.I):
            return "Commercial"

        # 8. Allied & International
        if re.search(r"\b(esa|europe|european|jaxa|japan|isro|india|uae|australia|uk\s*space|artemis\s*accords)\b", corpus, re.I):
            return "International"

        return "National Security"

    def _parse_items(self, content: str) -> List[dict]:
        items = []
        try:
            root = ET.fromstring(content)
            for item in root.findall(".//item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                pub_date = (item.findtext("pubDate") or "").strip()
                creator = item.findtext("{http://purl.org/dc/elements/1.1/}creator") or ""
                desc = item.findtext("description") or ""

                if title and link:
                    items.append({
                        "title": title,
                        "link": link,
                        "pub_date": pub_date,
                        "author": creator.strip(),
                        "description": self._clean_text(desc)[:320]
                    })
        except Exception:
            for block in re.findall(r"<item>(.*?)</item>", content, re.DOTALL | re.IGNORECASE):
                t_m = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", block, re.DOTALL | re.IGNORECASE)
                l_m = re.search(r"<link>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>", block, re.DOTALL | re.IGNORECASE)
                p_m = re.search(r"<pubDate>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</pubDate>", block, re.DOTALL | re.IGNORECASE)
                d_m = re.search(r"<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", block, re.DOTALL | re.IGNORECASE)
                a_m = re.search(r"<dc:creator>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</dc:creator>", block, re.DOTALL | re.IGNORECASE)

                title = self._clean_text(t_m.group(1)) if t_m else ""
                link = l_m.group(1).strip() if l_m else ""
                pub_date = p_m.group(1).strip() if p_m else ""
                desc = self._clean_text(d_m.group(1)) if d_m else ""
                author = self._clean_text(a_m.group(1)) if a_m else ""

                if title and link:
                    items.append({
                        "title": title,
                        "link": link,
                        "pub_date": pub_date,
                        "author": author,
                        "description": desc[:320]
                    })
        return items

    def _cluster_related_reporting(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        def get_keywords(t: str) -> Set[str]:
            stopwords = {"space", "force", "launch", "first", "plans", "tests", "after", "about", "could", "would", "names", "taps", "with", "from"}
            words = set(re.findall(r"\b[a-zA-Z]{4,}\b", t.lower()))
            return words - stopwords

        for i, art in enumerate(articles):
            kw_i = get_keywords(art["title"])
            related = []
            for j, other in enumerate(articles):
                if i == j or art["source"] == other["source"]:
                    continue
                kw_j = get_keywords(other["title"])
                shared = kw_i & kw_j
                if len(shared) >= 2:
                    related.append({
                        "source": other["source"],
                        "title": other["title"],
                        "url": other["url"]
                    })
            art["related_coverage"] = related[:3]

        return articles

    def scrape_all_feeds(self, limit_per_feed: int = 15) -> List[Dict[str, Any]]:
        logging.info(f"Ingesting space wire from {len(self.FEEDS)} premier industry outlets...")
        all_articles = []
        seen_links: Set[str] = set()

        for feed in self.FEEDS:
            try:
                resp = self.session.get(feed['url'], timeout=18)
                if resp.status_code != 200:
                    continue

                raw_items = self._parse_items(resp.text)
                matches = 0

                for item in raw_items:
                    clean_link = item['link'].split('?')[0].rstrip('/')
                    if clean_link in seen_links:
                        continue

                    corpus = f"{item['title']} {item['description']}"
                    rel = evaluate_relevance(corpus)
                    if not rel["is_relevant"]:
                        continue

                    seen_links.add(clean_link)
                    matches += 1

                    category = self._classify_topic(item['title'], item['description'])

                    all_articles.append({
                        "source": feed['name'],
                        "tier": feed['tier'],
                        "category": category,
                        "title": item['title'],
                        "author": item['author'] or feed['name'],
                        "pub_date": item['pub_date'][:16] if item['pub_date'] else "Recent",
                        "description": item['description'],
                        "url": item['link'],
                        "classification": rel["classification"],
                        "is_golden_dome": rel["is_golden_dome"],
                        "is_space": rel["is_space"],
                        "related_coverage": [],
                        "ingested_at": datetime.now(timezone.utc).isoformat()
                    })

                    if matches >= limit_per_feed:
                        break

            except Exception as e:
                logging.error(f"Error reading {feed['name']}: {e}")

        clustered_articles = self._cluster_related_reporting(all_articles)
        logging.info(f"Captured {len(clustered_articles)} categorized & clustered news stories.")
        return clustered_articles
