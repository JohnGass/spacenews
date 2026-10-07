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

class ICDIUScraper:
    """
    Ingests commercial innovation and intelligence community opportunities:
    1. Live DIU Commercial Solutions Openings (CSOs)
    2. NRO & NGA unclassified solicitations via SAM.gov
    3. In-Q-Tel (IQT) technology problem sets
    """
    DIU_OPEN_URL = "https://www.diu.mil/work-with-us/open-solicitations"
    SAM_API_URL = "https://api.sam.gov/opportunities/v2/search"

    def __init__(self):
        self.sam_api_key = os.getenv("SAM_GOV_API_KEY")
        self.scraper_api_key = os.getenv("SCRAPER_API_KEY")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "SpaceIntelPipeline/2.0"})

    def fetch_diu_csos(self) -> List[Dict[str, Any]]:
        """Scrapes active Defense Innovation Unit (DIU) CSOs."""
        logging.info("Scraping DIU Commercial Solutions Openings (CSOs)...")
        fetch_url = f"https://api.scraperapi.com?api_key={self.scraper_api_key}&url={quote(self.DIU_OPEN_URL)}" if self.scraper_api_key else self.DIU_OPEN_URL

        csos = []
        try:
            resp = self.session.get(fetch_url, timeout=25)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                cards = soup.find_all(["div", "article", "a"], class_=re.compile(r"solicitation|card|challenge|item", re.IGNORECASE))
                for card in cards:
                    txt = card.get_text().strip()
                    if len(txt) < 20 or "view all" in txt.lower():
                        continue

                    a_tag = card if card.name == "a" else card.find("a", href=True)
                    href = a_tag["href"] if a_tag else ""
                    url = href if href.startswith("http") else f"https://www.diu.mil{href}"

                    rel = evaluate_relevance(txt)
                    csos.append({
                        "source": "Defense Innovation Unit (DIU)",
                        "title": txt.splitlines()[0][:130].strip(),
                        "solicitation_number": "DIU-CSO",
                        "notice_type": "Commercial Solutions Opening (CSO)",
                        "agency_office": "DIU / OSD",
                        "response_deadline": "Check Challenge Window",
                        "classification": rel["classification"],
                        "is_golden_dome": rel["is_golden_dome"],
                        "is_space": rel["is_space"],
                        "url": url if url.startswith("http") else "https://www.diu.mil/work-with-us/open-solicitations",
                        "point_of_contact": "DIU Commercial Team",
                        "ingested_at": datetime.now(timezone.utc).isoformat()
                    })
        except Exception as e:
            logging.error(f"DIU CSO scraping error: {e}")

        # Deduplicate
        seen = set()
        deduped = []
        for c in csos:
            if c["title"] not in seen:
                seen.add(c["title"])
                deduped.append(c)

        logging.info(f"Captured {len(deduped)} DIU CSOs.")
        return deduped

    def fetch_nro_and_nga_sam(self) -> List[Dict[str, Any]]:
        """Queries SAM.gov for unclassified NRO and NGA solicitations."""
        if not self.sam_api_key:
            return []

        logging.info("Querying SAM.gov for NRO & NGA unclassified opportunities...")
        now = datetime.now(timezone.utc)
        posted_from = (now - timedelta(days=45)).strftime("%m/%d/%Y")
        posted_to = now.strftime("%m/%d/%Y")

        ic_queries = [
            '"National Geospatial-Intelligence Agency"',
            '"National Reconnaissance Office"',
            '"Commercial GEOINT"',
            '"Director\'s Innovation Initiative"'
        ]

        seen_ids = set()
        results = []

        for q in ic_queries:
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
                    seen_ids.add(nid)

                    title = item.get("title", "")
                    office = item.get("fullParentPathName", "Intelligence Community")
                    rel = evaluate_relevance(f"{title} {office}")

                    is_nro = "reconnaissance" in office.lower() or "nro" in title.lower()
                    source_label = "NRO (SAM.gov)" if is_nro else "NGA (SAM.gov)"

                    results.append({
                        "source": source_label,
                        "title": title,
                        "solicitation_number": item.get("solicitationNumber", "IC-OPP"),
                        "notice_type": item.get("type", "IC Broad Agency Announcement"),
                        "agency_office": office,
                        "response_deadline": item.get("responseDeadLine", "See Notice"),
                        "classification": rel["classification"],
                        "is_golden_dome": rel["is_golden_dome"],
                        "is_space": True,
                        "url": f"https://sam.gov/opp/{nid}/view",
                        "point_of_contact": "IC Acquisition Directorate",
                        "ingested_at": now.isoformat()
                    })
            except Exception as e:
                logging.error(f"Error querying NRO/NGA SAM notices: {e}")

        logging.info(f"Captured {len(results)} NRO/NGA solicitations.")
        return results

    def get_standing_ic_portals(self) -> List[Dict[str, Any]]:
        """Provides verified public-facing industry entry points."""
        now = datetime.now(timezone.utc).isoformat()
        return [
            {
                "source": "NRO Public Acquisition Portal",
                "title": "NRO Director's Innovation Initiative (DII) & Business Opportunities",
                "solicitation_number": "NRO-DII-PORTAL",
                "notice_type": "Public Acquisition Center",
                "agency_office": "National Reconnaissance Office (NRO)",
                "response_deadline": "Annual Open Rounds",
                "classification": "Space Relevant",
                "is_golden_dome": False,
                "is_space": True,
                "url": "https://www.nro.gov/Acquisition/",
                "point_of_contact": "NRO Office of Contracts",
                "ingested_at": now
            },
            {
                "source": "NGA Industry Portal",
                "title": "NGA Commercial GEOINT, BIG-R BAA & Industry Engagement",
                "solicitation_number": "NGA-INDUSTRY",
                "notice_type": "Commercial Solutions Portal",
                "agency_office": "National Geospatial-Intelligence Agency (NGA)",
                "response_deadline": "Continuous Intake",
                "classification": "Space Relevant",
                "is_golden_dome": False,
                "is_space": True,
                "url": "https://www.nga.mil/industry.html",
                "point_of_contact": "NGA Commercial Operations",
                "ingested_at": now
            },
            {
                "source": "In-Q-Tel (IQT)",
                "title": "IQT Commercial Space, Autonomous Systems & Sensor Problem Sets",
                "solicitation_number": "IQT-FOCUS",
                "notice_type": "Strategic Commercial Venture",
                "agency_office": "In-Q-Tel (CIA / NRO / NGA / USSF)",
                "response_deadline": "Continuous Pitch Intake",
                "classification": "Space Relevant",
                "is_golden_dome": False,
                "is_space": True,
                "url": "https://www.iqt.org/portfolio/",
                "point_of_contact": "IQT Space & Hardware Practice",
                "ingested_at": now
            }
        ]

    def get_all_ic_and_diu(self) -> List[Dict[str, Any]]:
        return self.fetch_diu_csos() + self.fetch_nro_and_nga_sam() + self.get_standing_ic_portals()
