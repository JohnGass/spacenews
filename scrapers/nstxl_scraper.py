import re
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class NSTXLScraper:
    """
    Scrapes only opportunities under the 'Current' tab on https://nstxl.org/nstxl-opportunities/
    without topic filtering.
    """
    OPPORTUNITIES_URL = "https://nstxl.org/nstxl-opportunities/"

    NON_CURRENT_STATUSES = (
        "awarded",
        "under evaluation",
        "rfi/rni - archived",
        "archived",
        "canceled",
        "cancelled",
        "closed"
    )

    def _detect_consortium(self, text: str, img_hints: str) -> str:
        combined = f"{text} {img_hints}".lower()
        if "space enterprise consortium" in combined or re.search(r'\bspec\b', combined):
            return "NSTXL (SpEC)"
        if "jdec" in combined or "joint directed energy" in combined:
            return "NSTXL (JDEC)"
        if "s2marts" in combined or "s²marts" in combined:
            return "NSTXL (S2MARTS)"
        if "microelectronics commons" in combined:
            return "NSTXL (Microelectronics Commons)"
        if "trex" in combined:
            return "NSTXL (TReX)"
        return "NSTXL OTA"

    def fetch_open_opportunities(self) -> List[Dict[str, Any]]:
        logging.info("Launching Playwright to scrape 'Current' opportunities from NSTXL.org...")
        opportunities: List[Dict[str, Any]] = []
        seen_titles = set()

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                    viewport={"width": 1440, "height": 900}
                )
                page = context.new_page()
                page.goto(self.OPPORTUNITIES_URL, wait_until="networkidle", timeout=45000)
                page.wait_for_timeout(2000)

                if "login" in page.url.lower() or "wp-login" in page.url.lower():
                    logging.warning("NSTXL redirected unauthenticated runner to login page.")
                    browser.close()
                    return []

                # Click the 'Current' filter item (handles <label>, <span>, <li>, <button>, and <a>)
                current_filter = page.locator("label, span, li, button, a").filter(
                    has_text=re.compile(r"^\s*Current\s*$", re.I)
                ).first

                if current_filter.count() > 0:
                    current_filter.scroll_into_view_if_needed()
                    current_filter.click(force=True)
                    try:
                        page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass
                    page.wait_for_timeout(3000)
                    logging.info("Clicked 'Current' filter on NSTXL.")
                else:
                    logging.warning("Could not locate 'Current' filter element on NSTXL.")

                # Expand any "Load More" pagination while on the Current filter
                for _ in range(5):
                    load_more = page.locator("button:has-text('Load More'), a:has-text('Load More')").first
                    if load_more.count() > 0 and load_more.is_visible():
                        try:
                            load_more.click()
                            page.wait_for_timeout(2000)
                        except Exception:
                            break
                    else:
                        break

                # Extract ONLY visible cards (ignore cards hidden via display:none)
                raw_cards = page.evaluate("""() => {
                    const results = [];
                    const seen = new Set();
                    const headings = document.querySelectorAll('main h2, main h3, main h4, article h2, article h3, .elementor-widget-container h2, .elementor-widget-container h3, .jet-listing-grid__item h2, .jet-listing-grid__item h3');

                    headings.forEach(h => {
                        const title = (h.innerText || '').trim().replace(/\\s+/g, ' ');
                        if (!title || title.length < 8 || seen.has(title)) return;
                        if (['Search Opportunities', 'Opportunities', 'Filter by'].includes(title)) return;

                        let card = h.closest('article, .jet-listing-grid__item, .elementor-post, .card, li, div[class*="item"], div[class*="card"]') || h.parentElement?.parentElement;
                        if (!card) return;

                        // Skip any card hidden by the active filter tab
                        const style = window.getComputedStyle(card);
                        if (card.offsetParent === null || style.display === 'none' || style.visibility === 'hidden') {
                            return;
                        }

                        let anchor = h.closest('a') || card.querySelector('a[href]');
                        let href = anchor ? anchor.getAttribute('href') : '';
                        const imgs = Array.from(card.querySelectorAll('img')).map(img => `${img.alt || ''} ${img.src || ''}`).join(' ');
                        const bodyText = (card.innerText || '').trim();

                        seen.add(title);
                        results.push({
                            title: title,
                            href: href,
                            bodyText: bodyText,
                            imgHints: imgs
                        });
                    });
                    return results;
                }""")

                for item in raw_cards:
                    title = item.get("title", "").strip()
                    if not title or title.lower() in seen_titles:
                        continue

                    body_text = item.get("bodyText", "")
                    lower_body = body_text.lower()

                    # Safeguard: skip if card explicitly displays a non-current status badge
                    if any(status in lower_body for status in self.NON_CURRENT_STATUSES):
                        continue

                    img_hints = item.get("imgHints", "")
                    href = item.get("href", "") or self.OPPORTUNITIES_URL
                    full_url = urljoin(self.OPPORTUNITIES_URL, href)

                    deadline_match = re.search(
                        r'(?:Due|Deadline|Closes|Closing|Submission Date)[:\s]*([A-Za-z0-9,/\-\s:]+?)(?:\n|$|\|)',
                        body_text,
                        re.I
                    )
                    deadline = deadline_match.group(1).strip() if deadline_match else "Current / Open"

                    consortium = self._detect_consortium(f"{title} {body_text}", img_hints)
                    is_golden = bool(re.search(r'golden dome|missile defense|hypersonic|interceptor|tracking layer|sda|pwsa|sbirs|directed energy', f"{title} {body_text}", re.I))

                    seen_titles.add(title.lower())
                    opportunities.append({
                        "title": title[:180],
                        "source": consortium,
                        "notice_type": "Current OTA / RFS",
                        "agency_office": consortium,
                        "solicitation_number": "",
                        "response_deadline": deadline[:45],
                        "point_of_contact": "NSTXL Opportunities",
                        "url": full_url,
                        "pub_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        "ingested_at": datetime.now(timezone.utc).isoformat(),
                        "is_golden_dome": is_golden
                    })

                browser.close()
        except Exception as e:
            logging.error(f"Error scraping NSTXL.org opportunities: {e}")

        logging.info(f"Captured {len(opportunities)} 'Current' opportunities from NSTXL.org.")
        return opportunities
