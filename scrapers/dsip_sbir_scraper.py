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

class DSIPSbirScraper:
    """
    Precision Space & Golden Dome SBIR/STTR and SpaceWERX Ingestion Engine.
    1. Unpacks nested `solicitation_topics` from official SBIR.gov Solicitations API.
    2. Deep technical space subsystem regex (catches topics omitting 'space').
    3. Scrapes SpaceWERX rolling TACFI, STRATFI, and challenge opportunities.
    4. Sweeps SAM.gov for SpaceWERX Commercial Solutions Openings (CSOs).
    """
    SOLICITATIONS_API_URL = "https://api.www.sbir.gov/public/api/solicitations"
    SAM_API_URL = "https://api.sam.gov/opportunities/v2/search"
    SPACEWERX_URL = "https://spacewerx.us/"

    SUBSYSTEM_TECHNICAL_PATTERNS = [
        r"\b(hall\s+effect\s+thruster|electric\s+propulsion|cold\s+gas\s+thruster|green\s+propellant)\b",
        r"\b(star\s+tracker|reaction\s+wheel|control\s+moment\s+gyro|orbital\s+insertion)\b",
        r"\b(optical\s+inter-satellite|oisl|laser\s+communication\s+terminal|lct)\b",
        r"\b(focal\s+plane\s+array|fpa|opir|persistent\s+infrared|infrared\s+sensor)\b",
        r"\b(space\s+domain\s+awareness|sda|space\s+situational\s+awareness|ssa)\b",
        r"\b(phased\s+array\s+antenna|ka-band\s+payload|x-band\s+downlink|synthetic\s+aperture\s+radar|sar\s+payload)\b",
        r"\b(cislunar|lagrange\s+point|vleo|very\s+low\s+earth|geostationary|geo\s+belt)\b",
        r"\b(rendezvous\s+and\s+proximity|rpo|non-cooperative\s+docking|deorbit\s+mechanism)\b",
        r"\b(in-space\s+servicing|assembly\s+and\s+manufacturing|isam|on-orbit\s+refueling)\b",
        r"\b(radiation-hardened|rad-hard|spaceborne\s+edge|flight\s+computer|space-qualified|cubesat|smallsat)\b",
        r"\b(glide\s+phase\s+interceptor|hbtss|missile\s+tracking|hypersonic\s+tracking|c2bmc)\b"
    ]
    COMPILED_TECH_REGEX = re.compile("|".join(SUBSYSTEM_TECHNICAL_PATTERNS), re.IGNORECASE)

    def __init__(self):
        self.sam_api_key = os.getenv("SAM_GOV_API_KEY")
        self.scraper_api_key = os.getenv("SCRAPER_API_KEY")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) SpaceIntelPipeline/3.0",
            "Accept": "application/json, text/plain, */*"
        })

    def _is_space_relevant(self, text_corpus: str) -> dict:
        std_eval = evaluate_relevance(text_corpus)
        if std_eval["is_relevant"]:
            return std_eval
        tech_match = self.COMPILED_TECH_REGEX.search(text_corpus)
        if tech_match:
            is_gd = any(term in text_corpus.lower() for term in ["glide phase", "hbtss", "missile tracking", "c2bmc"])
            return {
                "is_relevant": True,
                "is_space": True,
                "is_golden_dome": is_gd,
                "classification": "Golden Dome Priority" if is_gd else "Space Relevant"
            }
        return {"is_relevant": False, "is_space": False, "is_golden_dome": False, "classification": "Non-Relevant"}

    def _determine_topic_type(self, title: str, desc: str, sol_title: str) -> str:
        t_low = f"{title} {desc} {sol_title}".lower()
        if "tacfi" in t_low:
            return "TacFI ($1.5M Match)"
        if "stratfi" in t_low:
            return "StratFI ($15M Match)"
        if "direct to phase ii" in t_low or "d2p2" in t_low:
            return "Direct-to-Phase II (D2P2)"
        if "sttr" in t_low:
            return "STTR Topic"
        if "phase ii" in t_low:
            return "SBIR Phase II"
        return "SBIR Phase I / Open"

    def fetch_sbir_gov_topics(self) -> List[Dict[str, Any]]:
        """Queries SBIR.gov Solicitations API and unpacks all nested space topics."""
        logging.info("Querying SBIR.gov Solicitations API to unpack active space topics...")
        seen_topic_numbers: Set[str] = set()
        topics = []

        query_endpoints = [
            {"open": "1", "rows": "50"},
            {"keyword": "space", "open": "1", "rows": "50"},
            {"agency": "DOD", "open": "1", "rows": "50"},
            {"agency": "NASA", "open": "1", "rows": "50"}
        ]

        raw_solicitations = []
        seen_sol_ids = set()

        for params in query_endpoints:
            try:
                resp = self.session.get(self.SOLICITATIONS_API_URL, params=params, timeout=20)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list):
                        for sol in data:
                            sol_num = sol.get("solicitation_number") or sol.get("solicitation_title")
                            if sol_num and sol_num not in seen_sol_ids:
                                seen_sol_ids.add(sol_num)
                                raw_solicitations.append(sol)
            except Exception as e:
                logging.error(f"Error querying SBIR.gov Solicitations API ({params}): {e}")

        logging.info(f"Retrieved {len(raw_solicitations)} active solicitations from SBIR.gov. Unpacking nested topics...")

        for sol in raw_solicitations:
            sol_title = sol.get("solicitation_title", "")
            agency = sol.get("agency", "DOD")
            close_date = sol.get("close_date", "Open")
            sol_link = sol.get("sbir_solicitation_link") or "https://www.sbir.gov/solicitations"

            sol_topics = sol.get("solicitation_topics", [])

            # Fallback: if solicitation has no unpacked topics, check solicitation title itself
            if not sol_topics:
                rel = self._is_space_relevant(f"{sol_title} {agency}")
                if rel["is_relevant"]:
                    topics.append({
                        "source": f"SBIR.gov / {agency}",
                        "title": sol_title,
                        "solicitation_number": sol.get("solicitation_number", "SBIR-SOL"),
                        "notice_type": self._determine_topic_type(sol_title, "", sol_title),
                        "agency_office": agency,
                        "response_deadline": close_date,
                        "classification": rel["classification"],
                        "is_golden_dome": rel["is_golden_dome"],
                        "is_space": True,
                        "url": sol_link,
                        "point_of_contact": "See SBIR.gov Solicitation",
                        "ingested_at": datetime.now(timezone.utc).isoformat()
                    })
                continue

            # Unpack each nested topic
            for t in sol_topics:
                t_title = t.get("topic_title") or t.get("title") or ""
                t_num = str(t.get("topic_number") or t.get("topic_code") or "")
                branch = str(t.get("branch") or agency).strip()
                t_desc = str(t.get("topic_description") or "")
                t_link = t.get("sbir_topic_link") or sol_link

                if not t_title:
                    continue

                corpus = f"{t_title} {sol_title} {branch} {t_desc[:500]}"
                rel = self._is_space_relevant(corpus)

                if "SPACE" in branch.upper() or "SPACEWERX" in corpus.upper():
                    rel["is_relevant"] = True
                    rel["is_space"] = True

                if not rel["is_relevant"]:
                    continue

                dedup_key = t_num if t_num else t_title[:40].lower()
                if dedup_key in seen_topic_numbers:
                    continue
                seen_topic_numbers.add(dedup_key)

                topics.append({
                    "source": f"SBIR / {branch}",
                    "title": t_title,
                    "solicitation_number": t_num or "Topic",
                    "notice_type": self._determine_topic_type(t_title, t_desc, sol_title),
                    "agency_office": f"{agency} - {branch}" if branch != agency else agency,
                    "response_deadline": close_date,
                    "classification": rel["classification"],
                    "is_golden_dome": rel["is_golden_dome"],
                    "is_space": True,
                    "url": t_link,
                    "point_of_contact": "See Topic details in DSIP",
                    "ingested_at": datetime.now(timezone.utc).isoformat()
                })

        logging.info(f"Captured {len(topics)} space-relevant SBIR/STTR topics from SBIR.gov.")
        return topics

    def fetch_spacewerx_site_opportunities(self) -> List[Dict[str, Any]]:
        """Scrapes active SpaceWERX announcements (TACFI NOO, Challenges, Releases) from spacewerx.us."""
        logging.info("Scraping active SpaceWERX announcements (TACFI, Challenges, Releases)...")
        fetch_url = self.SPACEWERX_URL
        if self.scraper_api_key:
            fetch_url = f"https://api.scraperapi.com?api_key={self.scraper_api_key}&url={quote(self.SPACEWERX_URL)}"

        notices = []
        try:
            resp = self.session.get(fetch_url, timeout=20)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                blocks = soup.find_all(["div", "article", "section", "li"])
                seen_titles = set()

                for block in blocks:
                    text = block.get_text(" ", strip=True)
                    if not any(k in text.lower() for k in ["tacfi", "stratfi", "release", "now open", "challenge", "noo"]):
                        continue
                    if len(text) < 30 or len(text) > 400:
                        continue

                    a_tag = block.find("a", href=True)
                    href = a_tag["href"] if a_tag else "https://spacewerx.us"
                    full_url = href if href.startswith("http") else f"https://spacewerx.us{href}"

                    lines = [l.strip() for l in text.split("  ") if len(l.strip()) > 10]
                    title = lines[0] if lines else text[:120]

                    t_key = title[:35].lower()
                    if t_key in seen_titles or "menu" in t_key or "privacy" in t_key:
                        continue
                    seen_titles.add(t_key)

                    n_type = "SpaceWERX Notice"
                    if "tacfi" in text.lower():
                        n_type = "TacFI ($1.5M Match - Rolling)"
                    elif "stratfi" in text.lower():
                        n_type = "StratFI ($15M Match)"
                    elif "release" in text.lower():
                        n_type = "SpaceWERX SBIR Release"
                    elif "challenge" in text.lower():
                        n_type = "SpaceWERX Challenge"

                    notices.append({
                        "source": "SpaceWERX",
                        "title": title[:140],
                        "solicitation_number": "SpaceWERX-Open",
                        "notice_type": n_type,
                        "agency_office": "USSF / SpaceWERX",
                        "response_deadline": "Rolling / Check SpaceWERX",
                        "classification": "Space Relevant",
                        "is_golden_dome": False,
                        "is_space": True,
                        "url": full_url,
                        "point_of_contact": "SpaceWERX Ventures Directorate",
                        "ingested_at": datetime.now(timezone.utc).isoformat()
                    })
        except Exception as e:
            logging.error(f"Error scraping SpaceWERX homepage: {e}")

        logging.info(f"Captured {len(notices)} active SpaceWERX site opportunities.")
        return notices

    def fetch_spacewerx_sam_notices(self) -> List[Dict[str, Any]]:
        """Queries SAM.gov for SpaceWERX, TACFI, and STRATFI postings."""
        if not self.sam_api_key:
            return []

        logging.info("Querying SAM.gov for SpaceWERX, TACFI, and STRATFI postings...")
        now = datetime.now(timezone.utc)
        posted_from = (now - timedelta(days=60)).strftime("%m/%d/%Y")
        posted_to = now.strftime("%m/%d/%Y")

        queries = ["SpaceWERX", "TACFI", "STRATFI"]
        seen_ids = set()
        special_calls = []

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

                    corpus = f"{title} {office} {desc[:400]}"
                    rel = self._is_space_relevant(corpus)
                    if "SPACE" in office.upper() or "SPACEWERX" in corpus.upper():
                        rel["is_relevant"] = True
                        rel["is_space"] = True

                    if not rel["is_relevant"]:
                        continue

                    seen_ids.add(nid)
                    t_low = title.lower()
                    if "stratfi" in t_low:
                        n_type = "StratFI ($15M Match)"
                    elif "tacfi" in t_low:
                        n_type = "TacFI ($1.5M Match)"
                    elif "d2p2" in t_low or "direct to phase" in t_low:
                        n_type = "Direct-to-Phase II (D2P2)"
                    else:
                        n_type = "SpaceWERX Challenge / CSO"

                    special_calls.append({
                        "source": "SpaceWERX / SAM.gov",
                        "title": title,
                        "solicitation_number": item.get("solicitationNumber", "SpaceWERX-CSO"),
                        "notice_type": n_type,
                        "agency_office": office,
                        "response_deadline": item.get("responseDeadLine", "See Notice"),
                        "classification": rel["classification"],
                        "is_golden_dome": rel["is_golden_dome"],
                        "is_space": True,
                        "url": f"https://sam.gov/opp/{nid}/view",
                        "point_of_contact": "SpaceWERX Contracting Officer",
                        "ingested_at": now.isoformat()
                    })
            except Exception as e:
                logging.error(f"Error querying SAM.gov for '{q}': {e}")

        logging.info(f"Captured {len(special_calls)} SpaceWERX notices from SAM.gov.")
        return special_calls

    def get_all_sbir_and_spacewerx(self) -> List[Dict[str, Any]]:
        return self.fetch_sbir_gov_topics() + self.fetch_spacewerx_site_opportunities() + self.fetch_spacewerx_sam_notices()
