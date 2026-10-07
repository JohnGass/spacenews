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
    Ingests editorial reporting, policy analysis, and breaking defense space news from:
    1. SpaceNews (spacenews.com)
    2. Breaking Defense - Space (breakingdefense.com)
    3. Air & Space Forces Magazine - Space (airandspaceforces.com)
    4. SpacePolicyOnline (spacepolicyonline.com)
    5. Payload Space (payloadspace.com)
    """
    FEEDS = [
        {
            "name": "SpaceNews",
            "url": "https://spacenews.com/feed/",
            "category": "Commercial & Defense Space"
        },
        {
            "name": "Breaking Defense",
            "url": "https://breakingdefense.com/category/space/feed/",
            "category": "National Security Space"
        },
        {
            "name": "Air & Space Forces",
            "url": "https://www.airandspaceforces.com/category/space/feed/",
            "category": "USSF & Airpower"
        },
        {
            "name": "SpacePolicyOnline",
            "url": "https://spacepolicyonline.com/feed/",
            "category": "Civil, Defense & Budget Policy"
        },
        {
            "name": "Payload Space",
            "url": "https://payloadspace.com/feed/",
            "category": "Commercial Space & Defense"
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

    def _parse_xml_items(self, content: str) -> List[dict]:
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
            # Fallback regex parser for feeds with XML namespace or encoding quirks
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

    def scrape_all_feeds(self, limit_per_feed: int = 8) -> List[Dict[str, Any]]:
        logging.info("Ingesting top space and defense trade publications...")
        all_articles = []
        seen_links: Set[str] = set()

        for feed in self.FEEDS:
            logging.info(f"Polling {feed['name']} ({feed['url']})...")
            try:
                resp = self.session.get(feed['url'], timeout=15)
                if resp.status_code != 200:
                    logging.warning(f"{feed['name']} returned HTTP {resp.status_code}")
                    continue

                raw_items = self._parse_xml_items(resp.text)
                feed_matches = 0

                for item in raw_items:
                    clean_link = item['link'].split('?')[0].rstrip('/')
                    if clean_link in seen_links:
                        continue

                    # Filter for space/defense relevance
                    corpus = f"{item['title']} {item['description']}"
                    rel = evaluate_relevance(corpus)
                    if not rel["is_relevant"]:
                        continue

                    seen_links.add(clean_link)
                    feed_matches += 1

                    all_articles.append({
                        "source": feed['name'],
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

        logging.info(f"Total space industry articles ingested: {len(all_articles)}")
        return all_articles
