import os
import re
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Set
import requests
from scrapers.filter_rules import evaluate_relevance

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class PreAwardScraper:
    """
    Ingests pre-award signals directly from SAM.gov:
    1. Targeted Space NAICS codes
    2. Space Systems Command SpEC Prototype OTAs & Special Notices
    3. NRO & NGA Unclassified Solicitations
    """
    SAM_API_URL = "https://api.sam.gov/opportunities/v2/search"

    TARGET_NAICS = [
        "541715",  # R&D in Physical & Engineering Sciences (SDA BAAs, AFRL, SpaceWERX)
        "336414",  # Guided Missile and Space Vehicle Manufacturing
        "334511",  # Search, Detection, Navigation, Guidance Systems (Sensors, OPIR)
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
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "SpaceIntelPipeline/2.0"})

    def _query_sam(self, params: dict, max_records: int = 300) -> List[dict]:
        if not self.sam_api_key:
            return []

        records = []
        offset = 0
        limit = 100

        while offset < max_records:
            req_params = dict(params)
            req_params.update({
                "api_key": self.sam_api_key,
                "limit": limit,
                "offset": offset
            })

            try:
                resp = self.session.get(self.SAM_API_URL, params=req_params, timeout=25)
                if resp.status_code != 200:
                    break
                data = resp.json()
                batch = data.get("opportunitiesData", [])
                if not batch:
                    break
                records.extend(batch)
                total = data.get("totalRecords", len(records))
                offset += len(batch)
                if offset >= total or len(batch) < limit:
                    break
            except Exception as e:
                logging.error(f"SAM.gov query error: {e}")
                break

        return records

    def fetch_spec_and_otas(self) -> List[Dict[str, Any]]:
        """Pulls authentic SpEC and Space Systems Command OTA prototype opportunities from SAM.gov."""
        logging.info("Querying SAM.gov for SpEC & Space Prototype OTAs...")
        now = datetime.now(timezone.utc)
        posted_from = (now - timedelta(days=30)).strftime("%m/%d/%Y")
        posted_to = now.strftime("%m/%d/%Y")

        ota_queries = [
            '"Space Enterprise Consortium"',
            '"SpEC"',
            '"Space Systems Command" AND "Other Transaction"',
            '"Commercial Augmentation Space Reserve"'
        ]

        raw_items = []
        seen_ids = set()

        for q in ota_queries:
            batch = self._query_sam({
                "q": q,
                "deptname": "DEPT OF DEFENSE",
                "postedFrom": posted_from,
                "postedTo": posted_to
            })
            for item in batch:
                nid = item.get("noticeId")
                if nid and nid not in seen_ids:
                    seen_ids.add(nid)
                    raw_items.append(item)

        results = []
        for item in raw_items:
            title = item.get("title", "")
            sol_num = item.get("solicitationNumber", "SpEC-OTA")
            office = item.get("fullParentPathName", item.get("department", "Space Systems Command"))
            desc = str(item.get("description") or "")
            nid = item.get("noticeId", "")

            corpus = f"{title} {office} {desc[:400]}"
            rel = evaluate_relevance(corpus)
            if not rel["is_relevant"]:
                continue

            results.append({
                "source": "Space Enterprise Consortium (SpEC) / SAM.gov",
                "title": title,
                "solicitation_number": sol_num,
                "notice_type": "Prototype OTA / Special Notice",
                "agency_office": office,
                "response_deadline": item.get("responseDeadLine", "See Notice"),
                "classification": rel["classification"],
                "is_golden_dome": rel["is_golden_dome"],
                "is_space": True,
                "url": f"https://sam.gov/opp/{nid}/view" if nid else "https://sam.gov",
                "point_of_contact": "Space Systems Command Contracting",
                "ingested_at": now.isoformat()
            })

        logging.info(f"Captured {len(results)} verified SpEC & OTA notices.")
        return results

    def fetch_sam_opportunities(self, days_back: int = 14) -> List[Dict[str, Any]]:
        """Sweeps target NAICS codes across all federal agencies."""
        if not self.sam_api_key:
            return []

        now = datetime.now(timezone.utc)
        posted_from = (now - timedelta(days=days_back)).strftime("%m/%d/%Y")
        posted_to = now.strftime("%m/%d/%Y")

        seen_ids = set()
        raw_items = []

        for naics in self.TARGET_NAICS:
            batch = self._query_sam({
                "ncode": naics,
                "postedFrom": posted_from,
                "postedTo": posted_to
            })
            for item in batch:
                nid = item.get("noticeId")
                if nid and nid not in seen_ids:
                    seen_ids.add(nid)
                    raw_items.append(item)

        solicitations = []
        for item in raw_items:
            title = item.get("title", "")
            sol_num = item.get("solicitationNumber", "N/A")
            office = item.get("fullParentPathName", item.get("department", "Federal Government"))
            desc = str(item.get("description") or "")
            naics = item.get("naicsCode", "N/A")
            nid = item.get("noticeId", "")

            corpus = f"{title} {office} {sol_num} {desc[:500]}"
            rel = evaluate_relevance(corpus)
            if not rel["is_relevant"]:
                continue

            solicitations.append({
                "source": "SAM.gov",
                "title": title,
                "solicitation_number": sol_num,
                "notice_type": item.get("type", "Solicitation"),
                "agency_office": office,
                "response_deadline": item.get("responseDeadLine", "Unspecified"),
                "naics_code": naics,
                "classification": rel["classification"],
                "is_golden_dome": rel["is_golden_dome"],
                "is_space": rel["is_space"],
                "url": f"https://sam.gov/opp/{nid}/view" if nid else "https://sam.gov",
                "point_of_contact": "See Listing",
                "ingested_at": now.isoformat()
            })

        return solicitations

    def get_all_pre_award_signals(self) -> dict:
        return {
            "standard_solicitations": self.fetch_sam_opportunities(days_back=14),
            "spec_and_otas": self.fetch_spec_and_otas()
        }
