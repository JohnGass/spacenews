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
    Ingests pre-award signals:
    1. Targeted NAICS sweeps across SAM.gov (agency-agnostic, zero PSC restrictions)
    2. SpEC (Space Enterprise Consortium) prototype OTAs & SSC Special Notices
    """
    SAM_API_URL = "https://api.sam.gov/opportunities/v2/search"
    SPEC_OPP_URL = "https://space-enterprise.org/opportunities/"

    TARGET_NAICS = [
        "541715",  # R&D in Physical, Engineering, and Life Sciences
        "336414",  # Guided Missile and Space Vehicle Manufacturing
        "334511",  # Search, Detection, Navigation, Guidance Systems
        "517410",  # Satellite Telecommunications
        "481212",  # Commercial Launch & Space Transport
        "334220",  # Wireless Communications & RF Payloads
        "541511",  # Custom Computer Programming (Space C2)
        "541512",  # Computer Systems Design (Ground Enterprise)
        "541330",  # Aerospace Systems Engineering Services
        "336415",  # Space Propulsion Units and Parts
    ]

    def __init__(self):
        self.sam_api_key = os.getenv("SAM_GOV_API_KEY")
        self.scraper_api_key = os.getenv("SCRAPER_API_KEY")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "SpaceIntelPipeline/2.0"})

    def _paginate_sam_query(self, base_params: dict, max_records: int = 500) -> List[dict]:
        records = []
        offset = 0
        limit = 100

        while offset < max_records:
            params = dict(base_params)
            params.update({
                "api_key": self.sam_api_key,
                "limit": limit,
                "offset": offset
            })

            try:
                resp = self.session.get(self.SAM_API_URL, params=params, timeout=25)
                if resp.status_code != 200:
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
                logging.error(f"SAM.gov pagination error: {e}")
                break

        return records

    def fetch_spec_and_ota_notices(self) -> List[Dict[str, Any]]:
        """Captures SpEC and Other Transaction Authority (OTA) notices from SAM.gov and NSTXL."""
        logging.info("Ingesting SpEC (Space Enterprise Consortium) & OTA opportunities...")
        ota_items = []

        # 1. Scrape public SpEC Opportunity teasers from space-enterprise.org
        fetch_url = f"https://api.scraperapi.com?api_key={self.scraper_api_key}&url={quote(self.SPEC_OPP_URL)}" if self.scraper_api_key else self.SPEC_OPP_URL
        try:
            resp = self.session.get(fetch_url, timeout=25)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                cards = soup.find_all(["div", "article"], class_=re.compile(r"opportunity|card|post", re.IGNORECASE))
                for card in cards:
                    txt = card.get_text().strip()
                    if len(txt) < 30 or "member dashboard" in txt.lower():
                        continue
                    a_tag = card.find("a", href=True)
                    url = a_tag["href"] if a_tag else "https://space-enterprise.org/opportunities/"
                    first_line = [l.strip() for l in txt.splitlines() if len(l.strip()) > 5]
                    title = first_line[0] if first_line else "SpEC Prototype Project"
                    rel = evaluate_relevance(txt)

                    ota_items.append({
                        "source": "Space Enterprise Consortium (SpEC)",
                        "title": title[:130],
                        "solicitation_number": "SpEC-OTA",
                        "notice_type": "Other Transaction Agreement (OTA) Prototype",
                        "agency_office": "Space Systems Command (SSC) / NSTXL",
                        "response_deadline": "See SpEC Member Portal",
                        "classification": rel["classification"],
                        "is_golden_dome": rel["is_golden_dome"],
                        "is_space": True,
                        "url": url,
                        "point_of_contact": "NSTXL SpEC Consortium Management",
                        "ingested_at": datetime.now(timezone.utc).isoformat()
                    })
        except Exception as e:
            logging.error(f"Error scraping SpEC website: {e}")

        # 2. Query SAM.gov for Special Notices & Prototype announcements mentioning SpEC or OTAs
        if self.sam_api_key:
            now = datetime.now(timezone.utc)
            posted_from = (now - timedelta(days=21)).strftime("%m/%d/%Y")
            posted_to = now.strftime("%m/%d/%Y")
            ota_queries = ['"Space Enterprise Consortium"', '"SpEC"', '"Other Transaction" space', '"CASR"']

            for q in ota_queries:
                batch = self._paginate_sam_query({
                    "q": q,
                    "deptname": "DEPT OF DEFENSE",
                    "postedFrom": posted_from,
                    "postedTo": posted_to
                })
                for item in batch:
                    title = item.get("title", "")
                    notice_type = item.get("type", "Special Notice")
                    sol_num = item.get("solicitationNumber", "N/A")
                    office = item.get("fullParentPathName", item.get("department", "Space Systems Command"))
                    nid = item.get("noticeId", "")
                    rel = evaluate_relevance(f"{title} {office}")
                    if not rel["is_relevant"]:
                        continue

                    ota_items.append({
                        "source": "SAM.gov / OTA Special Notice",
                        "title": title,
                        "solicitation_number": sol_num,
                        "notice_type": f"OTA / {notice_type}",
                        "agency_office": office,
                        "response_deadline": item.get("responseDeadLine", "See Notice"),
                        "classification": rel["classification"],
                        "is_golden_dome": rel["is_golden_dome"],
                        "is_space": rel["is_space"],
                        "url": f"https://sam.gov/opp/{nid}/view" if nid else "https://sam.gov",
                        "point_of_contact": "See Listing",
                        "ingested_at": now.isoformat()
                    })

        # Deduplicate
        seen = set()
        deduped = []
        for o in ota_items:
            key = f"{o['title']}_{o['solicitation_number']}"
            if key not in seen:
                seen.add(key)
                deduped.append(o)

        logging.info(f"Captured {len(deduped)} SpEC & OTA notices.")
        return deduped

    def fetch_sam_opportunities(self, days_back: int = 14) -> List[Dict[str, Any]]:
        """Sweeps target NAICS codes across all agencies."""
        if not self.sam_api_key:
            return []

        now = datetime.now(timezone.utc)
        posted_from = (now - timedelta(days=days_back)).strftime("%m/%d/%Y")
        posted_to = now.strftime("%m/%d/%Y")
        seen_notice_ids: Set[str] = set()
        raw_opportunities = []

        for idx, naics in enumerate(self.TARGET_NAICS, start=1):
            batch = self._paginate_sam_query({
                "ncode": naics,
                "postedFrom": posted_from,
                "postedTo": posted_to
            })
            for item in batch:
                nid = item.get("noticeId")
                if nid and nid not in seen_notice_ids:
                    seen_notice_ids.add(nid)
                    raw_opportunities.append(item)

        solicitations = []
        for item in raw_opportunities:
            title = item.get("title", "")
            notice_type = item.get("type", "Solicitation")
            sol_num = item.get("solicitationNumber", "N/A")
            office = item.get("fullParentPathName", item.get("department", "Federal Government"))
            desc = str(item.get("description") or "")

            corpus = f"{title} {office} {sol_num} {desc[:500]}"
            relevance = evaluate_relevance(corpus)
            if not relevance["is_relevant"]:
                continue

            nid = item.get("noticeId", "")
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
                "url": f"https://sam.gov/opp/{nid}/view" if nid else "https://sam.gov",
                "point_of_contact": "See Listing",
                "ingested_at": now.isoformat()
            })

        return solicitations

    def get_all_pre_award_signals(self) -> dict:
        return {
            "standard_solicitations": self.fetch_sam_opportunities(days_back=14),
            "spec_and_otas": self.fetch_spec_and_ota_notices()
        }
