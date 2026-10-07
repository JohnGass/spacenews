import os
import re
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
import xml.etree.ElementTree as ET
import requests
from scrapers.filter_rules import evaluate_relevance

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class SpaceNewsScraper:
    """
    Broad-Spectrum Multithreaded Space Intelligence Engine.
    Polls 75+ global defense, trade press, allied, commercial primes,
    regional spaceport wires, and strategic news feeds concurrently.
    """
    FEEDS = [
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
        {"name": "Smallsat News", "url": "https://news.google.com/rss/search?q=site:smallsatnews.com&hl=en-US&gl=US&ceid=US:en", "tier": "Smallsats"},
        {"name": "SpaceWatch.Global", "url": "https://spacewatch.global/feed/", "tier": "Geopolitical Commercial"},
        {"name": "SpaceQ", "url": "https://spaceq.ca/feed/", "tier": "Canadian & Allied Space"},
        {"name": "Startup Daily", "url": "https://www.startupdaily.net/category/sectors/space/feed/", "tier": "Indo-Pacific Venture"},
        {"name": "Business News Australia", "url": "https://news.google.com/rss/search?q=site:businessnewsaustralia.com+space&hl=en-US&gl=US&ceid=US:en", "tier": "Commercial Space"},

        # --- Launch Operations, Engineering & Hardware ---
        {"name": "Ars Technica Space", "url": "https://arstechnica.com/space/feed/", "tier": "Investigative Launch"},
        {"name": "Spaceflight Now", "url": "https://spaceflightnow.com/feed/", "tier": "Mission Ops & Launch"},
        {"name": "NASASpaceFlight", "url": "https://www.nasaspaceflight.com/feed/", "tier": "Vehicle Testing & Hardware"},
        {"name": "Universe Today", "url": "https://www.universetoday.com/feed/", "tier": "Spaceflight & Tech"},
        {"name": "Space.com", "url": "https://www.space.com/feeds/all", "tier": "Spaceflight News"},
        {"name": "SpaceRef", "url": "https://spaceref.com/feed/", "tier": "Civil & Tech Wire"},
        {"name": "Douglas Messier", "url": "https://parabolicarc.com/feed/", "tier": "Parabolic Arc / Analysis"},
        {"name": "Dawn Aerospace", "url": "https://news.google.com/rss/search?q=site:dawnaerospace.com+OR+%22Dawn+Aerospace%22&hl=en-US&gl=US&ceid=US:en", "tier": "Spaceplane Propulsion"},
        {"name": "Firefly Aerospace", "url": "https://news.google.com/rss/search?q=%22Firefly+Aerospace%22&hl=en-US&gl=US&ceid=US:en", "tier": "Commercial Launch"},
        {"name": "Stratolaunch", "url": "https://news.google.com/rss/search?q=%22Stratolaunch%22&hl=en-US&gl=US&ceid=US:en", "tier": "Hypersonic Testing"},
        {"name": "Sidus Space", "url": "https://news.google.com/rss/search?q=%22Sidus+Space%22&hl=en-US&gl=US&ceid=US:en", "tier": "Satellite Manufacturing"},
        {"name": "Quantum Space", "url": "https://news.google.com/rss/search?q=%22Quantum+Space%22+satellite&hl=en-US&gl=US&ceid=US:en", "tier": "Cislunar & Super GEO"},
        {"name": "Lonestar Space", "url": "https://news.google.com/rss/search?q=%22Lonestar+Data+Holdings%22+OR+%22Lonestar+Space%22&hl=en-US&gl=US&ceid=US:en", "tier": "Lunar Data Operations"},

        # --- Strategic Analysis, Think Tanks & Policy ---
        {"name": "The Space Review", "url": "https://www.thespacereview.com/feed.xml", "tier": "Strategic Analysis"},
        {"name": "SpacePolicyOnline", "url": "https://spacepolicyonline.com/feed/", "tier": "Policy & Hill"},
        {"name": "The Conversation", "url": "https://theconversation.com/us/topics/space-31/articles.atom", "tier": "Academic Analysis"},
        {"name": "Scientific American", "url": "http://rss.sciam.com/ScientificAmerican-Space", "tier": "Science & Exploration"},
        {"name": "Earthsky", "url": "https://earthsky.org/feed/", "tier": "Orbital Science"},
        {"name": "Look Up", "url": "https://news.google.com/rss/search?q=%22Look+Up+Space%22+OR+%22LookUpSpace%22&hl=en-US&gl=US&ceid=US:en", "tier": "Space Safety / SSA"},
        {"name": "Omnidea", "url": "https://news.google.com/rss/search?q=Omnidea+space+propulsion&hl=en-US&gl=US&ceid=US:en", "tier": "Advanced Propulsion"},

        # --- Florida & Regional Spaceport News ---
        {"name": "Florida Today", "url": "https://rssfeeds.floridatoday.com/floridatoday/space", "tier": "Cape Canaveral Wire"},
        {"name": "Spectrum News 13", "url": "https://www.mynews13.com/services/rss/feed.space.rss", "tier": "Central Florida Space"},
        {"name": "Bay News 9", "url": "https://news.google.com/rss/search?q=site:baynews9.com+space&hl=en-US&gl=US&ceid=US:en", "tier": "Florida Space Coast"},
        {"name": "Bradenton Herald", "url": "https://news.google.com/rss/search?q=site:bradenton.com+space&hl=en-US&gl=US&ceid=US:en", "tier": "Florida Local"},
        {"name": "Charlotte Observer", "url": "https://news.google.com/rss/search?q=site:charlotteobserver.com+aerospace+OR+space&hl=en-US&gl=US&ceid=US:en", "tier": "Regional Aerospace"},
        {"name": "Dayton Daily News", "url": "https://news.google.com/rss/search?q=site:daytondailynews.com+space+OR+nasic&hl=en-US&gl=US&ceid=US:en", "tier": "Wright-Patt / NSIC"},
        {"name": "Team Orlando", "url": "https://news.google.com/rss/search?q=%22Team+Orlando%22+space+OR+simulation&hl=en-US&gl=US&ceid=US:en", "tier": "Simulation & Training"},

        # --- Global Mainstream, Business & Geopolitical Wires ---
        {"name": "Wall Street Journal", "url": "https://news.google.com/rss/search?q=site:wsj.com+space&hl=en-US&gl=US&ceid=US:en", "tier": "Financial & Aerospace"},
        {"name": "New York Times", "url": "https://rss.nytimes.com/services/xml/rss/nyt/Space.xml", "tier": "Mainstream Wire"},
        {"name": "Reuters", "url": "https://news.google.com/rss/search?q=site:reuters.com+space&hl=en-US&gl=US&ceid=US:en", "tier": "Global Wire"},
        {"name": "Bloomberg / LatAm", "url": "https://news.google.com/rss/search?q=site:bloomberg.com+space+industry&hl=en-US&gl=US&ceid=US:en", "tier": "Global Financial"},
        {"name": "Politico", "url": "https://news.google.com/rss/search?q=site:politico.com+space+force+OR+satellite&hl=en-US&gl=US&ceid=US:en", "tier": "Hill Policy"},
        {"name": "Axios", "url": "https://news.google.com/rss/search?q=site:axios.com+space&hl=en-US&gl=US&ceid=US:en", "tier": "Space Economy"},
        {"name": "CNBC", "url": "https://news.google.com/rss/search?q=site:cnbc.com+space+investing&hl=en-US&gl=US&ceid=US:en", "tier": "Venture & Public Primes"},
        {"name": "CNN Space", "url": "http://rss.cnn.com/rss/edition_space.rss", "tier": "Mainstream Wire"},
        {"name": "BBC News", "url": "http://feeds.bbci.co.uk/news/science_and_environment/rss.xml", "tier": "UK & Global Science"},
        {"name": "GeekWire", "url": "https://www.geekwire.com/aerospace/feed/", "tier": "Pacific NW Aerospace"},
        {"name": "Gizmodo", "url": "https://gizmodo.com/tag/space/rss", "tier": "Tech & Space"},
        {"name": "LA Times", "url": "https://news.google.com/rss/search?q=site:latimes.com+aerospace+OR+%22space+force%22&hl=en-US&gl=US&ceid=US:en", "tier": "SoCal Aerospace"},
        {"name": "Yahoo News", "url": "https://news.google.com/rss/search?q=site:yahoo.com/news+space+force+OR+satellite&hl=en-US&gl=US&ceid=US:en", "tier": "Wire Syndication"},

        # --- International & State Actors (China, Russia, Asia, Middle East, Europe) ---
        {"name": "South China Morning Post", "url": "https://news.google.com/rss/search?q=site:scmp.com+space&hl=en-US&gl=US&ceid=US:en", "tier": "China Space Tracking"},
        {"name": "China Daily", "url": "https://news.google.com/rss/search?q=site:chinadaily.com.cn+space+launch&hl=en-US&gl=US&ceid=US:en", "tier": "PRC State Media"},
        {"name": "Xinhua News", "url": "https://news.google.com/rss/search?q=site:xinhuanet.com+satellite+OR+space&hl=en-US&gl=US&ceid=US:en", "tier": "PRC Official Wire"},
        {"name": "European Spaceflight", "url": "https://europeanspaceflight.com/feed/", "tier": "European Launch"},
        {"name": "ESA", "url": "https://www.esa.int/rssfeed/Our_Activities/Space_Safety", "tier": "European Space Agency"},
        {"name": "Gov.UK / UKSA", "url": "https://www.gov.uk/government/organisations/uk-space-agency.atom", "tier": "UK Defense & Civil"},
        {"name": "Jiji Press", "url": "https://news.google.com/rss/search?q=site:jiji.com+space+OR+jaxa&hl=ja&gl=JP&ceid=JP:ja", "tier": "Japanese Aerospace"},
        {"name": "Economic Times", "url": "https://economictimes.indiatimes.com/news/science/rssfeeds/3983049.cms", "tier": "ISRO & Indo-Pacific"},
        {"name": "NDTV", "url": "https://news.google.com/rss/search?q=site:ndtv.com+isro+OR+space&hl=en-IN&gl=IN&ceid=IN:en", "tier": "South Asian Space"},
        {"name": "Radio New Zealand", "url": "https://www.rnz.co.nz/rss/science.xml", "tier": "Oceania / Mahia Launch"},
        {"name": "Irish Times", "url": "https://news.google.com/rss/search?q=site:irishtimes.com+space+technology&hl=en-IE&gl=IE&ceid=IE:en", "tier": "European Science"},
        {"name": "Times of Oman", "url": "https://news.google.com/rss/search?q=site:timesofoman.com+space&hl=en-US&gl=US&ceid=US:en", "tier": "Middle East Space"},
        {"name": "Nairobi Leo", "url": "https://news.google.com/rss/search?q=site:nairobileo.co.ke+space+satellite&hl=en-KE&gl=KE&ceid=KE:en", "tier": "African Space"},
        {"name": "DPA International", "url": "https://news.google.com/rss/search?q=%22dpa%22+space+launch+OR+satellite&hl=en-US&gl=US&ceid=US:en", "tier": "German / EU Wire"},

        # --- Civil Agencies, Research & Curated Aggregators ---
        {"name": "NASA HQ Releases", "url": "https://www.nasa.gov/news-release/feed/", "tier": "Civil Agency"},
        {"name": "FAA Commercial Space", "url": "https://news.google.com/rss/search?q=site:faa.gov+%22commercial+space%22+OR+licensing&hl=en-US&gl=US&ceid=US:en", "tier": "Launch Licensing"},
        {"name": "CASIS / ISS National Lab", "url": "https://www.issnationallab.org/feed/", "tier": "Microgravity & LEO"},
        {"name": "ODAA", "url": "https://news.google.com/rss/search?q=%22ODAA%22+space+OR+defense&hl=en-US&gl=US&ceid=US:en", "tier": "Defense Compliance"},
        {"name": "Tohoku Space", "url": "https://news.google.com/rss/search?q=%22Tohoku+University%22+satellite+OR+space&hl=en-US&gl=US&ceid=US:en", "tier": "Allied University R&D"},
        {"name": "Ikenna Lewis Space", "url": "https://news.google.com/rss/search?q=%22Ikenna+Lewis%22+space&hl=en-US&gl=US&ceid=US:en", "tier": "Analysis & Commentary"},
        {"name": "Latte Luxury Space", "url": "https://news.google.com/rss/search?q=%22Latte+Luxury%22+space&hl=en-US&gl=US&ceid=US:en", "tier": "Emerging Commercial"},
        {"name": "Florida SPACErePORT", "url": "https://news.google.com/rss/search?q=%22SPACErePORT%22+OR+%22Florida+Space+Report%22&hl=en-US&gl=US&ceid=US:en", "tier": "Space Coast Curated"}
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

    def _classify_topic(self, title: str, description: str) -> str:
        corpus = f"{title} {description}"

        # 1. Executive / C-Suite / Corporate M&A moves ALWAYS route to Commercial
        exec_pattern = re.compile(
            r"\b(names|appoints|taps|hires|named|executive|c-suite|ceo|coo|cfo|cto|president|"
            r"board\s+of\s+directors|merger|merges|acquires|acquisition|earnings|quarterly|"
            r"revenue|profit|loss|shares|nasdaq|nyse|valuation|spac|funding\s+round|series\s+[a-d])\b",
            re.IGNORECASE
        )
        if exec_pattern.search(title):
            return "Commercial"

        # 2. Geopolitical Competitors
        if re.search(r"\b(china|chinese|cnsa|beijing|tiangong|chang'e|long\s*march|casc|casic|landspace|deep\s*blue|yuanwang|tianwen|qianfan)\b", corpus, re.I):
            return "China"
        if re.search(r"\b(russia|russian|roscosmos|moscow|angara|soyuz|vostochny|plesetsk|glonass)\b", corpus, re.I):
            return "Russia"

        # 3. Policy, Hill & Regulatory
        if re.search(r"\b(congress|senate|house|hasc|sasc|appropriations|ndaa|lawmaker|capitol\s*hill|legislation|white\s*house|space\s*council|faa|fcc|treaty|budget|regulatory|commerce\s*department)\b", corpus, re.I):
            return "Policy & Hill"

        # 4. Launch & Propulsion
        if re.search(r"\b(launch|launches|launched|launching|rocket|booster|liftoff|starship|falcon\s*9|falcon\s*heavy|new\s*glenn|vulcan|sls|super\s*heavy|electron|static\s*fire|engine\s*test|hot\s*fire|pad\s*[0-9a-zA-Z]+|spaceport|cape\s*canaveral|vandenberg|kourou)\b", corpus, re.I):
            return "Launch"

        # 5. Spacecraft & In-Orbit Operations
        if re.search(r"\b(spacecraft|satellite|satellites|constellation|bus|rf-sensor|sensor|sensors|payload|on-orbit|in-orbit|orbital\s*target|orbital\s*debris|rendezvous|docking|proximity|rpo|space\s*domain\s*awareness|sda|ssa|space\s*tracking|maneuver|deorbit|flight\s*operations)\b", corpus, re.I):
            return "Spacecraft & Ops"

        # 6. Novel Technology & Research
        if re.search(r"\b(optical\s*comm|laser|quantum|nuclear|solar\s*array|ai|edge\s*compute|isam|in-space\s*servicing|refueling|materials|additive)\b", corpus, re.I):
            return "Technology"

        # 7. Commercial Space
        if re.search(r"\b(commercial|venture|startup|investment|spacex|blue\s*origin|rocket\s*lab|astrobotic|axiom|planet\s*labs|spire|capella|hawkeye)\b", corpus, re.I):
            return "Commercial"

        # 8. Allied & International
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
                l_m = re.search(r"<link(?:[^>]*href=[\"']([^\"']+)[\"']|[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>)", block, re.DOTALL | re.IGNORECASE)
                p_m = re.search(r"<(?:pubDate|published|updated)>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</(?:pubDate|published|updated)>", block, re.DOTALL | re.IGNORECASE)
                d_m = re.search(r"<(?:description|summary)>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</(?:description|summary)>", block, re.DOTALL | re.IGNORECASE)
                a_m = re.search(r"<(?:dc:creator|author)>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</(?:dc:creator|author)>", block, re.DOTALL | re.IGNORECASE)

                title = self._clean_text(t_m.group(1)) if t_m else ""
                link = ""
                if l_m:
                    link = (l_m.group(1) or l_m.group(2) or "").strip()
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
                corpus = f"{item['title']} {item['description']}"
                rel = evaluate_relevance(corpus)
                if not rel["is_relevant"]:
                    continue

                category = self._classify_topic(item['title'], item['description'])
                matched.append({
                    "source": feed['name'],
                    "tier": feed['tier'],
                    "category": category,
                    "title": item['title'],
                    "author": item['author'] or feed['name'],
                    "pub_date": item['pub_date'][:16] if item['pub_date'] else "Recent",
                    "description": item['description'],
                    "url": item['link'],
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

    def _cluster_related_reporting(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        def get_keywords(t: str) -> Set[str]:
            stopwords = {"space", "force", "launch", "first", "plans", "tests", "after", "about", "could", "would", "names", "taps", "with", "from"}
            words = set(re.findall(r"\b[a-zA-Z]{4,}\b", t.lower()))
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
        logging.info(f"Concurrent sweep across {len(self.FEEDS)} global space feeds...")
        all_articles = []
        seen_links: Set[str] = set()

        # Execute 30 concurrent workers to sweep all 75+ feeds in ~6-9 seconds
        with ThreadPoolExecutor(max_workers=30) as executor:
            future_to_feed = {executor.submit(self._fetch_single_feed, feed, limit_per_feed): feed for feed in self.FEEDS}
            for future in as_completed(future_to_feed):
                feed_items = future.result()
                for item in feed_items:
                    clean_link = item['url'].split('?')[0].rstrip('/')
                    if clean_link in seen_links:
                        continue
                    seen_links.add(clean_link)
                    all_articles.append(item)

        clustered = self._cluster_related_reporting(all_articles)
        logging.info(f"Ingested {len(clustered)} verified space articles across all 75+ feeds.")
        return clustered
