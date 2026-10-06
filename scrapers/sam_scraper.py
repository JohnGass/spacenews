import os
import re
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup
from scrapers.filter_rules import evaluate_relevance

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class PreAwardScraper:
    """
    Ingests pre-award signals:
    1. SAM.gov Opportunities API (Soliciations, Sources Sought, Presolicitations)
    2. Defense Innovation Unit (DIU) Open Commercial Solutions Openings (CSOs)
    """
    SAM_API_URL = "https://api.sam.gov/opportunities/v2/search"
    DIU_OPEN_URL = "https://www.diu.mil/work-with-us/open-solicitations"

    def __init__(self):
        self.sam_api_key = os.getenv("SAM_GOV_API_KEY")
        self.scraper_api_key = os.getenv("SCRAPER_API_KEY")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})

    def fetch_sam_opportunities(self, days_back: int = 14) -> List[Dict[str, Any]]:
        """Queries SAM.gov Opportunities v2 API for DoD/NASA Space & Missile Defense notices."""
        if not self.sam_api_key:
            logging.info("SAM_GOV_API_KEY not set. Skipping SAM.gov REST queries.")
            return []

        now = datetime.now(timezone.utc)
        posted_from = (now - timedelta(days=days_back)).strftime("%m/%d/%Y")
        posted_to = now.strftime("%m/%d/%Y")

        logging.info(f"Querying SAM.gov Opportunities API from {posted_from} to {posted_to}...")

        params = {
            "api_key": self.sam_api_key,
            "postedFrom": posted_from,
            "postedTo": posted_to,
            "limit": 100,
            # Target DoD / Space Force / MDA parent departments
            "deptname": "DEPT OF DEFENSE"
        }

        solicitations = []
        try:
            resp = self.session.get(self.SAM_API_URL, params=params, timeout=25)
            if resp.status_code != 200:
                logging.error(f"SAM.gov API returned HTTP {resp.status_code}: {resp.text[:300]}")
                return []

            data = resp.json()
            records = data.get("opportunitiesData", [])
            logging.info(f"Evaluating {len(records)} active DoD opportunities from SAM.gov...")

            for item in records:
                title = item.get("title", "")
                notice_type = item.get("type", "Solicitation")
                sol_num = item.get("solicitationNumber", "N/A")
                office = item.get("fullParentPathName", item.get("department", "DoD"))
                
                # Combine title, office, and solicitation text for relevance filter
                corpus = f"{title} {office} {sol_num}"
                relevance = evaluate_relevance(corpus)
                if not relevance["is_relevant"]:
                    continue

                notice_id = item.get("noticeId", "")
                ui_url = f"https://sam.gov/opp/{notice_id}/view" if notice_id else "https://sam.gov"

                pocs = []
                for p in item.get("pointOfContact", []):
                    poc_name = p.get("fullName", "")
                    poc_email = p.get("email", "")
                    if poc_email:
                        pocs.append(f"{poc_name} ({poc_email})" if poc_name else poc_email)

                solicitations.append({
                    "source": "SAM.gov",
                    "title": title,
                    "solicitation_number": sol_num,
                    "notice_type": notice_type,
                    "agency_office": office,
                    "response_deadline": item.get("responseDeadLine", "Unspecified"),
                    "naics_code": item.get("naicsCode", "N/A"),
                    "classification": relevance["classification"],
                    "is_golden_dome": relevance["is_golden_dome"],
                    "is_space": relevance["is_space"],
                    "url": ui_url,
                    "point_of_contact": ", ".join(pocs) if pocs else "See listing",
                    "ingested_at": now.isoformat()
                })

            logging.info(f"Captured {len(solicitations)} relevant SAM.gov solicitations.")
        except Exception as e:
            logging.error(f"SAM.gov ingestion failed: {e}")

        return solicitations

    def fetch_diu_solicitations(self) -> List[Dict[str, Any]]:
        """Scrapes active Defense Innovation Unit (DIU) Commercial Solutions Openings (CSOs)."""
        logging.info("Scraping active DIU Commercial Solutions Openings...")
        target_url = self.DIU_OPEN_URL
        
        # Use ScraperAPI if configured, otherwise direct request
        if self.scraper_api_key:
            fetch_url = f"https://api.scraperapi.com?api_key={self.scraper_api_key}&url={quote(target_url)}"
        else:
            fetch_url = target_url

        diu_opportunities = []
        try:
            resp = self.session.get(fetch_url, timeout=25)
            if resp.status_code != 200:
                logging.error(f"DIU request returned HTTP {resp.status_code}")
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.find_all("div", class_=re.compile(r"solicitation|card|challenge", re.IGNORECASE))
            if not cards:
                cards = soup.find_all("a", href=re.compile(r"/work-with-us/open-solicitations/", re.IGNORECASE))

            for card in cards:
                title = card.get_text().strip()
                if len(title) < 15 or "view open" in title.lower():
                    continue

                href = card.get("href") or (card.find("a", href=True)["href"] if card.find("a", href=True) else "")
                full_url = href if href.startswith("http") else f"https://www.diu.mil{href}"

                relevance = evaluate_relevance(title)
                # Keep all DIU solicitations if space-relevant, or catalog as general dual-use
                if relevance["is_relevant"]:
                    diu_opportunities.append({
                        "source": "Defense Innovation Unit (DIU)",
                        "title": title[:140],
                        "solicitation_number": "CSO",
                        "notice_type": "Commercial Solutions Opening",
                        "agency_office": "Defense Innovation Unit / OSD",
                        "response_deadline": "Check DIU Listing",
                        "naics_code": "541715",
                        "classification": relevance["classification"],
                        "is_golden_dome": relevance["is_golden_dome"],
                        "is_space": relevance["is_space"],
                        "url": full_url,
                        "point_of_contact": "DIU Commercial Team",
                        "ingested_at": datetime.now(timezone.utc).isoformat()
                    })

            logging.info(f"Captured {len(diu_opportunities)} space-relevant DIU solicitations.")
        except Exception as e:
            logging.error(f"DIU scraping error: {e}")

        return diu_opportunities

    def get_all_pre_award_signals(self) -> List[Dict[str, Any]]:
        """Aggregates all pre-award opportunities."""
        sam_ops = self.fetch_sam_opportunities(days_back=14)
        diu_ops = self.fetch_diu_solicitations()
        return sam_ops + diu_ops
