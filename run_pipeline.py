#!/usr/bin/env python3
import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from scrapers.defense_scraper import DefenseGovScraper
from scrapers.sam_scraper import PreAwardScraper
from scrapers.dsip_sbir_scraper import DSIPSbirScraper
from scrapers.ic_diu_scraper import ICDIUScraper
from scrapers.space_news_scraper import SpaceNewsScraper
from scrapers.client_intel_scraper import ClientIntelScraper
from scrapers.calendar_scraper import CalendarScraper
from scrapers.congress_scraper import CongressGovSpaceClient, CongressionalHearingPipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def main():
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    logging.info("Starting Full Spectrum Space & Defense Intelligence Pull...")

    # 1. Post-Award Contracts (Defense.gov)
    defense_scraper = DefenseGovScraper()
    contracts = defense_scraper.scrape_recent_releases(limit=5) or []
    logging.info(f"Captured {len(contracts)} Defense.gov contracts.")

    # 2. SAM.gov Pre-Award RFPs & SpEC Consortia OTAs
    pre_award_scraper = PreAwardScraper()
    pre_award_data = pre_award_scraper.get_all_pre_award_signals() or {}
    solicitations = pre_award_data.get("standard_solicitations", []) or []
    spec_otas = pre_award_data.get("spec_and_otas", []) or []
    logging.info(f"Captured {len(solicitations)} SAM.gov RFPs and {len(spec_otas)} SpEC/OTA notices.")

    # 3. SpaceWERX, TacFI, StratFI, SBIR/STTR (DSIP)
    dsip_scraper = DSIPSbirScraper()
    sbir_spacewerx = dsip_scraper.get_all_sbir_and_spacewerx() or []
    logging.info(f"Captured {len(sbir_spacewerx)} SpaceWERX and SBIR topics.")

    # 4. DIU CSOs, In-Q-Tel, NRO/NGA (IC Portals)
    ic_diu_scraper = ICDIUScraper()
    ic_and_diu = ic_diu_scraper.get_all_ic_and_diu() or []
    logging.info(f"Captured {len(ic_and_diu)} DIU, In-Q-Tel, and IC opportunities.")

    # 5. Global Space Wire (75+ Outlets)
    news_scraper = SpaceNewsScraper()
    space_news = news_scraper.scrape_all_feeds(limit_per_feed=15) or []
    logging.info(f"Captured {len(space_news)} global space news articles.")

    # 6. Tanagra Client Intelligence Wire (29 Clients)
    client_scraper = ClientIntelScraper()
    client_intel = client_scraper.scrape_all_clients(contracts=contracts, solicitations=solicitations) or []
    logging.info(f"Captured {len(client_intel)} Tanagra client reports.")

    # 7. Worldwide Rolling Space & Defense Calendar
    cal_scraper = CalendarScraper()
    rolling_calendar = cal_scraper.get_rolling_calendar() or []
    logging.info(f"Compiled {len(rolling_calendar)} worldwide rolling calendar events.")

    # 8. Congressional Hearings (Congress.gov)
    congress_key = os.getenv("CONGRESS_GOV_API_KEY")
    enriched_hearings = []
    if congress_key:
        try:
            congress_client = CongressGovSpaceClient(api_key=congress_key)
            raw_hearings = congress_client.process_and_filter(days_back=7, days_forward=21) or []
            hearing_pipeline = CongressionalHearingPipeline(api_key=congress_key)
            for h in raw_hearings:
                enriched_hearings.append(hearing_pipeline.process_hearing_testimony(h))
            logging.info(f"Captured {len(enriched_hearings)} Congressional hearings.")
        except Exception as e:
            logging.error(f"Error ingesting Congressional hearings: {e}")

    # Compile Multi-Vector Intelligence Report
    daily_report = {
        "report_date": today_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_contracts": len(contracts),
            "total_solicitations": len(solicitations),
            "total_spec_and_otas": len(spec_otas),
            "total_sbir_and_spacewerx": len(sbir_spacewerx),
            "total_ic_and_diu": len(ic_and_diu),
            "total_space_news": len(space_news),
            "total_client_intel": len(client_intel),
            "total_calendar_events": len(rolling_calendar),
            "total_hearings": len(enriched_hearings),
            "golden_dome_priority_count": (
                sum(1 for c in contracts if c.get("is_golden_dome")) +
                sum(1 for s in solicitations if s.get("is_golden_dome")) +
                sum(1 for o in spec_otas if o.get("is_golden_dome")) +
                sum(1 for sb in sbir_spacewerx if sb.get("is_golden_dome")) +
                sum(1 for ic in ic_and_diu if ic.get("is_golden_dome")) +
                sum(1 for cal in rolling_calendar if cal.get("is_golden_dome")) +
                sum(1 for n in space_news if n.get("is_golden_dome"))
            )
        },
        "rolling_calendar": rolling_calendar,
        "space_news": space_news,
        "client_intel": client_intel,
        "defense_contracts": contracts,
        "pre_award_solicitations": solicitations,
        "spec_and_otas": spec_otas,
        "sbir_and_spacewerx": sbir_spacewerx,
        "ic_and_diu": ic_and_diu,
        "congressional_hearings": enriched_hearings
    }

    report_file = data_dir / f"intel_report_{today_str}.json"
    latest_file = data_dir / "latest.json"

    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(daily_report, f, indent=2)

    with open(latest_file, "w", encoding="utf-8") as f:
        json.dump(daily_report, f, indent=2)

    logging.info(f"Pipeline complete. All intelligence synchronized to {latest_file}")

if __name__ == "__main__":
    main()
