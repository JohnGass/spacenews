import re
import os
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any
import requests
from scrapers.filter_rules import evaluate_relevance

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class DefenseGovScraper:
    """
    Ingests DoD contracts by routing requests through Jina Reader (https://r.jina.ai/)
    to bypass Akamai data center IP blocks on GitHub Actions runners.
    """
    PROXY_PREFIX = "https://r.jina.ai/"
    TARGET_INDEX_URL = "https://www.defense.gov/News/Contracts/"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "SpaceIntelPipeline/1.0",
            "Accept": "text/plain"
        })

    def _fetch_markdown(self, target_url: str) -> str:
        """Proxies URL through Jina Reader and returns clean markdown text."""
        proxy_url = f"{self.PROXY_PREFIX}{target_url}"
        try:
            resp = self.session.get(proxy_url, timeout=30)
            if resp.status_code == 200:
                return resp.text
            logging.error(f"Failed to fetch {proxy_url}: HTTP {resp.status_code}")
            return ""
        except Exception as e:
            logging.error(f"Error requesting {proxy_url}: {e}")
            return ""

    def fetch_recent_contract_urls(self, limit: int = 5) -> List[str]:
        """Identifies recent contract release URLs from the listing index."""
        logging.info("Polling Defense.gov Contracts index via proxy...")
        md_content = self._fetch_markdown(self.TARGET_INDEX_URL)
        if not md_content:
            logging.error("Empty response from contracts index.")
            return []

        # Find all Defense.gov contract article URLs in the markdown text
        article_pattern = re.compile(
            r"https://www\.defense\.gov/News/Contracts/Contract/Article/[0-9]+/[^/\)\s]+",
            re.IGNORECASE
        )
        
        discovered_urls = []
        for match in article_pattern.finditer(md_content):
            url = match.group(0).rstrip(")")
            if url not in discovered_urls:
                discovered_urls.append(url)
                logging.info(f"Discovered Release Link: {url}")
            if len(discovered_urls) >= limit:
                break

        logging.info(f"Identified {len(discovered_urls)} recent contract release URLs.")
        return discovered_urls

    def parse_contract_article(self, article_url: str) -> List[Dict[str, Any]]:
        """Parses individual contract paragraphs from a release markdown."""
        logging.info(f"Scanning contract release: {article_url}")
        md_text = self._fetch_markdown(article_url)
        if not md_text:
            return []

        # Split into distinct paragraphs
        paragraphs = md_text.split("\n\n")
        logging.info(f"Evaluating {len(paragraphs)} paragraph blocks in release...")

        current_branch = "UNKNOWN"
        relevant_contracts = []

        dollar_pattern = re.compile(
            r"\$([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?(?:\s+(?:million|billion))?)",
            re.IGNORECASE
        )
        contractor_pattern = re.compile(r"^([^,]+),\s*([^,]+),\s*([^,\.]+)")
        activity_pattern = re.compile(r"The\s+contracting\s+activity\s+is\s+([^,\.\(]+)", re.IGNORECASE)

        for p in paragraphs:
            text = p.strip().replace("\n", " ")
            
            # Identify Branch Headers (e.g., '### AIR FORCE', 'MISSILE DEFENSE AGENCY')
            clean_header = text.lstrip("#").strip()
            if clean_header.isupper() and len(clean_header) < 40 and not clean_header.startswith("$"):
                current_branch = clean_header
                continue

            if len(text) < 80:
                continue

            # Run through the Space / Golden Dome relevance filter
            relevance = evaluate_relevance(text)
            if not relevance["is_relevant"]:
                continue

            logging.info(f"MATCH [{relevance['classification']}]: {text[:80]}...")

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

        logging.info(f"Extracted {len(relevant_contracts)} space/Golden Dome contracts from this release.")
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
