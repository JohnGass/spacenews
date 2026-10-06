import re
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import requests
from bs4 import BeautifulSoup
from scrapers.filter_rules import evaluate_relevance

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class DefenseGovScraper:
    BASE_URL = "https://www.defense.gov"
    LISTING_URL = "https://www.defense.gov/News/Contracts/"

    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    def fetch_latest_contract_url(self) -> Optional[str]:
        logging.info("Polling Defense.gov Contracts index...")
        resp = requests.get(self.LISTING_URL, headers=self.headers, timeout=15)
        if resp.status_code != 200:
            logging.error(f"Failed to fetch contract listing: HTTP {resp.status_code}")
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if "/News/Contracts/Contract/Article/" in href:
                return href if href.startswith("http") else f"{self.BASE_URL}{href}"
        return None

    def parse_contract_article(self, article_url: str) -> List[Dict[str, Any]]:
        logging.info(f"Ingesting daily contracts from: {article_url}")
        resp = requests.get(article_url, headers=self.headers, timeout=15)
        if resp.status_code != 200:
            logging.error(f"Failed to retrieve article: {article_url}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
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
