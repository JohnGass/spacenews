import re
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from scrapers.filter_rules import evaluate_relevance

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class DefenseGovScraper:
    BASE_URL = "https://www.defense.gov"
    LISTING_URL = "https://www.defense.gov/News/Contracts/"

    def _fetch_html_with_browser(self, url: str) -> Optional[str]:
        """Launches headless Chromium to bypass Akamai/WAF anti-bot protections."""
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox"]
                )
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800}
                )
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2500)
                html = page.content()
                browser.close()
                return html
        except Exception as e:
            logging.error(f"Playwright navigation failed for {url}: {e}")
            return None

    def fetch_recent_contract_urls(self, limit: int = 5) -> List[str]:
        """Identifies the last N daily contract announcement links."""
        logging.info("Polling Defense.gov Contracts index...")
        html = self._fetch_html_with_browser(self.LISTING_URL)
        if not html:
            logging.error("Failed to retrieve contract listing HTML.")
            return []

        soup = BeautifulSoup(html, "html.parser")
        urls = []
        for link in soup.find_all("a", href=True):
            href = link["href"].strip()
            # Match release articles case-insensitively
            if "/article/" in href.lower() and "contract" in href.lower():
                full_url = href if href.startswith("http") else f"{self.BASE_URL}{href}"
                if full_url not in urls:
                    urls.append(full_url)
                    logging.info(f"Discovered Release Link: {full_url}")
                if len(urls) >= limit:
                    break

        logging.info(f"Identified {len(urls)} recent contract release URLs.")
        return urls

    def parse_contract_article(self, article_url: str) -> List[Dict[str, Any]]:
        """Extracts and filters contract paragraphs recursively."""
        logging.info(f"Scanning contract release: {article_url}")
        html = self._fetch_html_with_browser(article_url)
        if not html:
            logging.error(f"Failed to retrieve article: {article_url}")
            return []

        soup = BeautifulSoup(html, "html.parser")
        
        # Pull page title/date
        page_title = soup.title.string.strip() if soup.title else article_url
        logging.info(f"Article Heading: {page_title}")

        current_branch = "UNKNOWN"
        relevant_contracts = []
        
        dollar_pattern = re.compile(r"\$([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?(?:\s+(?:million|billion))?)", re.IGNORECASE)
        contractor_pattern = re.compile(r"^([^,]+),\s*([^,]+),\s*([^,\.]+)")
        activity_pattern = re.compile(r"The\s+contracting\s+activity\s+is\s+([^,\.\(]+)", re.IGNORECASE)

        # RECURSIVE SEARCH: Finds all headings and paragraphs regardless of nesting
        elements = soup.find_all(["h2", "h3", "h4", "p"])
        logging.info(f"Evaluating {len(elements)} structural elements on page...")

        for elem in elements:
            text = elem.get_text().strip()
            
            # Service branch header check (e.g., 'AIR FORCE', 'MISSILE DEFENSE AGENCY')
            if text.isupper() and len(text) < 40 and not text.startswith("$"):
                current_branch = text
                continue

            if elem.name == "p":
                if len(text) < 70:
                    continue

                relevance = evaluate_relevance(text)
                if not relevance["is_relevant"]:
                    continue

                logging.info(f"MATCH FOUND [{relevance['classification']}]: {text[:90]}...")

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
        """Aggregates and deduplicates contracts across recent releases."""
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
