import os
import re
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Set
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup
from scrapers.filter_rules import evaluate_relevance

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class PreAwardScraper:
    """
    Ingests pre-award signals by:
    1. Sweeping targeted space/defense NAICS codes (agency-agnostic, no keywords)
    2. Evaluating all returned opportunities against filter_rules.py
    3. Monitoring DIU Commercial Solutions Openings (CSOs)
    """
    SAM_API_URL = "https://api.sam.gov/opportunities/v2/search"
    DIU_OPEN_URL = "https://www.diu.mil/work-with-us/open-solicitations"

    # Targeted NAICS Codes
    TARGET_NAICS = [
        "541715",  # R&D in Physical, Engineering, and Life Sciences (SDA BAAs, AFRL, SpaceWERX)
        "336414",  # Guided Missile and Space Vehicle Manufacturing (Satellites, Interceptors)
        "334511",  # Search, Detection, Navigation, Guidance Systems (Sensors, OPIR, Radar)
        "517410",  # Satellite Telecommunications (COMSATCOM, CASR)
        "481212",  # Nonscheduled Chartered Freight Air (Commercial Launch Services, TacRS)
        "334220",  # Wireless Communications Equipment (Space Payloads, SDRs, RF)
        "541511",  # Custom Computer Programming (Space C2, Mission Software)
        "541512",  # Computer Systems Design (Ground Enterprise Architecture, C2BMC)
        "541330",  # Engineering Services (Space Systems Engineering & SETA)
        "336415",  # Space Vehicle Propulsion Units and Parts
    ]

    def __init__(self):
        self.sam_api_key = os.getenv("SAM_GOV_API_KEY")
        self.scraper_api_key = os.getenv("SCRAPER_API_KEY")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "SpaceIntelPipeline/2.0"})

    def _paginate_naics(self, naics_code: str, posted_from: str, posted_to: str, max_records: int = 500) -> List[dict]:
        """Paginates through all federal opportunities for a specific NAICS code."""
        records = []
        offset = 0
        limit = 100

        while offset < max_records:
            params = {
                "api_key": self.sam_api_key,
                "ncode": naics_code,
                "postedFrom": posted_from,
                "postedTo": posted_to,
                "limit": limit,
                "offset": offset
            }

            try:
                resp = self.session.get(self.SAM_API_URL, params=params, timeout=25)
                if resp.status_code != 200:
                    logging.warning(f"SAM.gov NAICS {naics_code} query returned HTTP {resp.status_code} at offset {offset}")
                    break

                data = resp.json()
                batch = data.get("opportunitiesData", [])
                if not batch:
                    break

                records.extend(batch)
                total_available = data.get("totalRecords", len(records))
                offset += len(batch)

                if offset >= total_available or len(batch) < limit:
                    break
            except Exception as e:
                logging.error(f"Error fetching NAICS {naics_code}: {e}")
                break

        return records

    def fetch_sam_opportunities(self, days_back: int = 14) -> List[Dict[str, Any]]:
        """Sweeps target NAICS codes across all agencies and filters for domain relevance."""
        if not self.sam_api_key:
            logging.warning("SAM_GOV_API_KEY missing. Skipping SAM.gov queries.")
            return []

        now = datetime.now(timezone.utc)
        posted_from = (now - timedelta(days=days_back)).strftime("%m/%d/%Y")
        posted_to = now.strftime("%m/%d/%Y")

        logging.info(f"Sweeping {len(self.TARGET_NAICS)} NAICS codes across all federal agencies ({posted_from} to {posted_to})...")

        seen_notice_ids: Set[str] = set()
        raw_opportunities = []

        for idx, naics in enumerate(self.TARGET_NAICS, start=1):
            logging.info(f"[{idx}/{len(self.TARGET_NAICS)}] Querying NAICS {naics}...")
            batch = self._paginate_naics(naics, posted_from, posted_to)
            logging.info(f"   -> Retrieved {len(batch)} notices under NAICS {naics}")

            for item in batch:
                nid = item.get("noticeId")
                if nid and nid not in seen_notice_ids:
                    seen_notice_ids.add(nid)
                    raw_opportunities.append(item)

        logging.info(f"Deduplicated total: {len(raw_opportunities)} notices across all NAICS sweeps.")
        logging.info("Evaluating domain relevance via filter_rules...")

        solicitations = []
        for item in raw_opportunities:
            title = item.get("title", "")
            notice_type = item.get("type", "Solicitation")
            sol_num = item.get("solicitationNumber", "N/A")
            office = item.get("fullParentPathName", item.get("department", "Federal Government"))
            desc = str(item.get("description") or "")
            naics = item.get("naicsCode", "N/A")

            # Build full text corpus (Title + Organization hierarchy + Solicitation ID + Description excerpt)
            corpus = f"{title} {office} {sol_num} {desc[:500]}"
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
                "naics_code": naics,
                "classification": relevance["classification"],
                "is_golden_dome": relevance["is_golden_dome"],
                "is_space": relevance["is_space"],
                "url": ui_url,
                "point_of_contact": ", ".join(pocs) if pocs else "See listing",
                "ingested_at": now.isoformat()
            })

        logging.info(f"Captured {len(solicitations)} relevant space/missile defense solicitations.")
        return solicitations

    def fetch_diu_solicitations(self) -> List[Dict[str, Any]]:
        """Scrapes active Defense Innovation Unit (DIU) Commercial Solutions Openings."""
        logging.info("Scraping active DIU Commercial Solutions Openings...")
        target_url = self.DIU_OPEN_URL

        if self.scraper_api_key:
            fetch_url = f"https://api.scraperapi.com?api_key={self.scraper_api_key}&url={quote(target_url)}"
        else:
            fetch_url = target_url

        diu_opportunities = []
        try:
            resp = self.session.get(fetch_url, timeout=25)
            if resp.status_code == 200:
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
