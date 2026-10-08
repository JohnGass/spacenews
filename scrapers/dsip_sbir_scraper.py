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

# Hard exclusion filter for SpaceWERX informational fluff
SPACEWERX_NOISE_REGEX = re.compile(
    r"\b(webinar|recording|presentation|ama\b|ask me anything|faq|faqs|overview|"
    r"showcase|spotlight|definitions|helpdesk|office hours|assistance|teams channel|"
    r"slides|video|past challenges|guidance documents|suitability resources|how to apply)\b",
    re.IGNORECASE
)

class DSIPSbirScraper:
    """
    Precision Space Intelligence, ISR, C2, and Golden Dome SBIR/STTR Engine.
    1. Direct live web search of SBIR.gov across space intelligence, ISR, C2, and subsystems.
    2. Deep technical regex catching un-tagged space topics (BMC3, GMTI, OISL, RPO).
    3. Scrapes SpaceWERX rolling TACFI ($1.5M), STRATFI ($15M), and Challenge releases.
    4. Sweeps SAM.gov for SpaceWERX CSOs and Direct-to-Phase II solicitations.
    """
    SBIR_WEB_SEARCH_URL = "https://www.sbir.gov/topics"
    SAM_API_URL = "https://api.sam.gov/opportunities/v2/search"
    SPACEWERX_TACFI_URL = "https://spacewerx.us/accelerate/stratfi-tacfi/"
    SPACEWERX_VENTURES_URL = "https://spacewerx.us/ventures/overview/"

    # Expanded targeted keywords for live SBIR.gov search engine
    SEARCH_KEYWORDS = [
        "satellite",
        "spacecraft",
        "space intelligence",
        "space ISR",
        "space command and control",
        "space C2",
        "battle management space",
        "space domain awareness",
        "tactical space",
        "orbital",
        "cislunar",
        "missile tracking",
        "space electronic warfare",
        "tactically responsive space",
        "space propulsion"
    ]

    # Technical patterns that guarantee space relevance even if the word 'space' is absent
    SUBSYSTEM_TECHNICAL_PATTERNS = [
        # Space Command & Control (C2) and Battle Management
        r"\b(space\s+command\s+and\s+control|space\s+c2|bmc3|c2bmc|battle\s+management\s+space)\b",
        r"\b(jadc2\s+space|kobayashi\s+maru|forge\s+c2|ground\s+command\s+and\s+control|space\s+c4isr)\b",
        r"\b(autonomous\s+mission\s+operations|satellite\s+telemetry,\s+tracking\s+and\s+command|tt&c)\b",
        
        # Space Intelligence & Space ISR
        r"\b(space\s+intelligence|space\s+isr|tactical\s+space\s+isr|space-based\s+isr)\b",
        r"\b(space-based\s+radar|gmti|amti|moving\s+target\s+indicator|rf\s+geolocation)\b",
        r"\b(geoint\s+payload|sigint\s+payload|rf\s+sensing\s+satellite|automated\s+target\s+recognition)\b",
        
        # Payloads, Comm & Sensors
        r"\b(optical\s+inter-satellite|oisl|laser\s+communication\s+terminal|lct)\b",
        r"\b(focal\s+plane\s+array|fpa|opir|overhead\s+persistent\s+infrared|infrared\s+sensor)\b",
        r"\b(space\s+domain\s+awareness|sda|space\s+situational\s+awareness|ssa|orbital\s+custody)\b",
        r"\b(phased\s+array\s+antenna|ka-band\s+payload|x-band\s+downlink|synthetic\s+aperture\s+radar|sar\s+payload)\b",
        
        # Space Electronic Warfare & Counterspace
        r"\b(space\s+electronic\s+warfare|counterspace|space\s+control|threat\s+warning\s+in\s+space)\b",
        r"\b(gps\s+anti-jamming|resilient\s+pnt|rf\s+interference\s+mitigation)\b",
        
        # Propulsion, Orbital Regimes & Operations
        r"\b(hall\s+effect\s+thruster|electric\s+propulsion|cold\s+gas\s+thruster|green\s+propellant)\b",
        r"\b(cislunar|lagrange\s+point|vleo|very\s+low\s+earth|geostationary|geo\s+belt)\b",
        r"\b(rendezvous\s+and\s+proximity|rpo|non-cooperative\s+docking|deorbit\s+mechanism)\b",
        r"\b(in-space\s+servicing|assembly\s+and\s+manufacturing|isam|on-orbit\s+refueling)\b",
        r"\b(tactically\s+responsive\s+space|tacrs|rapid\s+reconstitution)\b",
        
        # Rad-Hard Hardware & Space Edge Compute
        r"\b(radiation-hardened|rad-hard|spaceborne\s+edge|flight\s+computer|space-qualified|cubesat|smallsat)\b",
        
        # Golden Dome & Layered Missile Defense
        r"\b(glide\s+phase\s+interceptor|hbtss|missile\s+tracking|hypersonic\s+tracking)\b"
    ]
    COMPILED_TECH_REGEX = re.compile("|".join(SUBSYSTEM_TECHNICAL_PATTERNS), re.IGNORECASE)

    def __init__(self):
        self.sam_api_key = os.getenv("SAM_GOV_API_KEY")
        self.scraper_api_key = os.getenv("SCRAPER_API_KEY")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        })

    def _fetch_page(self, url: str) -> str:
        """Fetches page directly with ScraperAPI fallback."""
        try:
            resp = self.session.get(url, timeout=12)
            if resp.status_code == 200 and len(resp.text) > 1000:
                return resp.text
        except Exception:
            pass

        if self.scraper_api_key:
            try:
                proxy_url = f"https://api.scraperapi.com?api_key={self.scraper_api_key}&url={quote(url)}"
                resp = self.session.get(proxy_url, timeout=25)
                if resp.status_code == 200:
                    return resp.text
            except Exception as e:
                logging.error(f"ScraperAPI failed for {url}: {e}")
        return ""

    def _is_space_relevant(self, text_corpus: str) -> dict:
        """
        Dual-gate evaluation:
        Gate 1: Standard domain rules from filter_rules.py
        Gate 2: Technical space subsystem / C2 / ISR / Subsystem regex
        """
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

    def scrape_live_sbir_gov(self) -> List[Dict[str, Any]]:
        """
        Scrapes the live SBIR.gov search engine across all targeted space, C2, and ISR terms.
        Extracts active topic numbers, titles, close dates, and direct links to /topics/{id}.
        """
        logging.info(f"Scraping live SBIR.gov search across {len(self.SEARCH_KEYWORDS)} space & C2 keywords...")
        topics = []
        seen_urls: Set[str] = set()

        for kw in self.SEARCH_KEYWORDS:
            target_url = f"{self.SBIR_WEB_SEARCH_URL}?keywords={quote(kw)}&status=Open"
            logging.info(f"Querying SBIR.gov for '{kw}'...")
            html = self._fetch_page(target_url)
            if not html:
                continue

            soup = BeautifulSoup(html, "html.parser")
            links = soup.find_all("a", href=re.compile(r"/topics/\d+"))

            for a in links:
                title = a.get_text(strip=True)
                href = a["href"].strip()
                full_url = f"https://www.sbir.gov{href}" if href.startswith("/") else href

                if len(title) < 10 or full_url in seen_urls:
                    continue

                parent_row = a.find_parent(["div", "article", "li"])
                row_text = parent_row.get_text(" ", strip=True) if parent_row else title

                rel = self._is_space_relevant(f"{title} {row_text[:500]}")
                if not rel["is_relevant"]:
                    continue

                seen_urls.add(full_url)

                # Extract close date
                close_m = re.search(r'Close\s*Date:\s*([A-Za-z]+\s+\d{1,2},\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})', row_text, re.I)
                close_date = close_m.group(1).strip() if close_m else "See SBIR.gov"

                # Identify military branch / agency
                branch = "DoD"
                row_lower = row_text.lower()
                if "space force" in row_lower or "ussf" in row_lower:
                    branch = "USSF / Space Force"
                elif "air force" in row_lower or "daf" in row_lower:
                    branch = "DAF / Air Force"
                elif "missile defense" in row_lower or "mda" in row_lower:
                    branch = "Missile Defense Agency"
                elif "darpa" in row_lower:
                    branch = "DARPA"
                elif "nasa" in row_lower:
                    branch = "NASA"

                # Extract topic code or fallback to topic ID
                topic_num_m = re.search(r'\b([A-Z0-9]+-\d+|[A-Z0-9]+-[A-Z0-9]+)\b', row_text)
                topic_num = topic_num_m.group(1) if topic_num_m else f"Topic #{href.split('/')[-1]}"

                phase = "Phase I"
                if "phase ii" in row_lower:
                    phase = "Phase II"

                # Tag specific topic subtype if relevant
                notice_type = f"SBIR Topic ({phase})"
                if "c2" in title.lower() or "command and control" in title.lower() or "bmc3" in title.lower():
                    notice_type = f"Space C2 Topic ({phase})"
                elif "isr" in title.lower() or "intelligence" in title.lower() or "sensing" in title.lower():
                    notice_type = f"Space ISR Topic ({phase})"

                topics.append({
                    "source": f"SBIR.gov / {branch}",
                    "title": title,
                    "solicitation_number": topic_num,
                    "notice_type": notice_type,
                    "agency_office": branch,
                    "response_deadline": close_date,
                    "classification": rel["classification"],
                    "is_golden_dome": rel["is_golden_dome"],
                    "is_space": True,
                    "url": full_url,
                    "point_of_contact": "See Topic details in DSIP",
                    "ingested_at": datetime.now(timezone.utc).isoformat()
                })

        logging.info(f"Captured {len(topics)} active space, C2, and ISR topics from SBIR.gov.")
        return topics

    def scrape_spacewerx_genuine_opportunities(self) -> List[Dict[str, Any]]:
        """
        Scrapes SpaceWERX, strictly filtering out recordings, webinars, AMA decks,
        and extracting only genuine Notice of Opportunity (NOO) and TACFI/STRATFI solicitations.
        """
        logging.info("Scraping SpaceWERX for verified active solicitations...")
        notices = []
        targets = [self.SPACEWERX_TACFI_URL, self.SPACEWERX_VENTURES_URL]
        seen_titles = set()

        for target in targets:
            html = self._fetch_page(target)
            if not html:
                continue

            soup = BeautifulSoup(html, "html.parser")
            elements = soup.find_all(["h2", "h3", "h4", "div", "p"])

            for elem in elements:
                text = elem.get_text(" ", strip=True)
                if len(text) < 25 or len(text) > 400:
                    continue

                if SPACEWERX_NOISE_REGEX.search(text):
                    continue

                text_lower = text.lower()
                is_tacfi_noo = "tacfi" in text_lower and ("notice of opportunity" in text_lower or "noo" in text_lower or "open" in text_lower)
                is_stratfi_call = "stratfi" in text_lower and ("open" in text_lower or "notice" in text_lower or "solicitation" in text_lower)
                is_challenge = "challenge" in text_lower and ("open" in text_lower or "accepting" in text_lower)

                if not (is_tacfi_noo or is_stratfi_call or is_challenge):
                    continue

                a_tag = elem.find("a", href=True) if elem.name != "a" else elem
                href = a_tag["href"] if a_tag else target
                full_url = href if href.startswith("http") else f"https://spacewerx.us{href}"

                lines = [l.strip() for l in text.split("  ") if len(l.strip()) > 10]
                title = lines[0] if lines else text[:120]

                t_key = title[:35].lower()
                if t_key in seen_titles:
                    continue
                seen_titles.add(t_key)

                if is_stratfi_call:
                    notice_type = "STRATFI ($15M Matching)"
                elif is_tacfi_noo:
                    notice_type = "TACFI Notice of Opportunity (Rolling)"
                else:
                    notice_type = "SpaceWERX Challenge"

                notices.append({
                    "source": "SpaceWERX",
                    "title": title[:140],
                    "solicitation_number": "PY26.2-NOO",
                    "notice_type": notice_type,
                    "agency_office": "USSF / SpaceWERX",
                    "response_deadline": "Continuous / Rolling Submission",
                    "classification": "Space Relevant",
                    "is_golden_dome": False,
                    "is_space": True,
                    "url": full_url,
                    "point_of_contact": "SpaceWERX Ventures Directorate",
                    "ingested_at": datetime.now(timezone.utc).isoformat()
                })

        logging.info(f"Captured {len(notices)} genuine SpaceWERX solicitations.")
        return notices

    def fetch_spacewerx_sam_csos(self) -> List[Dict[str, Any]]:
        """Pulls authentic SpaceWERX CSOs and Direct-to-Phase II solicitations from SAM.gov."""
        if not self.sam_api_key:
            return []

        logging.info("Querying SAM.gov for SpaceWERX CSOs, C2, and D2P2 notices...")
        now = datetime.now(timezone.utc)
        posted_from = (now - timedelta(days=60)).strftime("%m/%d/%Y")
        posted_to = now.strftime("%m/%d/%Y")

        queries = ['"SpaceWERX"', '"Space Systems Command" AND "D2P2"', '"Space Systems Command" AND "C2"']
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

                    if SPACEWERX_NOISE_REGEX.search(title):
                        continue

                    corpus = f"{title} {office} {desc[:400]}"
                    rel = self._is_space_relevant(corpus)
                    if not rel["is_relevant"]:
                        continue

                    seen_ids.add(nid)
                    t_low = title.lower()
                    if "d2p2" in t_low or "direct to phase" in t_low:
                        n_type = "Direct-to-Phase II (D2P2)"
                    elif "stratfi" in t_low:
                        n_type = "StratFI ($15M Match)"
                    elif "tacfi" in t_low:
                        n_type = "TacFI ($1.5M Match)"
                    elif "c2" in t_low or "command and control" in t_low:
                        n_type = "Space C2 Solicitation"
                    else:
                        n_type = "SpaceWERX Challenge / CSO"

                    results.append({
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

        logging.info(f"Captured {len(results)} SpaceWERX notices from SAM.gov.")
        return results

    def get_all_sbir_and_spacewerx(self) -> List[Dict[str, Any]]:
        return self.scrape_live_sbir_gov() + self.scrape_spacewerx_genuine_opportunities() + self.fetch_spacewerx_sam_csos()
