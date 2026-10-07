import os
import re
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Set
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup
from scrapers.filter_rules import evaluate_relevance

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class DSIPSbirScraper:
    """
    Ingests non-FAR innovation pathways:
    1. SBIR.gov / DSIP public API for active DoD & NASA Space/Missile Defense topics
    2. SpaceWERX Ventures / Open Challenges (TacFI & StratFI matching rounds)
    """
    SBIR_API_URL = "https://api.www.sbir.gov/public/api/solicitations"
    SPACEWERX_VENTURES_URL = "https://spacewerx.us/ventures/overview/"
    SPACEWERX_CHALLENGES_URL = "https://spacewerx.us/challenges/"

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

    def fetch_sbir_topics(self) -> List[Dict[str, Any]]:
        """Queries SBIR.gov API for active DoD/NASA space and missile defense solicitations."""
        logging.info("Querying SBIR.gov / DSIP open solicitation API...")
        keywords = ["space", "satellite", "orbital", "missile tracking", "cislunar"]
        seen_solicitations: Set[str] = set()
        topics = []

        for kw in keywords:
            try:
                params = {"keyword": kw, "open": "1", "rows": "50"}
                resp = self.session.get(self.SBIR_API_URL, params=params, timeout=20)
                if resp.status_code != 200:
                    continue

                records = resp.json()
                for item in records:
                    sol_num = item.get("solicitation_number", "")
                    title = item.get("solicitation_title", "")
                    if not sol_num or sol_num in seen_solicitations:
                        continue

                    agency = item.get("agency", "DoD/NASA")
                    corpus = f"{title} {agency} {item.get('solicitation_description', '')[:300]}"
                    rel = evaluate_relevance(corpus)
                    if not rel["is_relevant"]:
                        continue

                    seen_solicitations.add(sol_num)
                    phase = item.get("phase", "Phase I/II")
                    topics.append({
                        "source": "SBIR / DSIP",
                        "title": title,
                        "solicitation_number": sol_num,
                        "notice_type": f"SBIR/STTR {phase}".strip(),
                        "agency_office": f"{agency} (SBIR/STTR)",
                        "response_deadline": item.get("close_date", "Open Cycle"),
                        "classification": rel["classification"],
                        "is_golden_dome": rel["is_golden_dome"],
                        "is_space": rel["is_space"],
                        "url": item.get("sbir_solicitation_link") or "https://www.sbir.gov",
                        "point_of_contact": "DSIP Helpdesk / Program Manager",
                        "ingested_at": datetime.now(timezone.utc).isoformat()
                    })
            except Exception as e:
                logging.error(f"Error querying SBIR API for '{kw}': {e}")

        logging.info(f"Captured {len(topics)} active space-relevant SBIR/STTR topics.")
        return topics

    def fetch_spacewerx_opportunities(self) -> List[Dict[str, Any]]:
        """Scrapes SpaceWERX Ventures (TacFI, StratFI, and open challenges)."""
        logging.info("Scraping SpaceWERX challenges and Ventures (TacFI/StratFI)...")
        html = self._fetch_html(self.SPACEWERX_CHALLENGES_URL)
        if not html:
            html = self._fetch_html(self.SPACEWERX_VENTURES_URL)

        opportunities = []
        if not html:
            return opportunities

        soup = BeautifulSoup(html, "html.parser")
        cards = soup.find_all(["div", "article", "section"], class_=re.compile(r"challenge|venture|card|portfolio|grid", re.IGNORECASE))

        for card in cards:
            title = card.get_text().strip()
            if len(title) < 20 or "privacy" in title.lower() or "menu" in title.lower():
                continue

            link_tag = card.find("a", href=True)
            link = link_tag["href"] if link_tag else "https://spacewerx.us"
            full_url = link if link.startswith("http") else f"https://spacewerx.us{link}"

            lines = [l.strip() for l in title.splitlines() if len(l.strip()) > 5]
            display_title = lines[0] if lines else "SpaceWERX Spaceflight Capability Need"

            # Detect TacFI or StratFI flags
            is_stratfi = "stratfi" in title.lower()
            is_tacfi = "tacfi" in title.lower()
            notice_type = "StratFI Opportunity" if is_stratfi else ("TacFI Opportunity" if is_tacfi else "SpaceWERX Challenge")

            rel = evaluate_relevance(title)
            opportunities.append({
                "source": "SpaceWERX",
                "title": display_title[:130],
                "solicitation_number": "SpaceWERX-CSO",
                "notice_type": notice_type,
                "agency_office": "USSF / SpaceWERX",
                "response_deadline": "See SpaceWERX Notice",
                "classification": rel["classification"],
                "is_golden_dome": rel["is_golden_dome"],
                "is_space": True,
                "url": full_url,
                "point_of_contact": "SpaceWERX Ventures Directorate",
                "ingested_at": datetime.now(timezone.utc).isoformat()
            })

        # Deduplicate by title
        deduped = []
        seen_titles = set()
        for o in opportunities:
            if o["title"] not in seen_titles:
                seen_titles.add(o["title"])
                deduped.append(o)

        logging.info(f"Captured {len(deduped)} SpaceWERX challenges/initiatives.")
        return deduped

    def get_all_sbir_and_spacewerx(self) -> List[Dict[str, Any]]:
        return self.fetch_sbir_topics() + self.fetch_spacewerx_opportunities()
