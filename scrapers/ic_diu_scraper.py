import os
import re
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup
from scrapers.filter_rules import evaluate_relevance

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class ICDIUScraper:
    """
    Ingests commercial innovation and intelligence community opportunities:
    1. Defense Innovation Unit (DIU) Commercial Solutions Openings (CSOs)
    2. In-Q-Tel (IQT) Strategic Investment Problem Sets & Focus Areas
    3. NRO & NGA Unclassified Acquisition Initiatives (DII & Commercial GEOINT BAAs)
    """
    DIU_OPEN_URL = "https://www.diu.mil/work-with-us/open-solicitations"
    IQT_FOCUS_URL = "https://www.iqt.org/focus-areas/"

    def __init__(self):
        self.scraper_api_key = os.getenv("SCRAPER_API_KEY")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "SpaceIntelPipeline/2.0"})

    def _fetch_html(self, url: str) -> str:
        fetch_url = f"https://api.scraperapi.com?api_key={self.scraper_api_key}&url={quote(url)}" if self.scraper_api_key else url
        try:
            resp = self.session.get(fetch_url, timeout=25)
            if resp.status_code == 200:
                return resp.text
        except Exception as e:
            logging.error(f"Failed to fetch {url}: {e}")
        return ""

    def fetch_diu_csos(self) -> List[Dict[str, Any]]:
        """Scrapes active Defense Innovation Unit (DIU) Commercial Solutions Openings."""
        logging.info("Scraping DIU Commercial Solutions Openings (CSOs)...")
        html = self._fetch_html(self.DIU_OPEN_URL)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        cards = soup.find_all(["div", "article", "a"], class_=re.compile(r"solicitation|card|challenge|item", re.IGNORECASE))
        if not cards:
            cards = soup.find_all("a", href=re.compile(r"/work-with-us/open-solicitations/", re.IGNORECASE))

        csos = []
        for card in cards:
            title = card.get_text().strip()
            if len(title) < 20 or "view all" in title.lower():
                continue

            href = card.get("href") or (card.find("a", href=True)["href"] if card.find("a", href=True) else "")
            full_url = href if href.startswith("http") else f"https://www.diu.mil{href}"

            rel = evaluate_relevance(title)
            csos.append({
                "source": "Defense Innovation Unit (DIU)",
                "title": title[:140].replace("\n", " "),
                "solicitation_number": "DIU-CSO",
                "notice_type": "Commercial Solutions Opening (CSO)",
                "agency_office": "DIU / OSD",
                "response_deadline": "Check DIU Challenge Window",
                "classification": rel["classification"],
                "is_golden_dome": rel["is_golden_dome"],
                "is_space": rel["is_space"],
                "url": full_url,
                "point_of_contact": "DIU Commercial Acquisition Directorate",
                "ingested_at": datetime.now(timezone.utc).isoformat()
            })

        # Deduplicate
        seen = set()
        deduped = []
        for c in csos:
            if c["title"] not in seen:
                seen.add(c["title"])
                deduped.append(c)

        logging.info(f"Captured {len(deduped)} DIU CSO opportunities.")
        return deduped

    def fetch_iqt_focus_areas(self) -> List[Dict[str, Any]]:
        """Scrapes In-Q-Tel technology problem sets and strategic focus areas."""
        logging.info("Scraping In-Q-Tel (IQT) strategic technology problem sets...")
        html = self._fetch_html(self.IQT_FOCUS_URL)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        focus_cards = soup.find_all(["div", "h2", "h3", "article"])
        iqt_items = []

        target_keywords = ["space", "satellite", "orbital", "sensor", "autonomous", "quantum", "optical", "analytics"]

        for elem in focus_cards:
            text = elem.get_text().strip()
            if len(text) < 25 or len(text) > 300:
                continue

            if any(k in text.lower() for k in target_keywords):
                link_tag = elem.find("a", href=True)
                url = link_tag["href"] if link_tag else "https://www.iqt.org/focus-areas/"
                full_url = url if url.startswith("http") else f"https://www.iqt.org{url}"

                iqt_items.append({
                    "source": "In-Q-Tel (IQT)",
                    "title": text.splitlines()[0][:130],
                    "solicitation_number": "IQT-Strategic-Focus",
                    "notice_type": "Strategic IC Commercial Venture",
                    "agency_office": "In-Q-Tel / CIA / NRO / NGA",
                    "response_deadline": "Continuous Pitch Intake",
                    "classification": "Space Relevant",
                    "is_golden_dome": False,
                    "is_space": True,
                    "url": full_url,
                    "point_of_contact": "IQT Technology Practice Lead",
                    "ingested_at": datetime.now(timezone.utc).isoformat()
                })

        seen = set()
        deduped = []
        for item in iqt_items:
            if item["title"] not in seen:
                seen.add(item["title"])
                deduped.append(item)

        logging.info(f"Captured {len(deduped)} In-Q-Tel technology problem areas.")
        return deduped

    def fetch_ic_arc_initiatives(self) -> List[Dict[str, Any]]:
        """Catalogs standing NRO Director's Innovation Initiative (DII) and NGA BAA portals."""
        now = datetime.now(timezone.utc).isoformat()
        return [
            {
                "source": "NRO DII / ARC",
                "title": "NRO Director's Innovation Initiative (DII) - Advanced Disruptive Space Tech",
                "solicitation_number": "NRO-DII-ANNUAL",
                "notice_type": "Broad Agency Announcement (BAA)",
                "agency_office": "National Reconnaissance Office (NRO) / AS&T",
                "response_deadline": "Annual Open Solicitations",
                "classification": "Space Relevant",
                "is_golden_dome": False,
                "is_space": True,
                "url": "https://acq.westfields.net/",
                "point_of_contact": "NRO Acquisition Research Center (ARC)",
                "ingested_at": now
            },
            {
                "source": "NGA Commercial BAA",
                "title": "NGA Boosting Innovative GEOINT Research (BIG-R) & Commercial Satellites",
                "solicitation_number": "HM0476-BAA",
                "notice_type": "Commercial GEOINT BAA",
                "agency_office": "National Geospatial-Intelligence Agency (NGA)",
                "response_deadline": "Standing Open Call",
                "classification": "Space Relevant",
                "is_golden_dome": False,
                "is_space": True,
                "url": "https://acquisition.geoint.services/",
                "point_of_contact": "NGA Commercial Solutions Office",
                "ingested_at": now
            }
        ]

    def get_all_ic_and_diu(self) -> List[Dict[str, Any]]:
        return self.fetch_diu_csos() + self.fetch_iqt_focus_areas() + self.fetch_ic_arc_initiatives()
