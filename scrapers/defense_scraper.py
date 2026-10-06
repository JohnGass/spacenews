import re
import os
import sys
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import xml.etree.ElementTree as ET
import requests
from scrapers.filter_rules import evaluate_relevance

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def log_terminal(title: str, content: str):
    """Prints highlighted diagnostic output to GitHub Actions terminal."""
    border = "=" * 70
    print(f"\n{border}\n[DIAGNOSTIC] {title}\n{border}\n{content}\n{border}\n", flush=True)

class DefenseGovScraper:
    """
    Ingests DoD contracts with terminal diagnostic output.
    Attempts official RSS feed first, then falls back to proxied web index.
    """
    BASE_URL = "https://www.defense.gov"
    # Official DoD ArticleCS RSS Feed for Daily Contracts (ContentType 400)
    RSS_FEED_URL = "https://www.defense.gov/DesktopModules/ArticleCS/RSS.ashx?ContentType=400&Site=945&max=10"
    WEB_INDEX_URL = "https://www.defense.gov/News/Contracts/"
    PROXY_PREFIX = "https://r.jina.ai/"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        })

    def _fetch_diagnostic(self, url: str, is_proxied: bool = False) -> tuple[int, str]:
        """Fetches URL, prints diagnostic metrics, and returns (status_code, body)."""
        target = f"{self.PROXY_PREFIX}{url}" if is_proxied else url
        print(f"--> Fetching: {target} (proxied={is_proxied})", flush=True)
        try:
            resp = self.session.get(target, timeout=25)
            status = resp.status_code
            text = resp.text
            
            # Print diagnostic snapshot to terminal
            preview = text[:800] if text else "[EMPTY BODY]"
            log_terminal(
                f"HTTP {status} from {target[:55]}...",
                f"Status: {status}\n"
                f"Bytes Received: {len(text)}\n"
                f"Headers: {dict(list(resp.headers.items())[:5])}\n\n"
                f"--- BODY PREVIEW (First 800 chars) ---\n{preview}"
            )
            return status, text
        except Exception as e:
            log_terminal(f"CONNECTION ERROR: {target}", str(e))
            return 0, ""

    def fetch_recent_contract_urls(self, limit: int = 5) -> List[str]:
        """
        Attempts link discovery across two independent paths:
        1. Official Contracts RSS Feed (Direct & Proxied)
        2. Contracts Web Index via Proxy
        """
        discovered = []

        # ==============================================================
        # ATTEMPT 1: Official DoD Contracts RSS Feed
        # ==============================================================
        print("\n[STEP 1] Testing Official DoD Contracts RSS Feed...", flush=True)
        status, content = self._fetch_diagnostic(self.RSS_FEED_URL, is_proxied=False)
        
        # If direct RSS is blocked by Akamai, try RSS via proxy
        if status != 200 or "<rss" not in content.lower():
            print("\n[STEP 1b] Direct RSS blocked. Testing Proxied RSS...", flush=True)
            status, content = self._fetch_diagnostic(self.RSS_FEED_URL, is_proxied=True)

        if status == 200 and ("<item" in content or "<rss" in content.lower()):
            try:
                root = ET.fromstring(content)
                for item in root.findall(".//item"):
                    link = item.find("link")
                    if link is not None and link.text:
                        clean = link.text.strip()
                        if clean not in discovered:
                            discovered.append(clean)
                            print(f"[RSS Found] {clean}", flush=True)
            except Exception as e:
                print(f"[WARN] XML parsing failed, extracting with regex: {e}", flush=True)
                # Regex fallback for RSS items
                for match in re.findall(r"<link>(https?://[^<]+)</link>", content):
                    if "/Article/" in match and match not in discovered:
                        discovered.append(match)
                        print(f"[RSS Regex Found] {match}", flush=True)

        if discovered:
            print(f"[SUCCESS] Discovered {len(discovered)} releases via RSS.", flush=True)
            return discovered[:limit]

        # ==============================================================
        # ATTEMPT 2: Web Listing Index via Proxy
        # ==============================================================
        print("\n[STEP 2] RSS empty or blocked. Testing Web Index via Proxy...", flush=True)
        status, content = self._fetch_diagnostic(self.WEB_INDEX_URL, is_proxied=True)

        if status == 200 and content:
            # Broad regex: catches both absolute and relative contract article links
            patterns = [
                r"https://www\.defense\.gov/News/Contracts/Contract/Article/[0-9]+/[a-zA-Z0-9\-_]+",
                r"/News/Contracts/Contract/Article/[0-9]+/[a-zA-Z0-9\-_]+",
                r"https://www\.defense\.gov/News/Contracts/Contract/Article/[0-9]+/?",
                r"/News/Contracts/Contract/Article/[0-9]+/?"
            ]

            for pattern in patterns:
                for match in re.findall(pattern, content, re.IGNORECASE):
                    full = match if match.startswith("http") else f"{self.BASE_URL}{match}"
                    full = full.rstrip("/").split("?")[0]
                    if full not in discovered:
                        discovered.append(full)
                        print(f"[Web Link Found] {full}", flush=True)
                    if len(discovered) >= limit:
                        break

        print(f"\n[SUMMARY] Total release URLs identified: {len(discovered)}", flush=True)
        return discovered[:limit]

    def parse_contract_article(self, article_url: str) -> List[Dict[str, Any]]:
        """Parses individual contract paragraphs from a release."""
        print(f"\n--- Parsing Release Article: {article_url} ---", flush=True)
        
        # Ingest via proxy to avoid Akamai 403 blocks on article pages
        status, content = self._fetch_diagnostic(article_url, is_proxied=True)
        if status != 200 or not content:
            print(f"[WARN] Failed to load article content for {article_url}", flush=True)
            return []

        paragraphs = content.split("\n\n")
        print(f"Total paragraph blocks to evaluate: {len(paragraphs)}", flush=True)

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
            clean_header = text.lstrip("#* ").strip()

            if clean_header.isupper() and len(clean_header) < 40 and not clean_header.startswith("$"):
                current_branch = clean_header
                continue

            if len(text) < 70:
                continue

            relevance = evaluate_relevance(text)
            if not relevance["is_relevant"]:
                continue

            print(f"\n>>> MATCH [{relevance['classification']}]: {text[:100]}...", flush=True)

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

        print(f"Extracted {len(relevant_contracts)} contracts from {article_url}", flush=True)
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
