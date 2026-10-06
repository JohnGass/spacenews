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
    Ingests DoD contracts by discovering releases via the ArticleCS RSS feed
    and fetching content through whitelisted print endpoints and edge relays
    to bypass datacenter IP bans.
    """
    BASE_URL = "https://www.defense.gov"
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
        """
        Fetches contract HTML through a multi-route fallback to circumvent Akamai blocks:
        Route 1: DesktopModules Print Endpoint (whitelisted path)
        Route 2: Public edge relays (AllOrigins / CodeTabs)
        Route 3: Playwright with automation flags stripped
        """
        # Extract the Article ID from the URL (e.g. .../Article/4619270/...)
        id_match = re.search(r"/Article/(\d+)/", url)
        article_id = id_match.group(1) if id_match else None

        # Route 1: Official DoD Print Endpoint (lives under whitelisted DesktopModules)
        if article_id:
            print_url = f"https://www.defense.gov/DesktopModules/ArticleCS/Print.aspx?ArticleId={article_id}"
            try:
                print(f"--> Trying DoD Print Endpoint: {print_url}", flush=True)
                resp = self.session.get(print_url, timeout=15)
                if resp.status_code == 200 and "Access Denied" not in resp.text and len(resp.text) > 3000:
                    print(f"[SUCCESS] Loaded {len(resp.text)} bytes via DoD Print Endpoint.", flush=True)
                    return resp.text
            except Exception as e:
                print(f"[INFO] Print endpoint unavailable: {e}", flush=True)

        # Route 2: Public Edge Proxies
        encoded_url = requests.utils.quote(url)
        proxies = [
            f"https://api.allorigins.win/raw?url={encoded_url}",
            f"https://api.codetabs.com/v1/proxy?quest={encoded_url}"
        ]

        for p_url in proxies:
            try:
                print(f"--> Trying Edge Relay: {p_url[:55]}...", flush=True)
                resp = requests.get(p_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
                if resp.status_code == 200 and "Access Denied" not in resp.text and len(resp.text) > 3000:
                    print(f"[SUCCESS] Loaded {len(resp.text)} bytes via Edge Relay.", flush=True)
                    return resp.text
            except Exception as e:
                print(f"[INFO] Edge relay skipped: {e}", flush=True)

        # Route 3: Stealth Playwright
        print("--> Fallback: Launching Playwright Chromium with stealth flags...", flush=True)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-blink-features=AutomationControlled"
                    ]
                )
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                )
                context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)
                content = page.content()
                browser.close()

                if "Access Denied" not in content and len(content) > 3000:
                    print(f"[SUCCESS] Loaded {len(content)} bytes via Playwright.", flush=True)
                    return content
                print("[WARN] Playwright returned Access Denied.", flush=True)
        except Exception as e:
            logging.error(f"Playwright fallback failed: {e}")

        return None

    def parse_contract_article(self, article_url: str) -> List[Dict[str, Any]]:
        """Parses individual contract paragraphs from an article page."""
        print(f"\n--- Ingesting Contracts: {article_url} ---", flush=True)
        html = self._fetch_article_html(article_url)
        if not html:
            logging.warning(f"Could not retrieve readable HTML for {article_url}")
            return []

        soup = BeautifulSoup(html, "html.parser")
        page_title = soup.title.string.strip() if soup.title else "No Title"
        print(f"Loaded Page: '{page_title}' ({len(html)} bytes)", flush=True)

        # Extract paragraphs via <p> tags first
        paragraphs = []
        for p in soup.find_all("p"):
            txt = p.get_text().strip()
            if len(txt) > 70:
                paragraphs.append(txt)

        # If <p> tags are absent (e.g. plain text or <br> formatting), split by double newline
        if len(paragraphs) < 3:
            body = soup.find("div", class_="body") or soup.find("main") or soup.body or soup
            paragraphs = [b.strip() for b in body.get_text("\n\n").split("\n\n") if len(b.strip()) > 70]

        print(f"Extracted {len(paragraphs)} paragraph blocks to evaluate...", flush=True)

        current_branch = "UNKNOWN"
        relevant_contracts = []

        dollar_pattern = re.compile(
            r"\$([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?(?:\s+(?:million|billion))?)",
            re.IGNORECASE
        )
        contractor_pattern = re.compile(r"^([^,]+),\s*([^,]+),\s*([^,\.]+)")
        activity_pattern = re.compile(r"The\s+contracting\s+activity\s+is\s+([^,\.\(]+)", re.IGNORECASE)

        for text in paragraphs:
            # Check for service branch header (e.g. 'AIR FORCE', 'MISSILE DEFENSE AGENCY')
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
