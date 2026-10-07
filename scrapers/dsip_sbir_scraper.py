import os
import re
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Set
import requests
from scrapers.filter_rules import evaluate_relevance

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class DSIPSbirScraper:
    """
    Ingests non-FAR innovation pathways:
    1. SBIR.gov API for active DoD Space / Missile Defense Topics
    2. SAM.gov targeted queries for SpaceWERX Open Topic, TacFI, and StratFI notices
    """
    SBIR_API_URL = "https://api.www.sbir.gov/public/api/solicitations"
    SAM_API_URL = "https://api.sam.gov/opportunities/v2/search"

    def __init__(self):
        self.sam_api_key = os.getenv("SAM_GOV_API_KEY")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "SpaceIntelPipeline/2.0"})

    def fetch_sbir_topics(self) -> List[Dict[str, Any]]:
        """Queries SBIR.gov for active space and missile defense topics."""
        logging.info("Querying SBIR.gov for active space topics...")
        keywords = ["spacecraft", "satellite", "orbital", "cislunar", "missile warning"]
        seen_ids = set()
        topics = []

        for kw in keywords:
            try:
                params = {"keyword": kw, "open": "1", "rows": "50"}
                resp = self.session.get(self.SBIR_API_URL, params=params, timeout=20)
                if resp.status_code != 200:
                    continue

                for item in resp.json():
                    sol_num = item.get("solicitation_number", "")
                    title = item.get("solicitation_title", "")
                    agency = item.get("agency", "DoD/NASA")

                    if not sol_num or sol_num in seen_ids:
                        continue

                    # Filter out non-aerospace hits
                    corpus = f"{title} {agency} {item.get('solicitation_description', '')[:400]}"
                    rel = evaluate_relevance(corpus)
                    if not rel["is_relevant"]:
                        continue

                    seen_ids.add(sol_num)
                    link = item.get("sbir_solicitation_link") or "https://www.sbir.gov"

                    topics.append({
                        "source": "SBIR.gov / DSIP",
                        "title": title,
                        "solicitation_number": sol_num,
                        "notice_type": f"SBIR {item.get('phase', 'Topic')}",
                        "agency_office": f"{agency} (SBIR/STTR)",
                        "response_deadline": item.get("close_date", "Open"),
                        "classification": rel["classification"],
                        "is_golden_dome": rel["is_golden_dome"],
                        "is_space": True,
                        "url": link,
                        "point_of_contact": "DSIP Program Office",
                        "ingested_at": datetime.now(timezone.utc).isoformat()
                    })
            except Exception as e:
                logging.error(f"Error querying SBIR API for {kw}: {e}")

        logging.info(f"Captured {len(topics)} space-relevant SBIR topics.")
        return topics

    def fetch_spacewerx_sam_notices(self) -> List[Dict[str, Any]]:
        """Queries SAM.gov specifically for SpaceWERX and USSF TacFI/StratFI calls."""
        if not self.sam_api_key:
            return []

        logging.info("Querying SAM.gov specifically for SpaceWERX notices...")
        now = datetime.now(timezone.utc)
        posted_from = (now - timedelta(days=60)).strftime("%m/%d/%Y")
        posted_to = now.strftime("%m/%d/%Y")

        # Specific queries targeting USSF/SpaceWERX, dropping generic Air Force TacFI
        queries = [
            '"SpaceWERX"',
            '"Space Systems Command" AND "TacFI"',
            '"Space Systems Command" AND "StratFI"',
            '"Space Force" AND "StratFI"'
        ]
        seen_ids = set()
        results = []

        for q in queries:
            try:
                params = {
                    "api_key": self.sam_api_key,
                    "q": q,
                    "deptname": "DEPT OF DEFENSE",
                    "postedFrom": posted_from,
                    "postedTo": posted_to,
                    "limit": 50
                }
                resp = self.session.get(self.SAM_API_URL, params=params, timeout=25)
                if resp.status_code != 200:
                    continue

                for item in resp.json().get("opportunitiesData", []):
                    nid = item.get("noticeId")
                    if not nid or nid in seen_ids:
                        continue

                    title = item.get("title", "")
                    office = item.get("fullParentPathName", "SpaceWERX / USSF")
                    desc = str(item.get("description") or "")

                    # Strict relevance guard
                    rel = evaluate_relevance(f"{title} {office} {desc[:300]}")
                    if not rel["is_relevant"]:
                        continue

                    seen_ids.add(nid)
                    is_stratfi = "stratfi" in title.lower()
                    is_tacfi = "tacfi" in title.lower()
                    notice_type = "StratFI Opportunity" if is_stratfi else ("TacFI Opportunity" if is_tacfi else "SpaceWERX Challenge")

                    results.append({
                        "source": "SpaceWERX / USSF",
                        "title": title,
                        "solicitation_number": item.get("solicitationNumber", "SpaceWERX"),
                        "notice_type": notice_type,
                        "agency_office": office,
                        "response_deadline": item.get("responseDeadLine", "See Listing"),
                        "classification": rel["classification"],
                        "is_golden_dome": rel["is_golden_dome"],
                        "is_space": True,
                        "url": f"https://sam.gov/opp/{nid}/view",
                        "point_of_contact": "SpaceWERX Ventures",
                        "ingested_at": now.isoformat()
                    })
            except Exception as e:
                logging.error(f"Error querying SpaceWERX notices: {e}")

        logging.info(f"Captured {len(results)} verified SpaceWERX notices.")
        return results

    def get_all_sbir_and_spacewerx(self) -> List[Dict[str, Any]]:
        return self.fetch_sbir_topics() + self.fetch_spacewerx_sam_notices()
