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
        """Launches headless Chromium to bypass Akamai/WAF blocks."""
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
                page.wait_for_timeout(2000)
                html = page.content()
                browser.close()
                return html
        except Exception as e:
            logging.error(f"Playwright navigation failed for {url}: {e}")
            return None

    def fetch_recent_contract_urls(self, limit: int = 5) -> List[str]:
        """Collects URLs for the last N daily contract releases."""
        logging.info(f"Polling Defense.gov Contracts index for the last {limit} releases...")
        html = self._fetch_html_with_browser(self.LISTING_URL)
        if not html:
            logging.error("Failed to retrieve contract listing HTML.")
            return []

        soup = BeautifulSoup(html, "html.parser")
        urls = []
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if "/News/Contracts/Contract/Article/" in href:
                full_url = href if href.startswith("http") else f"{self.BASE_URL}{href}"
                if full_url not in urls:
                    urls.append(full_url)
                if len(urls) >= limit:
                    break

        logging.info(f"Identified {len(urls)} recent contract release URLs.")
        return urls

    def parse_contract_article(self, article_url: str) -> List[Dict[str, Any]]:
        """Parses individual contract paragraphs from a specific release page."""
        logging.info(f"Scanning contract release: {article_url}")
        html = self._fetch_html_with_browser(article_url)
        if not html:
            logging.error(f"Failed to retrieve article: {article_url}")
            return []

        soup = BeautifulSoup(html, "html.parser")
        body = soup.find("div", class_="body") or soup.find("main") or soup

        current_branch = "UNKNOWN"
        relevant_contracts = []
        
        dollar_pattern = re.compile(r"\$([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?(?:\s+(?:million|billion))?)", re.IGNORECASE)
        contractor_pattern = re.compile(r"^([^,]+),\s*([^,]+),\s*([^,\.]+)")
        activity_pattern = re.compile(r"The\s+contracting\s+activity\s+is\s+([^,\.\(]+)", re.IGNORECASE)

        for elem in body.children:
            if elem.name in ["h2", "h3", "h4", "p"] and elem.get_text().isupper() and len(elem.get_text().strip()) < 50:
                current_branch = elem.get_text().strip()
                continue

            if elem.name == "p":
                paragraph = elem.get_text().strip()
                if len(paragraph) < 80:
                    continue

                relevance = evaluate_relevance(paragraph)
                if not relevance["is_relevant"]:
                    continue

                dollar_match = dollar_pattern.search(paragraph)
                awarded_amount = f"${dollar_match.group(1)}" if dollar_match else "Unspecified"

                contractor_match = contractor_pattern.match(paragraph)
                contractor = contractor_match.group(1).strip() if contractor_match else "Unknown Contractor"

                activity_match = activity_pattern.search(paragraph)
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
                    "raw_text": paragraph,
                    "ingested_at": datetime.now(timezone.utc).isoformat()
                })

        return relevant_contracts

    def scrape_recent_releases(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Scrapes across the last N releases and deduplicates findings."""
        target_urls = self.fetch_recent_contract_urls(limit=limit)
        all_contracts = []
        seen_texts = set()

        for url in target_urls:
            awards = self.parse_contract_article(url)
            for award in awards:
                # Deduplicate by prime contractor + award amount snippet
                dedup_key = f"{award['contractor']}_{award['award_amount']}"
                if dedup_key not in seen_texts:
                    seen_texts.add(dedup_key)
                    all_contracts.append(award)

        return all_contracts
