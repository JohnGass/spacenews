import os
import re
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Set
import xml.etree.ElementTree as ET
import requests
from scrapers.filter_rules import evaluate_relevance

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class DSIPSbirScraper:
    """
    Precision Space & Golden Dome SBIR/STTR Ingestion Engine.
    Monitors:
    1. SBA / DSIP Topic API across DoD Components (USSF, MDA, DARPA, DAF, NASA)
    2. Deep Technical Space Subsystem Taxonomy (detects topics omitting 'space')
    3. SpaceWERX TacFI, StratFI, and D2P2 Special Calls
    """
    TOPICS_API_URL = "https://api.www.sbir.gov/public/api/topics"
    SOLICITATIONS_API_URL = "https://api.www.sbir.gov/public/api/solicitations"
    SAM_API_URL = "https://api.sam.gov/opportunities/v2/search"

    # Targeted Agencies & Military Components
    TARGET_AGENCIES = ["DOD", "NASA"]
    TARGET_BRANCHES = [
        "SPACE FORCE",
        "MISSILE DEFENSE AGENCY",
        "DEFENSE ADVANCED RESEARCH PROJECTS AGENCY",
        "AIR FORCE",
        "NATIONAL AERONAUTICS AND SPACE ADMINISTRATION"
    ]

    # Technical Subsystem Keywords (topics that belong to space but omit the word 'space')
    SUBSYSTEM_TECHNICAL_PATTERNS = [
        # Propulsion & Attitude Control
        r"\b(hall\s+effect\s+thruster|electric\s+propulsion|cold\s+gas\s+thruster|green\s+propellant)\b",
        r"\b(star\s+tracker|reaction\s+wheel|control\s+moment\s+gyro|orbital\s+insertion)\b",
        r"\b(cryogenic\s+fluid\s+management|apogee\s+kick\s+motor|chemical\s+propulsion)\b",
        # Payloads, Comm & Sensors
        r"\b(optical\s+inter-satellite|oisl|laser\s+communication\s+terminal|lct)\b",
        r"\b(focal\s+plane\s+array|fpa|opir|persistent\s+infrared|infrared\s+sensor)\b",
        r"\b(space\s+domain\s+awareness|sda|space\s+situational\s+awareness|ssa)\b",
        r"\b(phased\s+array\s+antenna|ka-band\s+payload|x-band\s+downlink|telemetry,\s+tracking)\b",
        r"\b(synthetic\s+aperture\s+radar|sar\s+payload|hyperspectral\s+sensor)\b",
        # Orbital Regimes & Mechanics
        r"\b(cislunar|lagrange\s+point|vleo|very\s+low\s+earth|geostationary|geo\s+belt)\b",
        r"\b(rendezvous\s+and\s+proximity|rpo|non-cooperative\s+docking|deorbit\s+mechanism)\b",
        r"\b(in-space\s+servicing|assembly\s+and\s+manufacturing|isam|on-orbit\s+refueling)\b",
        # Rad-Hard Hardware & Space Edge Compute
        r"\b(radiation-hardened|rad-hard|single-event\s+upset|seu\s+mitigation)\b",
        r"\b(spaceborne\s+edge|flight\s+computer|space-qualified|cubesat\s+bus|smallsat\s+bus)\b",
        # Golden Dome & Missile Defense Specific
        r"\b(glide\s+phase\s+interceptor|hbtss|missile\s+tracking\s+sensor|discrimination\s+algorithm)\b",
        r"\b(hypersonic\s+tracking|boost-phase\s+tracking|c2bmc\s+integration)\b"
    ]

    COMPILED_TECH_REGEX = re.compile("|".join(SUBSYSTEM_TECHNICAL_PATTERNS), re.IGNORECASE)

    def __init__(self):
        self.sam_api_key = os.getenv("SAM_GOV_API_KEY")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) SpaceIntelPipeline/3.0",
            "Accept": "application/json, text/plain, */*"
        })

    def _determine_lifecycle_stage(self, item: dict) -> str:
        """Identifies whether a topic is Pre-Release, Open, or Special Matching."""
        status = str(item.get("status") or "").lower()
        title = str(item.get("topic_title") or item.get("title") or "").lower()
        sol_title = str(item.get("solicitation_title") or "").lower()

        if "pre-release" in status or "prerelease" in status or "pre-release" in sol_title:
            return "Pre-Release (Contact TPOC)"
        if "tacfi" in title or "tacfi" in sol_title:
            return "TacFI ($1.5M Match)"
        if "stratfi" in title or "stratfi" in sol_title:
            return "StratFI ($15M Match)"
        if "direct to phase ii" in title or "d2p2" in title or "direct to phase ii" in sol_title:
            return "Direct-to-Phase II (D2P2)"
        if "open" in status or item.get("open") == 1 or item.get("open") == "1":
            return "Open for Submission"
        return "Active Topic"

    def _is_space_or_subsystem_relevant(self, text_corpus: str) -> dict:
        """
        Dual-gate evaluation:
        Gate 1: Standard domain rules (filter_rules.py)
        Gate 2: Deep subsystem vocabulary regex (catches topics without the word 'space')
        """
        # Run standard filter
        std_eval = evaluate_relevance(text_corpus)
        if std_eval["is_relevant"]:
            return std_eval

        # Run technical subsystem check
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

    def fetch_targeted_topics(self) -> List[Dict[str, Any]]:
        """
        Sweeps SBA / DSIP Topic API targeting space components and technical queries.
        """
        logging.info("Sweeping DSIP / SBIR topics across DoD space components and technical subsystems...")
        seen_ids: Set[str] = set()
        topics = []

        # Strategy A: Query by targeted space keywords across all agencies
        broad_keywords = [
            "satellite", "spacecraft", "orbital", "cislunar", "launch vehicle",
            "space domain awareness", "optical inter-satellite", "hypersonic tracking",
            "hall thruster", "star tracker", "rad-hard", "payload"
        ]

        for kw in broad_keywords:
            try:
                params = {"keyword": kw, "open": "1", "rows": "50"}
                resp = self.session.get(self.TOPICS_API_URL, params=params, timeout=18)
                if resp.status_code != 200:
                    continue

                for item in resp.json():
                    topic_id = str(item.get("topic_number") or item.get("topic_id") or "")
                    title = item.get("topic_title") or item.get("title") or ""
                    if not topic_id or topic_id in seen_ids:
                        continue

                    agency = item.get("agency") or "DoD"
                    branch = item.get("branch") or ""
                    desc = item.get("topic_description") or item.get("description") or ""

                    corpus = f"{title} {agency} {branch} {desc[:600]}"
                    rel = self._is_space_or_subsystem_relevant(corpus)
                    if not rel["is_relevant"]:
                        continue

                    seen_ids.add(topic_id)
                    stage = self._determine_lifecycle_stage(item)
                    link = item.get("sbir_topic_link") or item.get("topic_link") or "https://www.dsip.defense.gov"

                    # Extract TPOC info if available
                    tpoc_info = item.get("tpoc_name") or "See Topic / SIT in DSIP"
                    if item.get("tpoc_email"):
                        tpoc_info += f" ({item.get('tpoc_email')})"

                    topics.append({
                        "source": f"SBIR / {branch or agency}",
                        "title": title,
                        "solicitation_number": topic_id,
                        "notice_type": stage,
                        "agency_office": f"{agency} - {branch}" if branch else agency,
                        "response_deadline": item.get("close_date") or item.get("expiration_date") or "See Schedule",
                        "classification": rel["classification"],
                        "is_golden_dome": rel["is_golden_dome"],
                        "is_space": True,
                        "url": link,
                        "point_of_contact": tpoc_info,
                        "ingested_at": datetime.now(timezone.utc).isoformat()
                    })
            except Exception as e:
                logging.error(f"Error querying SBIR Topics API for '{kw}': {e}")

        # Strategy B: Component Sweeps (Pull all topics for USSF, MDA, and NASA)
        for agency in self.TARGET_AGENCIES:
            try:
                params = {"agency": agency, "open": "1", "rows": "100"}
                resp = self.session.get(self.TOPICS_API_URL, params=params, timeout=18)
                if resp.status_code != 200:
                    continue

                for item in resp.json():
                    topic_id = str(item.get("topic_number") or item.get("topic_id") or "")
                    if not topic_id or topic_id in seen_ids:
                        continue

                    title = item.get("topic_title") or item.get("title") or ""
                    branch = str(item.get("branch") or "").upper()
                    desc = item.get("topic_description") or item.get("description") or ""

                    # Automatic pass for Space Force or NASA topics
                    is_auto_space = "SPACE" in branch or agency == "NASA"
                    corpus = f"{title} {agency} {branch} {desc[:600]}"
                    rel = self._is_space_or_subsystem_relevant(corpus)

                    if not is_auto_space and not rel["is_relevant"]:
                        continue

                    seen_ids.add(topic_id)
                    stage = self._determine_lifecycle_stage(item)
                    link = item.get("sbir_topic_link") or item.get("topic_link") or "https://www.dsip.defense.gov"

                    tpoc_info = item.get("tpoc_name") or "See DSIP Topic Details"
                    if item.get("tpoc_email"):
                        tpoc_info += f" ({item.get('tpoc_email')})"

                    topics.append({
                        "source": f"SBIR / {branch or agency}",
                        "title": title,
                        "solicitation_number": topic_id,
                        "notice_type": stage,
                        "agency_office": f"{agency} - {branch}" if branch else agency,
                        "response_deadline": item.get("close_date") or "See Schedule",
                        "classification": rel["classification"],
                        "is_golden_dome": rel["is_golden_dome"],
                        "is_space": True,
                        "url": link,
                        "point_of_contact": tpoc_info,
                        "ingested_at": datetime.now(timezone.utc).isoformat()
                    })
            except Exception as e:
                logging.error(f"Error executing component sweep for {agency}: {e}")

        logging.info(f"Captured {len(topics)} high-signal space/missile defense SBIR topics.")
        return topics

    def fetch_spacewerx_and_special_calls(self) -> List[Dict[str, Any]]:
        """
        Pulls SpaceWERX Open Topics, TacFI, StratFI, and D2P2 notices from SAM.gov.
        """
        if not self.sam_api_key:
            return []

        logging.info("Querying SAM.gov for SpaceWERX Open Topic, TacFI, and StratFI calls...")
        now = datetime.now(timezone.utc)
        posted_from = (now - timedelta(days=60)).strftime("%m/%d/%Y")
        posted_to = now.strftime("%m/%d/%Y")

        queries = [
            '"SpaceWERX"',
            '"Space Systems Command" AND "SBIR"',
            '"Space Systems Command" AND "StratFI"',
            '"Space Force" AND "TacFI"'
        ]
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

                    rel = self._is_space_or_subsystem_relevant(f"{title} {office} {desc[:400]}")
                    if not rel["is_relevant"]:
                        continue

                    seen_ids.add(nid)
                    title_lower = title.lower()
                    if "stratfi" in title_lower:
                        notice_type = "StratFI ($15M Match)"
                    elif "tacfi" in title_lower:
                        notice_type = "TacFI ($1.5M Match)"
                    elif "d2p2" in title_lower or "direct to phase" in title_lower:
                        notice_type = "Direct-to-Phase II (D2P2)"
                    else:
                        notice_type = "SpaceWERX Challenge"

                    special_calls.append({
                        "source": "SpaceWERX / DAF",
                        "title": title,
                        "solicitation_number": item.get("solicitationNumber", "SpaceWERX"),
                        "notice_type": notice_type,
                        "agency_office": office,
                        "response_deadline": item.get("responseDeadLine", "See Listing"),
                        "classification": rel["classification"],
                        "is_golden_dome": rel["is_golden_dome"],
                        "is_space": True,
                        "url": f"https://sam.gov/opp/{nid}/view",
                        "point_of_contact": "SpaceWERX Ventures Directorate",
                        "ingested_at": now.isoformat()
                    })
            except Exception as e:
                logging.error(f"Error querying SpaceWERX calls: {e}")

        logging.info(f"Captured {len(special_calls)} SpaceWERX / TacFI / StratFI notices.")
        return special_calls

    def get_all_sbir_and_spacewerx(self) -> List[Dict[str, Any]]:
        return self.fetch_targeted_topics() + self.fetch_spacewerx_and_special_calls()
