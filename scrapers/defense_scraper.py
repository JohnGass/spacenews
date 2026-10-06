import re
import os
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup
from scrapers.filter_rules import evaluate_relevance

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class DefenseGovScraper:
    """
    Ingests DoD contracts by discovering releases via the ArticleCS RSS feed
    and retrieving content via the whitelisted DesktopModules Print endpoint.
    """
    RSS_FEED_URL = "https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=400&Site=945&max=10"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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
                        if "/Article/" in raw_url and raw_url not in discovered:
                            discovered.append(raw_url)
                            print(f"[RSS Discovered] {raw_url}", flush=True)
            else:
                logging.error(f"RSS feed returned HTTP {resp.status_code}")
        except Exception as e:
            logging.error(f"Error reading DoD RSS feed: {e}")

        logging.info(f"Identified {len(discovered)} contract release URLs.")
        return discovered[:limit]

    def _fetch_article_html(self, article_url: str) -> Optional[str]:
        """
        Retrieves full article text via DotNetNuke ArticleCS Print endpoints,
        which are allowed through Akamai's path filtering.
        """
        # Extract numerical article ID (e.g., 4619270 from /Article/4619270/...)
        id_match = re.search(r"/Article/(\d+)/", article_url)
        if not id_match:
            print(f"[WARN] No Article ID found in URL: {article_url}", flush=True)
            return None

        article_id = id_match.group(1)

        # DotNetNuke ArticleCS Print parameter variations
        candidate_endpoints = [
            f"https://www.defense.gov/DesktopModules/ArticleCS/Print.aspx?PortalId=1&ModuleId=764&Article={article_id}",
            f"https://www.war.gov/DesktopModules/ArticleCS/Print.aspx?PortalId=1&ModuleId=764&Article={article_id}",
            f"https://www.defense.gov/DesktopModules/ArticleCS/Print.aspx?PortalId=1&Article={article_id}",
            f"https://www.war.gov/DesktopModules/ArticleCS/Print.aspx?PortalId=1&Article={article_id}",
            f"https://www.defense.gov/DesktopModules/ArticleCS/Print.aspx?Article={article_id}"
        ]

        for endpoint in candidate_endpoints:
            try:
                print(f"--> Requesting print endpoint: {endpoint}", flush=True)
                resp = self.session.get(endpoint, timeout=20)
                status = resp.status_code
                content_len = len(resp.text)
                
                print(f"    Response: HTTP {status} | Bytes: {content_len}", flush=True)

                if status == 200 and content_len > 2500 and "Access Denied" not in resp.text:
                    print(f"[SUCCESS] Article body loaded ({content_len} bytes).", flush=True)
                    return resp.text
            except Exception as e:
                print(f"    Failed: {e}", flush=True)

        return None

    def parse_contract_article(self, article_url: str) -> List[Dict[str, Any]]:
        """Parses individual contract paragraphs from an article page."""
        print(f"\n--- Ingesting Contracts: {article_url} ---", flush=True)
        html = self._fetch_article_html(article_url)
        if not html:
            logging.warning(f"Could not retrieve readable HTML for {article_url}")
            return []

        soup = BeautifulSoup(html, "html.parser")
        
        # Collect paragraphs from standard tags or double newlines
        paragraphs = []
        for p in soup.find_all(["p", "div"]):
            txt = p.get_text().strip()
            if len(txt) > 75 and txt not in paragraphs:
                paragraphs.append(txt)

        if len(paragraphs) < 3:
            body_text = soup.get_text("\n\n")
            paragraphs = [b.strip() for b in body_text.split("\n\n") if len(b.strip()) > 75]

        print(f"Evaluating {len(paragraphs)} paragraph blocks...", flush=True)

        current_branch = "UNKNOWN"
        relevant_contracts = []

        dollar_pattern = re.compile(
            r"\$([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?(?:\s+(?:million|billion))?)",
            re.IGNORECASE
        )
        contractor_pattern = re.compile(r"^([^,]+),\s*([^,]+),\s*([^,\.]+)")
        activity_pattern = re.compile(r"The\s+contracting\s+activity\s+is\s+([^,\.\(]+)", re.IGNORECASE)

        for text in paragraphs:
            # Check for branch headers (e.g. 'AIR FORCE', 'MISSILE DEFENSE AGENCY')
            clean_hdr = text.lstrip("#* -").strip()
            if clean_hdr.isupper() and len(clean_hdr) < 40 and not clean_hdr.startswith("$"):
                current_branch = clean_hdr
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
        """Scrapes across recent releases and deduplicates findings."""
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
