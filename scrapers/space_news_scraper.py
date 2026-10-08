import os
import re
import base64
import logging
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import List, Dict, Any, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote
import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup
from scrapers.filter_rules import evaluate_relevance

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def resolve_gnews_url(gnews_url: str) -> str:
    """Extracts the real target destination URL from Google News base64 links."""
    match = re.search(r'/articles/([A-Za-z0-9_\-]+)', gnews_url)
    if not match:
        return gnews_url
    b64_str = match.group(1)
    b64_str += '=' * (-len(b64_str) % 4)
    try:
        decoded = base64.urlsafe_b64decode(b64_str)
        urls = re.findall(rb'https?://[^\x00-\x1f\x7f-\xff\s"\'<>]+', decoded)
        if urls:
            return urls[0].decode('utf-8', 'ignore')
    except Exception:
        pass
    return gnews_url

def make_translated_link(url: str, src_lang: str = "zh-CN", target_lang: str = "en") -> str:
    """Wraps URL in Google Translate web proxy so it opens in full English when clicked."""
    real_url = resolve_gnews_url(url)
    if "translate.google.com" in real_url:
        return real_url
    return f"https://translate.google.com/translate?sl={src_lang}&tl={target_lang}&u={quote(real_url)}"

def translate_zh_to_en(text: str) -> str:
    """Translates Chinese text into English using automated translation relay."""
    if not text or not re.search(r'[\u4e00-\u9fff]', text):
        return text
    # 1. Primary Google Translate API endpoint
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "client": "gtx",
            "sl": "zh-CN",
            "tl": "en",
            "dt": "t",
            "q": text[:1500]
        }
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(url, params=params, headers=headers, timeout=6)
        if resp.status_code == 200:
            data = resp.json()
            if data and isinstance(data, list) and data[0]:
                translated = "".join(seg[0] for seg in data[0] if seg and seg[0])
                if translated.strip():
                    return translated.strip()
    except Exception:
        pass

    # 2. Free translation fallback
    try:
        url = "https://api.mymemory.translated.net/get"
        params = {"q": text[:500], "langpair": "zh|en"}
        resp = requests.get(url, params=params, timeout=5)
        if resp.status_code == 200:
            res = resp.json().get("responseData", {}).get("translatedText", "")
            if res and not res.startswith("MYMEMORY WARNING"):
                return res.strip()
    except Exception:
        pass

    return text

def is_within_14_days(date_str: str) -> bool:
    """Strictly enforces rolling 14-day cutoff across RFC, ISO, and standard dates."""
    if not date_str:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    s = date_str.strip()
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt >= cutoff
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt >= cutoff
    except Exception:
        pass
    match = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', s)
    if match:
        try:
            year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
            dt = datetime(year, month, day, tzinfo=timezone.utc)
            return dt >= cutoff
        except Exception:
            pass
    return False

class SpaceNewsScraper:
    """
    Broad-Spectrum Multithreaded Space Intelligence Engine.
    Polls 75+ global feeds concurrently, translates Chinese-language intelligence into English,
    wraps Chinese-language links in web translation proxies, and enforces a strict rolling 14-day window.
    """
    FEEDS = [
        # --- China Space Tracking & Doctrine ---
        {"name": "China in Space", "url": "https://www.china-in-space.com/feed", "tier": "PRC Space Analysis"},
        {"name": "South China Morning Post", "url": "https://news.google.com/rss/search?q=site:scmp.com+space+when:14d&hl=en-US&gl=US&ceid=US:en", "tier": "China Space Tracking"},
        {"name": "China Daily", "url": "https://news.google.com/rss/search?q=site:chinadaily.com.cn+space+when:14d&hl=en-US&gl=US&ceid=US:en", "tier": "PRC State Media"},
        {"name": "Xinhua News", "url": "https://news.google.com/rss/search?q=site:xinhuanet.com+space+when:14d&hl=en-US&gl=US&ceid=US:en", "tier": "PRC Official Wire"},
        {"name": "Taibo English", "url": "https://news.google.com/rss/search?q=site:en.taibo.cn+when:14d&hl=en-US&gl=US&ceid=US:en", "tier": "Chinese Commercial Space"},

        # --- National Security Space, Pentagon & Defense Trade ---
        {"name": "Breaking Defense", "url": "https://breakingdefense.com/category/space/feed/", "tier": "National Security Space"},
        {"name": "Defense Scoop", "url": "https://defensescoop.com/feed/", "tier": "Defense Tech & USSF"},
        {"name": "Air & Space Forces", "url": "https://www.airandspaceforces.com/category/space/feed/", "tier": "USSF Force Design"},
        {"name": "Defense News", "url": "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml", "tier": "Defense Acquisition"},
        {"name": "Defense One", "url": "https://www.defenseone.com/rss/all/", "tier": "Pentagon Strategy"},
        {"name": "C4ISRNET", "url": "https://www.c4isrnet.com/arc/outboundfeeds/rss/?outputType=xml", "tier": "Space C2 & Sensors"},
        {"name": "The War Zone", "url": "https://www.twz.com/feed", "tier": "Tactical Hardware"},
        {"name": "Militarnyi", "url": "https://mil.in.ua/en/feed/", "tier": "Tactical Defense"},
        {"name": "National Defense", "url": "https://www.nationaldefensemagazine.org/rss/all", "tier": "Defense Industrial Base"},
        {"name": "DVIDS Space Force", "url": "https://www.dvidshub.net/rss/tags/space%20force", "tier": "USSF Operational Wire"},
        {"name": "DVIDS USSPACECOM", "url": "https://www.dvidshub.net/rss/unit/5284", "tier": "USSPACECOM Operations"},
        {"name": "Jamestown Foundation", "url": "https://jamestown.org/feed/", "tier": "Eurasia & China Defense"},

        # --- Commercial Space, Industry Wire & Trade Press ---
        {"name": "SpaceNews", "url": "https://spacenews.com/feed/", "tier": "Global Industry Wire"},
        {"name": "Payload Space", "url": "https://payloadspace.com/feed/", "tier": "Space Economy & Venture"},
        {"name": "Aviation Week", "url": "https://aviationweek.com/rss.xml", "tier": "Aerospace & Defense"},
        {"name": "Flight Global", "url": "https://www.flightglobal.com/rss/space/117.rss", "tier": "Aerospace Industry"},
        {"name": "Aerospace America", "url": "https://aerospaceamerica.aiaa.org/feed/", "tier": "AIAA Engineering"},
        {"name": "SatNews", "url": "https://news.satnews.com/feed/", "tier": "Satellite & Payloads"},
        {"name": "Via Satellite", "url": "https://www.satellitetoday.com/feed/", "tier": "COMSATCOM"},
        {"name": "Smallsat News", "url": "https://news.google.com/rss/search?q=site:smallsatnews.com+when:14d&hl=en-US&gl=US&ceid=US:en", "tier": "Smallsats"},
        {"name": "SpaceWatch.Global", "url": "https://spacewatch.global/feed/", "tier": "Geopolitical Commercial"},
        {"name": "SpaceQ", "url": "https://spaceq.ca/feed/", "tier": "Canadian & Allied Space"},
        {"name": "Startup Daily", "url": "https://www.startupdaily.net/category/sectors/space/feed/", "tier": "Indo-Pacific Venture"},

        # --- Launch Operations, Engineering & Hardware ---
        {"name": "Ars Technica Space", "url": "https://arstechnica.com/space/feed/", "tier": "Investigative Launch"},
        {"name": "Spaceflight Now", "url": "https://spaceflightnow.com/feed/", "tier": "Mission Ops & Launch"},
        {"name": "NASASpaceFlight", "url": "https://www.nasaspaceflight.com/feed/", "tier": "Vehicle Testing & Hardware"},
        {"name": "Universe Today", "url": "https://www.universetoday.com/feed/", "tier": "Spaceflight & Tech"},
        {"name": "Space.com", "url": "https://www.space.com/feeds/all", "tier": "Spaceflight News"},
        {"name": "SpaceRef", "url": "https://spaceref.com/feed/", "tier": "Civil & Tech Wire"},
        {"name": "Douglas Messier", "url": "https://parabolicarc.com/feed/", "tier": "Parabolic Arc / Analysis"},

        # --- Strategic Analysis & Policy ---
        {"name": "The Space Review", "url": "https://www.thespacereview.com/feed.xml", "tier": "Strategic Analysis"},
        {"name": "SpacePolicyOnline", "url": "https://spacepolicyonline.com/feed/", "tier": "Policy & Hill"},
        {"name": "The Conversation", "url": "https://theconversation.com/us/topics/space-31/articles.atom", "tier": "Academic Analysis"},
        {"name": "Scientific American", "url": "http://rss.sciam.com/ScientificAmerican-Space", "tier": "Science & Exploration"},
        {"name": "Earthsky", "url": "https://earthsky.org/feed/", "tier": "Orbital Science"},

        # --- Florida & Regional Spaceport News ---
        {"name": "Florida Today", "url": "https://rssfeeds.floridatoday.com/floridatoday/space", "tier": "Cape Canaveral Wire"},
        {"name": "Spectrum News 13", "url": "https://www.mynews13.com/services/rss/feed.space.rss", "tier": "Central Florida Space"},
        {"name": "Bay News 9", "url": "https://news.google.com/rss/search?q=site:baynews9.com+space+when:14d&hl=en-US&gl=US&ceid=US:en", "tier": "Florida Space Coast"},
        {"name": "Bradenton Herald", "url": "https://news.google.com/rss/search?q=site:bradenton.com+space+when:14d&hl=en-US&gl=US&ceid=US:en", "tier": "Florida Local"},
        {"name": "Charlotte Observer", "url": "https://news.google.com/rss/search?q=site:charlotteobserver.com+(aerospace+OR+space)+when:14d&hl=en-US&gl=US&ceid=US:en", "tier": "Regional Aerospace"},
        {"name": "Dayton Daily News", "url": "https://news.google.com/rss/search?q=site:daytondailynews.com+(space+OR+nasic)+when:14d&hl=en-US&gl=US&ceid=US:en", "tier": "Wright-Patt / NSIC"},

        # --- Global Mainstream, Business & Geopolitical Wires ---
        {"name": "Wall Street Journal", "url": "https://news.google.com/rss/search?q=site:wsj.com+space+when:14d&hl=en-US&gl=US&ceid=US:en", "tier": "Financial & Aerospace"},
        {"name": "New York Times", "url": "https://rss.nytimes.com/services/xml/rss/nyt/Space.xml", "tier": "Mainstream Wire"},
        {"name": "Reuters", "url": "https://news.google.com/rss/search?q=site:reuters.com+space+when:14d&hl=en-US&gl=US&ceid=US:en", "tier": "Global Wire"},
        {"name": "Politico", "url": "https://news.google.com/rss/search?q=site:politico.com+(%22space+force%22+OR+satellite)+when:14d&hl=en-US&gl=US&ceid=US:en", "tier": "Hill Policy"},
        {"name": "Axios", "url": "https://news.google.com/rss/search?q=site:axios.com+space+when:14d&hl=en-US&gl=US&ceid=US:en", "tier": "Space Economy"},
        {"name": "CNBC", "url": "https://news.google.com/rss/search?q=site:cnbc.com+space+when:14d&hl=en-US&gl=US&ceid=US:en", "tier": "Venture & Public Primes"},
        {"name": "CNN Space", "url": "http://rss.cnn.com/rss/edition_space.rss", "tier": "Mainstream Wire"},
        {"name": "BBC News", "url": "http://feeds.bbci.co.uk/news/science_and_environment/rss.xml", "tier": "UK & Global Science"},
        {"name": "GeekWire", "url": "https://www.geekwire.com/aerospace/feed/", "tier": "Pacific NW Aerospace"},
        {"name": "Gizmodo", "url": "https://gizmodo.com/tag/space/rss", "tier": "Tech & Space"},
        {"name": "LA Times", "url": "https://news.google.com/rss/search?q=site:latimes.com+(aerospace+OR+%22space+force%22)+when:14d&hl=en-US&gl=US&ceid=US:en", "tier": "SoCal Aerospace"},

        # --- Allied & Civil Agencies ---
        {"name": "European Spaceflight", "url": "https://europeanspaceflight.com/feed/", "tier": "European Launch"},
        {"name": "ESA", "url": "https://www.esa.int/rssfeed/Our_Activities/Space_Safety", "tier": "European Space Agency"},
        {"name": "Gov.UK / UKSA", "url": "https://www.gov.uk/government/organisations/uk-space-agency.atom", "tier": "UK Defense & Civil"},
        {"name": "Economic Times", "url": "https://economictimes.indiatimes.com/news/science/rssfeeds/3983049.cms", "tier": "ISRO & Indo-Pacific"},
        {"name": "NDTV", "url": "https://news.google.com/rss/search?q=site:ndtv.com+(isro+OR+space)+when:14d&hl=en-IN&gl=IN&ceid=IN:en", "tier": "South Asian Space"},
        {"name": "NASA HQ Releases", "url": "https://www.nasa.gov/news-release/feed/", "tier": "Civil Agency"},
        {"name": "CASIS / ISS National Lab", "url": "https://www.issnationallab.org/feed/", "tier": "Microgravity & LEO"}
    ]

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        })

    def _clean_text(self, text: str) -> str:
        if not text:
            return ""
        clean = re.sub(r"<[^>]+>", "", text)
        clean = clean.replace("&nbsp;", " ").replace("&amp;", "&").replace("&quot;", '"').replace("&#039;", "'")
        return re.sub(r"\s+", " ", clean).strip()

    def _classify_topic(self, title: str, description: str, source_name: str = "") -> str:
        corpus = f"{title} {description}".lower()

        if "china in space" in source_name.lower() or "taibo" in source_name.lower():
            return "China"

        exec_pattern = re.compile(
            r"\b(names|appoints|taps|hires|named|executive|c-suite|ceo|coo|cfo|cto|president|"
            r"board\s+of\s+directors|merger|merges|acquires|acquisition|earnings|quarterly|"
            r"revenue|profit|loss|shares|nasdaq|nyse|valuation|spac|funding\s+round|series\s+[a-d])\b",
            re.IGNORECASE
        )
        if exec_pattern.search(title):
            return "Commercial"

        if re.search(r"\b(china|chinese|cnsa|beijing|tiangong|chang'e|long\s*march|casc|casic|landspace|deep\s*blue|yuanwang|tianwen|qianfan)\b", corpus, re.I):
            return "China"
        if re.search(r"\b(russia|russian|roscosmos|moscow|angara|soyuz|vostochny|plesetsk|glonass)\b", corpus, re.I):
            return "Russia"

        if re.search(r"\b(congress|senate|house|hasc|sasc|appropriations|ndaa|lawmaker|capitol\s*hill|legislation|white\s*house|space\s*council|faa|fcc|treaty|budget|regulatory|commerce\s*department)\b", corpus, re.I):
            return "Policy & Hill"

        if re.search(r"\b(launch|launches|launched|launching|rocket|booster|liftoff|starship|falcon\s*9|falcon\s*heavy|new\s*glenn|vulcan|sls|super\s*heavy|electron|static\s*fire|engine\s*test|hot\s*fire|pad\s*[0-9a-zA-Z]+|spaceport|cape\s*canaveral|vandenberg|kourou)\b", corpus, re.I):
            return "Launch"

        if re.search(r"\b(spacecraft|satellite|satellites|constellation|bus|rf-sensor|sensor|sensors|payload|on-orbit|in-orbit|orbital\s*target|orbital\s*debris|rendezvous|docking|proximity|rpo|space\s*domain\s*awareness|sda|ssa|space\s*tracking|maneuver|deorbit|flight\s*operations)\b", corpus, re.I):
            return "Spacecraft & Ops"

        if re.search(r"\b(optical\s*comm|laser|quantum|nuclear|solar\s*array|ai|edge\s*compute|isam|in-space\s*servicing|refueling|materials|additive)\b", corpus, re.I):
            return "Technology"

        if re.search(r"\b(commercial|venture|startup|investment|spacex|blue\s*origin|rocket\s*lab|astrobotic|axiom|planet\s*labs|spire|capella|hawkeye)\b", corpus, re.I):
            return "Commercial"

        if re.search(r"\b(esa|europe|european|jaxa|japan|isro|india|uae|australia|uk\s*space|artemis\s*accords)\b", corpus, re.I):
            return "International"

        return "National Security"

    def _parse_items(self, content: str) -> List[dict]:
        items = []
        try:
            root = ET.fromstring(content)
            entries = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
            for item in entries:
                title = (item.findtext("title") or item.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
                link = ""
                link_node = item.find("link")
                if link_node is not None:
                    link = (link_node.get("href") or link_node.text or "").strip()
                if not link:
                    link = (item.findtext("link") or "").strip()

                pub_date = (
                    item.findtext("pubDate") or 
                    item.findtext("{http://www.w3.org/2005/Atom}published") or 
                    item.findtext("{http://www.w3.org/2005/Atom}updated") or ""
                ).strip()

                creator = item.findtext("{http://purl.org/dc/elements/1.1/}creator") or item.findtext("{http://www.w3.org/2005/Atom}author") or ""
                desc = item.findtext("description") or item.findtext("{http://www.w3.org/2005/Atom}summary") or ""

                if title and link:
                    items.append({
                        "title": title,
                        "link": link,
                        "pub_date": pub_date,
                        "author": creator.strip(),
                        "description": self._clean_text(desc)[:320]
                    })
        except Exception:
            for block in re.findall(r"<(?:item|entry)>(.*?)</(?:item|entry)>", content, re.DOTALL | re.IGNORECASE):
                t_m = re.search(r"<title(?:[^>]*)>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", block, re.DOTALL | re.IGNORECASE)
                l_m = re.search(r'<link[^>]*href="([^"]+)"', block, re.IGNORECASE) or re.search(r"<link[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>", block, re.DOTALL | re.IGNORECASE)
                p_m = re.search(r"<(?:pubDate|published|updated)>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</(?:pubDate|published|updated)>", block, re.DOTALL | re.IGNORECASE)
                d_m = re.search(r"<(?:description|summary)>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</(?:description|summary)>", block, re.DOTALL | re.IGNORECASE)
                a_m = re.search(r"<(?:dc:creator|author)>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</(?:dc:creator|author)>", block, re.DOTALL | re.IGNORECASE)

                title = self._clean_text(t_m.group(1)) if t_m else ""
                link = ""
                if l_m:
                    link = (l_m.group(1) or "").strip()
                pub_date = p_m.group(1).strip() if p_m else ""
                desc = self._clean_text(d_m.group(1)) if d_m else ""
                author = self._clean_text(a_m.group(1)) if a_m else ""

                if title and link:
                    items.append({
                        "title": title,
                        "link": link,
                        "pub_date": pub_date,
                        "author": author,
                        "description": desc[:320]
                    })
        return items

    def _fetch_single_feed(self, feed: dict, limit: int = 15) -> List[dict]:
        try:
            resp = self.session.get(feed['url'], timeout=8)
            if resp.status_code != 200:
                return []
            raw_items = self._parse_items(resp.text)
            matched = []
            for item in raw_items:
                if not is_within_14_days(item.get("pub_date", "")):
                    continue

                title = item['title']
                desc = item['description']
                link = item['link']

                # Translate Chinese if detected
                is_chinese = bool(re.search(r'[\u4e00-\u9fff]', title) or re.search(r'[\u4e00-\u9fff]', desc))
                if re.search(r'[\u4e00-\u9fff]', title):
                    title = translate_zh_to_en(title)
                if re.search(r'[\u4e00-\u9fff]', desc):
                    desc = translate_zh_to_en(desc)

                # Wrap Chinese pages in Google Translate proxy
                if is_chinese or "taibo.cn" in link:
                    link = make_translated_link(link)

                corpus = f"{title} {desc}"
                rel = evaluate_relevance(corpus)
                if not rel["is_relevant"]:
                    continue

                category = self._classify_topic(title, desc, feed['name'])
                matched.append({
                    "source": feed['name'],
                    "tier": feed['tier'],
                    "category": category,
                    "title": title,
                    "author": item['author'] or feed['name'],
                    "pub_date": item['pub_date'][:16] if item['pub_date'] else "Recent",
                    "description": desc,
                    "url": link,
                    "classification": rel["classification"],
                    "is_golden_dome": rel["is_golden_dome"],
                    "is_space": rel["is_space"],
                    "related_coverage": [],
                    "ingested_at": datetime.now(timezone.utc).isoformat()
                })
                if len(matched) >= limit:
                    break
            return matched
        except Exception:
            return []

    def _scrape_china_in_space_archive(self, limit: int = 10) -> List[dict]:
        """Scrapes reporting from china-in-space.com/archive, strictly validating publication dates."""
        archive_url = "https://www.china-in-space.com/archive"
        results = []
        try:
            resp = self.session.get(archive_url, timeout=10)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                posts = soup.find_all(["div", "article"], class_=re.compile(r"post-preview|entry|portable-archive", re.I)) or soup.find_all("a", href=re.compile(r"/p/"))
                seen_urls = set()

                for elem in posts:
                    a_tag = elem if elem.name == "a" else elem.find("a", href=re.compile(r"/p/"))
                    if not a_tag:
                        continue

                    title = a_tag.get_text().strip()
                    href = a_tag.get("href", "")
                    full_url = href if href.startswith("http") else f"https://www.china-in-space.com{href}"

                    if len(title) < 15 or full_url in seen_urls:
                        continue

                    time_tag = elem.find("time") if elem.name != "a" else None
                    pub_date = time_tag.get("datetime", "") if time_tag else ""

                    if pub_date and not is_within_14_days(pub_date):
                        continue

                    seen_urls.add(full_url)
                    results.append({
                        "source": "China in Space",
                        "tier": "PRC Space Analysis",
                        "category": "China",
                        "title": title,
                        "author": "China in Space",
                        "pub_date": pub_date[:10] if pub_date else "Recent",
                        "description": f"China in Space reporting: {title}",
                        "url": full_url,
                        "classification": "Space Relevant",
                        "is_golden_dome": False,
                        "is_space": True,
                        "related_coverage": [],
                        "ingested_at": datetime.now(timezone.utc).isoformat()
                    })
                    if len(results) >= limit:
                        break
        except Exception as e:
            logging.error(f"Error scraping china-in-space.com/archive: {e}")
        return results

    def _fetch_taibo_chinese_news(self, limit: int = 15) -> List[dict]:
        """
        Polls Taibo.cn commercial space wire:
        1. Translates Chinese headlines and summaries to English for dashboard display.
        2. Wraps destination URLs in Google Translate web proxy so clicking opens in English.
        3. Enforces strict 14-day rolling window.
        """
        logging.info("Querying Taibo.cn commercial aerospace wire and translating to English...")
        query = "site:taibo.cn (商业航天 OR 卫星 OR 航天 OR 火箭) when:14d"
        feed_url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"

        translated_items = []
        try:
            resp = self.session.get(feed_url, timeout=10)
            if resp.status_code != 200:
                return []

            root = ET.fromstring(resp.text.replace("&nbsp;", " "))
            for item in root.findall(".//item"):
                pub_date = (item.findtext("pubDate") or "").strip()
                if not is_within_14_days(pub_date):
                    continue

                raw_title = (item.findtext("title") or "").strip()
                raw_link = (item.findtext("link") or "").strip()
                raw_desc = self._clean_text(item.findtext("description") or "")

                if " - " in raw_title:
                    raw_title = raw_title.rsplit(" - ", 1)[0].strip()

                # Translate text for display
                en_title = translate_zh_to_en(raw_title)
                en_desc = translate_zh_to_en(raw_desc)

                # Wrap destination link so it opens fully translated in English when clicked
                translated_link = make_translated_link(raw_link)

                translated_items.append({
                    "source": "Taibo (泰伯网)",
                    "tier": "Chinese Commercial Space",
                    "category": "China",
                    "title": en_title,
                    "author": "Taibo.cn",
                    "pub_date": pub_date[:16] if pub_date else "Recent",
                    "description": en_desc[:300],
                    "url": translated_link,
                    "classification": "Space Relevant",
                    "is_golden_dome": False,
                    "is_space": True,
                    "related_coverage": [],
                    "ingested_at": datetime.now(timezone.utc).isoformat()
                })
                if len(translated_items) >= limit:
                    break
        except Exception as e:
            logging.error(f"Error ingesting Taibo.cn: {e}")

        logging.info(f"Captured and translated {len(translated_items)} Taibo.cn articles.")
        return translated_items

    def _cluster_related_reporting(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        def get_keywords(t: str) -> Set[str]:
            stopwords = {"space", "force", "launch", "first", "plans", "tests", "after", "about", "could", "would", "names", "taps", "with", "from"}
            words = set(re.findall(r'\b[a-zA-Z]{4,}\b', t.lower()))
            return words - stopwords

        for i, art in enumerate(articles):
            kw_i = get_keywords(art["title"])
            related = []
            for j, other in enumerate(articles):
                if i == j or art["source"] == other["source"]:
                    continue
                kw_j = get_keywords(other["title"])
                shared = kw_i & kw_j
                if len(shared) >= 2:
                    related.append({
                        "source": other["source"],
                        "title": other["title"],
                        "url": other["url"]
                    })
            art["related_coverage"] = related[:3]

        return articles

    def scrape_all_feeds(self, limit_per_feed: int = 15) -> List[Dict[str, Any]]:
        logging.info(f"Concurrent sweep across {len(self.FEEDS)} global space feeds (<= 14 days)...")
        all_articles = []
        seen_links: Set[str] = set()

        with ThreadPoolExecutor(max_workers=25) as executor:
            future_to_feed = {executor.submit(self._fetch_single_feed, feed, limit_per_feed): feed for feed in self.FEEDS}
            for future in as_completed(future_to_feed):
                feed_items = future.result()
                for item in feed_items:
                    clean_link = item['url'].split('?')[0].rstrip('/')
                    if clean_link in seen_links:
                        continue
                    seen_links.add(clean_link)
                    all_articles.append(item)

        taibo_items = self._fetch_taibo_chinese_news(limit=15)
        for t in taibo_items:
            clean_link = t['url'].split('?')[0].rstrip('/')
            if clean_link not in seen_links:
                seen_links.add(clean_link)
                all_articles.append(t)

        cis_items = self._scrape_china_in_space_archive(limit=8)
        for c in cis_items:
            clean_link = c['url'].split('?')[0].rstrip('/')
            if clean_link not in seen_links:
                seen_links.add(clean_link)
                all_articles.append(c)

        clustered = self._cluster_related_reporting(all_articles)
        logging.info(f"Ingested {len(clustered)} verified space articles from the past 14 days.")
        return clustered
