import re
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class NSTXLScraper:
    """
    Scrapes all open/active opportunities from NSTXL.org (SpEC, S2MARTS, TReX, etc.)
    without topic filtering, excluding only closed or past-deadline items.
    """
    OPPORTUNITIES_URL = "https://nstxl.org/opportunities/"

    def _is_closed(self, text: str, deadline_str: str) -> bool:
        """Returns True if the opportunity is explicitly marked closed or its deadline has passed."""
        lower_text = text.lower()
        if any(flag in lower_text for flag in ["status: closed", "solicitation closed", "awarded", "archived"]):
            return True

        if not deadline_str or deadline_str.lower() in ["open", "tbd", "ongoing", "rolling", "see listing"]:
            return False

        # Attempt to parse common date formats (e.g., "Nov 30, 2026", "11/30/2026", "2026-11-30")
        now = datetime.now(timezone.utc)
        clean_date = re.sub(r'(st|nd|rd|th)', '', deadline_str.strip(), flags=re.I)
        
        for fmt in ("%b %d, %Y", "%B %d, %Y", "%m/%d/%Y", "%Y-%m-%d", "%d %b %Y", "%d %B %Y"):
            try:
                # Extract just the date substring if time/timezone is attached
                date_part = re.search(r'([A-Za-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})', clean_date)
                if date_part:
                    parsed_dt = datetime.strptime(date_part.group(1).replace(",", ""), fmt.replace(",", "")).replace(tzinfo=timezone.utc)
                    # Add 24-hour buffer so items closing today remain visible until tomorrow
                    if parsed_dt.timestamp() < (now.timestamp() - 86400):
                        return True
            except ValueError:
                continue

        return False

    def fetch_open_opportunities(self) -> List[Dict[str, Any]]:
        logging.info("Launching Playwright to scrape open opportunities from NSTXL.org...")
        opportunities: List[Dict[str, Any]] = []
        seen_urls = set()

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
                )
                page = context.new_page()
                page.goto(self.OPPORTUNITIES_URL, wait_until="networkidle", timeout=45000)
                page.wait_for_timeout(2500)

                # Ensure the "Current" / Active tab is selected if tabbed UI is present
                current_tab = page.locator("button:has-text('Current'), a:has-text('Current'), [data-tab*='current']").first
                if current_tab.count() > 0:
                    try:
                        current_tab.click()
                        page.wait_for_timeout(1500)
                    except Exception:
                        pass

                # Locate opportunity cards/rows across NSTXL's WordPress/Elementor/HubSpot card structures
                cards = page.locator("article, .opportunity-card, .jet-listing-grid__item, .elementor-post, .card, tr").all()

                for card in cards:
                    try:
                        raw_text = card.inner_text().strip()
                        if len(raw_text) < 25:
                            continue

                        # Skip navigation or non-opportunity blocks
                        link_el = card.locator("a[href*='nstxl.org'], a[href*='opportunity'], a[href*='info.nstxl']").first
                        if link_el.count() == 0:
                            continue

                        url = link_el.get_attribute("href") or ""
                        if not url or url in seen_urls or url.rstrip("/") == self.OPPORTUNITIES_URL.rstrip("/"):
                            continue

                        # Extract Title
                        heading_el = card.locator("h1, h2, h3, h4, .title, .entry-title").first
                        title = heading_el.inner_text().strip() if heading_el.count() > 0 else link_el.inner_text().strip()
                        title = re.sub(r'\s+', ' ', title)
                        if len(title) < 8 or title.lower() in ["learn more", "view opportunity", "read more", "current", "closed"]:
                            continue

                        # Extract Deadline if listed on the card
                        deadline_match = re.search(
                            r'(?:Due|Deadline|Closes|Closing|Submission Date)[:\s]*([A-Za-z0-9,/\-\s:]+?)(?:\n|$|\|)',
                            raw_text,
                            re.I
                        )
                        deadline = deadline_match.group(1).strip() if deadline_match else "Open"

                        # Filter out closed opportunities
                        if self._is_closed(raw_text, deadline):
                            continue

                        # Identify OTA vehicle tag (SpEC, S2MARTS, TReX, etc.)
                        ota_vehicle = "NSTXL OTA"
                        for tag in ["SpEC", "S2MARTS", "S²MARTS", "TReX", "DIB", "OIB"]:
                            if tag.lower() in raw_text.lower():
                                ota_vehicle = f"NSTXL ({tag})"
                                break

                        is_golden = bool(re.search(r'golden dome|missile defense|hypersonic|interceptor|tracking layer|sda|pwsa', raw_text, re.I))

                        seen_urls.add(url)
                        opportunities.append({
                            "title": title[:180],
                            "source": ota_vehicle,
                            "notice_type": "Consortium OTA / RFS",
                            "agency_office": "NSTXL Consortium",
                            "solicitation_number": "",
                            "response_deadline": deadline[:45],
                            "point_of_contact": "NSTXL Member Portal",
                            "url": url,
                            "pub_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                            "ingested_at": datetime.now(timezone.utc).isoformat(),
                            "is_golden_dome": is_golden
                        })
                    except Exception:
                        continue

                browser.close()
        except Exception as e:
            logging.error(f"Error scraping NSTXL.org opportunities: {e}")

        logging.info(f"Captured {len(opportunities)} open opportunities from NSTXL.org.")
        return opportunities
