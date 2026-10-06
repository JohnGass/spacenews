import re
import os
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from scrapers.filter_rules import evaluate_relevance

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class DefenseGovScraper:
    """
    Ingests DoD contracts by leveraging the official ArticleCS RSS feed for link
    discovery and direct HTTP requests (with Playwright fallback) for parsing.
    """
    BASE_URL = "https://www.defense.gov"
    RSS_FEED_URL = "https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=400&Site=945&max=10"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })

    def fetch_recent_contract_urls(self, limit: int = 5) -> List[str]:
        """Discovers recent daily contract releases directly from the DoD RSS feed."""
        logging.info("Fetching DoD Contracts RSS feed...")
        discovered = []

        try:
            resp = self.session.get(self.RSS_FEED_URL, timeout=20)
            if resp.status_code == 200:
                root = ET.fromstring(resp.content)
                for item in root.findall(".//item"):
                    link = item.find("link")
                    if link is not None and link.text:
                        raw_url = link.text.strip()
                        clean_url = re.sub(r"https?://(www\.)?war\.gov", "https://www.defense.gov", raw_url)
                        if clean_url not in discovered and "/Article/" in clean_url:
                            discovered.append(clean_url)
                            print(f"[RSS Discovered] {clean_url}", flush=True)
            else:
                logging.error(f"RSS feed returned HTTP {resp.status_code}")
        except Exception as e:
            logging.error(f"Error reading DoD RSS feed: {e}")

        logging.info(f"Identified {len(discovered)} contract release URLs.")
        return discovered[:limit]

    def _fetch_article_html(self, url: str) -> Optional[str]:
        """Fetches article HTML directly; falls back to Playwright if challenged."""
        try:
            print(f"--> Requesting: {url}", flush=True)
            resp = self.session.get(url, timeout=20, allow_redirects=True)
            if resp.status_code == 200 and "Just a moment" not in resp.text:
                return resp.text
            print(f"[WARN] Direct fetch returned HTTP {resp.status_code}. Attempting Playwright...", flush=True)
        except Exception as e:
            print(f"[WARN] Direct request failed ({e}). Attempting Playwright...", flush=True)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox"]
                )
                page = browser.new_page(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                )
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2000)
                html = page.content()
                browser.close()
                return html
        except Exception as e:
            logging.error(f"Playwright fallback failed for {url}: {e}")
            return None

    def parse_contract_article(self, article_url: str) -> List[Dict[str, Any]]:
        """Parses individual contract paragraphs from an article page."""
        print(f"\n--- Ingesting Contracts: {article_url} ---", flush=True)
        html = self._fetch_article_html(article_url)
        if not html:
            logging.warning(f"Could not retrieve HTML for {article_url}")
            return []

        soup = BeautifulSoup(html, "html.parser")
        current_branch = "UNKNOWN"
        relevant_contracts = []

        dollar_pattern = re.compile(
            r"\$([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?(?:\s+(?:million|billion))?)",
            re.IGNORECASE
        )
        contractor_pattern = re.compile(r"^([^,]+),\s*([^,]+),\s*([^,\.]+)")
        activity_pattern = re.compile(r"The\s+contracting\s+activity\s+is\s+([^,\.\(]+)", re.IGNORECASE)

        elements = soup.find_all(["h2", "h3", "h4", "p"])
        print(f"Evaluating {len(elements)} HTML elements...", flush=True)

        for elem in elements:
            text = elem.get_text().strip()

            if text.isupper() and len(text) < 40 and not text.startswith("$"):
                current_branch = text
                continue

            if elem.name == "p":
                if len(text) < 70:
                    continue

                relevance = evaluate_relevance(text)
                if not relevance["is_relevant"]:
                    continue

                print(f">>> MATCH [{relevance['classification']}]: {text[:95]}...", flush=True)

                dollar_match = dollar_pattern.search(text)
                awarded_amount = f"${dollar_match.group(1)}" if dollar_match else "Unspecified"

                contractor_match = contractor_pattern.match(text)
                contractor = contractor_match.group(1).strip() if contractor_match else "Unknown Contractor"

                activity_match = activity_pattern.search(text)
                contracting_activity = activity_match.group(1).strip() if activity_match else current_branch

                relevant_contracts.append({
                    "source": "Defense.gov Contracts",
                    "article_url": article_url,
                    "branch_section": current_branch,
                    "contractor": contractor,
                    "award_amount": awarded_amount,
                    "contracting_activity": contracting_activity,
                    "classification": relevance["classification"],
                    "is_golden_dome": relevance["is_golden_dome"],
                    "is_space": relevance["is_space"],
                    "raw_text": text,
                    "ingested_at": datetime.now(timezone.utc).isoformat()
                })

        print(f"Captured {len(relevant_contracts)} relevant contracts from this release.", flush=True)
        return relevant_contracts

    def scrape_recent_releases(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Scrapes across the last N releases and deduplicates findings."""
        target_urls = self.fetch_recent_contract_urls(limit=limit)
        all_contracts = []
        seen_keys = set()

        for url in target_urls:
            awards = self.parse_contract_article(url)
            for award in awards:
                dedup_key = f"{award['contractor']}_{award['award_amount']}"
                if dedup_key not in seen_keys:
                    seen_keys.add(dedup_key)
                    all_contracts.append(award)

        return all_contracts
