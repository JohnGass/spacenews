import os
import re
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
from scrapers.filter_rules import evaluate_relevance

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BASE_API_URL = "https://api.congress.gov/v3"

POLICY_ANCHORS = {
    "Golden Dome & Layered Missile Defense": re.compile(
        r"\b(golden\s+dome|proliferated\s+warfighter\s+space\s+architecture|pwsa|"
        r"tracking\s+layer|transport\s+layer|tranche\s+[0-4]|hbtss|next-gen\s+opir|"
        r"glide\s+phase\s+interceptor|gpi|next\s+generation\s+interceptor|ngi|"
        r"space-based\s+interceptor|boost-phase\s+intercept|c2bmc|"
        r"missile\s+warning\s+and\s+missile\s+tracking|mw/mt)\b",
        re.IGNORECASE
    ),
    "Space Domain Awareness & Counterspace": re.compile(
        r"\b(space\s+domain\s+awareness|sda|space\s+situational\s+awareness|ssa|"
        r"counterspace|co-orbital|direct-ascent|asat|electronic\s+warfare|"
        r"directed\s+energy|cislunar\s+domain\s+awareness)\b",
        re.IGNORECASE
    ),
    "Acquisition & Force Design": re.compile(
        r"\b(tactically\s+responsive\s+space|tacrs|nssl\s+phase\s+[3-4]|"
        r"commercial\s+augmentation\s+space\s+reserve|casr|space\s+systems\s+command|"
        r"fixed-price\s+procurement|cspo)\b",
        re.IGNORECASE
    )
}

class WitnessDocLocator:
    def __init__(self, session: requests.Session):
        self.session = session
        self.headers = {"User-Agent": "Mozilla/5.0"}

    def resolve_house_pdfs(self, event_id: str) -> List[Dict[str, str]]:
        url = f"https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID={event_id}"
        pdf_docs = []
        try:
            resp = self.session.get(url, headers=self.headers, timeout=15)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                for link in soup.find_all("a", href=True):
                    href = link["href"].strip()
                    if href.lower().endswith(".pdf") and "-wstate-" in href.lower():
                        full_pdf_url = href if href.startswith("http") else urljoin("https://docs.house.gov", href)
                        pdf_docs.append({
                            "chamber": "House",
                            "witness_hint": link.get_text().strip() or "Witness Statement",
                            "pdf_url": full_pdf_url
                        })
        except Exception as e:
            logging.error(f"Error resolving House PDFs: {e}")
        return pdf_docs

    def resolve_senate_pdfs(self, committee_url: str) -> List[Dict[str, str]]:
        if not committee_url or "senate.gov" not in committee_url:
            return []
        pdf_docs = []
        try:
            resp = self.session.get(committee_url, headers=self.headers, timeout=15)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                for link in soup.find_all("a", href=True):
                    href = link["href"].strip()
                    if href.lower().endswith(".pdf") and "/imo/media/doc/" in href.lower():
                        full_url = href if href.startswith("http") else urljoin(committee_url, href)
                        pdf_docs.append({
                            "chamber": "Senate",
                            "witness_hint": link.get_text().strip() or "Senate Witness",
                            "pdf_url": full_url
                        })
        except Exception as e:
            logging.error(f"Error resolving Senate PDFs: {e}")
        return pdf_docs

class PDFQuoteExtractor:
    @staticmethod
    def extract_quotes(pdf_path: Path) -> List[Dict[str, Any]]:
        extracted = []
        try:
            reader = PdfReader(str(pdf_path))
            for page_num, page in enumerate(reader.pages, start=1):
                text = page.extract_text() or ""
                text = re.sub(r"(\w+)-\n(\w+)", r"\1\2", text)
                text = re.sub(r"\s+", " ", text).strip()
                sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text)

                for idx, sentence in enumerate(sentences):
                    for category, pattern in POLICY_ANCHORS.items():
                        match = pattern.search(sentence)
                        if match:
                            start_idx = max(0, idx - 1)
                            end_idx = min(len(sentences), idx + 2)
                            window = " ".join(sentences[start_idx:end_idx]).strip()
                            extracted.append({
                                "topic_category": category,
                                "matched_term": match.group(0),
                                "page_number": page_num,
                                "quote": window
                            })
        except Exception as e:
            logging.error(f"Error parsing PDF quotes from {pdf_path.name}: {e}")
        return extracted

class CongressGovSpaceClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.params = {"api_key": self.api_key, "format": "json"}

    def process_and_filter(self, days_back: int = 7, days_forward: int = 21) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        start_date = (now - timedelta(days=days_back)).strftime("%Y-%m-%dT00:00:00Z")
        endpoint = f"{BASE_API_URL}/committee-meeting"
        params = {"fromDateTime": start_date, "limit": 150, "sort": "date+desc"}
        
        resp = self.session.get(endpoint, params=params, timeout=20)
        if resp.status_code != 200:
            return []

        meetings = resp.json().get("committeeMeetings", [])
        filtered = []

        for m in meetings:
            title = m.get("title", "")
            event_id = str(m.get("eventId", ""))
            chamber = m.get("chamber", "")
            date = m.get("date", "")
            committees = [c.get("name", "") for c in m.get("committees", [])]
            corpus = f"{title} {' '.join(committees)}"
            
            relevance = evaluate_relevance(corpus)
            if relevance["is_relevant"]:
                filtered.append({
                    "event_id": event_id,
                    "chamber": chamber,
                    "date": date,
                    "title": title,
                    "classification": relevance["classification"],
                    "is_golden_dome": relevance["is_golden_dome"],
                    "is_space": relevance["is_space"],
                    "committees": committees,
                    "url": m.get("url", f"https://www.congress.gov/committee-meeting/{event_id}")
                })

        return filtered

class CongressionalHearingPipeline:
    def __init__(self, api_key: str):
        self.session = requests.Session()
        self.session.params = {"api_key": api_key, "format": "json"}
        self.locator = WitnessDocLocator(self.session)
        self.quote_extractor = PDFQuoteExtractor()
        self.cache_dir = Path("testimony_cache")
        self.cache_dir.mkdir(exist_ok=True)

    def process_hearing_testimony(self, hearing: Dict[str, Any]) -> Dict[str, Any]:
        event_id = hearing.get("event_id", "")
        chamber = hearing.get("chamber", "").lower()
        docs = []

        if "house" in chamber:
            docs = self.locator.resolve_house_pdfs(event_id)
        elif "senate" in chamber:
            docs = self.locator.resolve_senate_pdfs(hearing.get("url", ""))

        testimonies = []
        for doc in docs:
            pdf_url = doc["pdf_url"]
            filename = f"{event_id}_{hashlib.sha256(pdf_url.encode()).hexdigest()[:8]}.pdf"
            destination = self.cache_dir / filename

            if not destination.exists():
                try:
                    r = requests.get(pdf_url, stream=True, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
                    if r.status_code == 200:
                        with open(destination, "wb") as f:
                            for chunk in r.iter_content(8192):
                                f.write(chunk)
                except Exception:
                    continue

            quotes = self.quote_extractor.extract_quotes(destination) if destination.exists() else []
            testimonies.append({
                "witness": doc["witness_hint"],
                "pdf_url": pdf_url,
                "quotes_count": len(quotes),
                "quotes": quotes
            })

        enriched = dict(hearing)
        enriched["testimonies"] = testimonies
        return enriched
