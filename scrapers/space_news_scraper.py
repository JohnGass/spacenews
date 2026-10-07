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
    Multi-tier Space Intelligence Ingestion Engine.
    Aggregates analytical essays, launch operations, defense policy,
    and commercial space venture reporting.
    """
    FEEDS = [
        # --- TIER 1: Analytical Deep Dives & Doctrine ---
        {
            "name": "The Space Review",
            "url": "https://www.thespacereview.com/feed.xml",
            "tier": "Strategic Analysis",
            "category": "Doctrine & Long-form"
        },
        # --- TIER 2: Launch Operations & Technical Investigative ---
        {
            "name": "Ars Technica Space",
            "url": "https://arstechnica.com/space/feed/",
            "tier": "Launch & Hardware",
            "category": "Investigative Technical"
        },
        {
            "name": "Spaceflight Now",
            "url": "https://spaceflightnow.com/feed/",
            "tier": "Launch & Hardware",
            "category": "Mission Operations"
        },
        # --- TIER 3: National Security, Pentagon & Policy ---
        {
            "name": "Breaking Defense",
            "url": "https://breakingdefense.com/category/space/feed/",
            "tier": "National Security Space",
            "category": "Defense Acquisition & Warfighting"
        },
        {
            "name": "Air & Space Forces",
            "url": "https://www.airandspaceforces.com/category/space/feed/",
            "tier": "National Security Space",
            "category": "USSF Force Design & Requirements"
        },
        {
            "name": "SpacePolicyOnline",
            "url": "https://spacepolicyonline.com/feed/",
            "tier": "Policy & Hill",
            "category": "Congressional Budget & Civil Space"
        },
        # --- TIER 4: Commercial Space & Dual-Use Ventures ---
        {
            "name": "SpaceNews",
            "url": "https://spacenews.com/feed/",
            "tier": "Commercial & Defense",
            "category": "Global Space Industry"
        },
        {
            "name": "Payload Space",
            "url": "https://payloadspace.com/feed/",
            "tier": "Commercial & Defense",
            "category": "Space Economy & Venture"
        },
        # --- TIER 5: Agency & Exploration Direct ---
        {
            "name": "NASA News",
            "url": "https://www.nasa.gov/news-release/feed/",
            "tier": "Civil & Agency",
            "category": "NASA Exploration & Contracts"
        }
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
                        "description": self._clean_text(desc)[:280]
                    })
        except Exception:
            # Fallback regex extraction for feeds with XML namespace discrepancies
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
                        "description": desc[:280]
                    })
        return items

    def scrape_all_feeds(self, limit_per_feed: int = 6) -> List[Dict[str, Any]]:
        logging.info(f"Ingesting space intelligence across {len(self.FEEDS)} premier industry publications...")
        all_articles = []
        seen_links: Set[str] = set()

        for feed in self.FEEDS:
            logging.info(f"Polling {feed['name']} ({feed['tier']})...")
            try:
                resp = self.session.get(feed['url'], timeout=18)
                if resp.status_code != 200:
                    logging.warning(f"{feed['name']} returned HTTP {resp.status_code}")
                    continue

                raw_items = self._parse_items(resp.text)
                feed_matches = 0

                for item in raw_items:
                    clean_link = item['link'].split('?')[0].rstrip('/')
                    if clean_link in seen_links:
                        continue

                    corpus = f"{item['title']} {item['description']}"
                    rel = evaluate_relevance(corpus)
                    if not rel["is_relevant"]:
                        continue

                    seen_links.add(clean_link)
                    feed_matches += 1

                    all_articles.append({
                        "source": feed['name'],
                        "tier": feed['tier'],
                        "outlet_category": feed['category'],
                        "title": item['title'],
                        "author": item['author'] or feed['name'],
                        "pub_date": item['pub_date'][:16] if item['pub_date'] else "Recent",
                        "description": item['description'],
                        "url": item['link'],
                        "classification": rel["classification"],
                        "is_golden_dome": rel["is_golden_dome"],
                        "is_space": rel["is_space"],
                        "ingested_at": datetime.now(timezone.utc).isoformat()
                    })

                    if feed_matches >= limit_per_feed:
                        break

                logging.info(f"Captured {feed_matches} relevant articles from {feed['name']}.")
            except Exception as e:
                logging.error(f"Error fetching {feed['name']}: {e}")

        logging.info(f"Total verified space industry articles ingested: {len(all_articles)}")
        return all_articles
