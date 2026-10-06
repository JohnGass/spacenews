#!/usr/bin/env python3
import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from scrapers.defense_scraper import DefenseGovScraper
from scrapers.congress_scraper import CongressGovSpaceClient, CongressionalHearingPipeline
from scrapers.sam_scraper import PreAwardScraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def main():
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    logging.info("Starting Full Spectrum Space & Golden Dome Intel Pull...")

    # 1. Ingest Post-Award Contracts (Defense.gov)
    defense_scraper = DefenseGovScraper()
    contracts = defense_scraper.scrape_recent_releases(limit=5)
    logging.info(f"Total verified Defense.gov contracts: {len(contracts)}")

    # 2. Ingest Pre-Award Solicitations & RFPs (SAM.gov & DIU)
    pre_award_scraper = PreAwardScraper()
    solicitations = pre_award_scraper.get_all_pre_award_signals()
    logging.info(f"Total active pre-award solicitations: {len(solicitations)}")

    # 3. Ingest Congressional Proceedings & Hearings (Congress.gov)
    congress_key = os.getenv("CONGRESS_GOV_API_KEY")
    enriched_hearings = []
    if congress_key:
        congress_client = CongressGovSpaceClient(api_key=congress_key)
        raw_hearings = congress_client.process_and_filter(days_back=7, days_forward=21)
        hearing_pipeline = CongressionalHearingPipeline(api_key=congress_key)
        for h in raw_hearings:
            enriched_hearings.append(hearing_pipeline.process_hearing_testimony(h))
        logging.info(f"Total Congressional hearings tracked: {len(enriched_hearings)}")
    else:
        logging.warning("CONGRESS_GOV_API_KEY missing. Skipping hearing ingestion.")

    # 4. Compile Comprehensive Intelligence Payload
    daily_report = {
        "report_date": today_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_contracts": len(contracts),
            "total_solicitations": len(solicitations),
            "total_hearings": len(enriched_hearings),
            "golden_dome_priority_count": (
                sum(1 for c in contracts if c.get("is_golden_dome")) +
                sum(1 for s in solicitations if s.get("is_golden_dome")) +
                sum(1 for h in enriched_hearings if h.get("is_golden_dome"))
            )
        },
        "pre_award_solicitations": solicitations,
        "defense_contracts": contracts,
        "congressional_hearings": enriched_hearings
    }

    # Write to local cache and web dashboard feeds
    report_file = data_dir / f"intel_report_{today_str}.json"
    latest_file = data_dir / "latest.json"

    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(daily_report, f, indent=2)

    with open(latest_file, "w", encoding="utf-8") as f:
        json.dump(daily_report, f, indent=2)

    logging.info(f"Pipeline complete. All intelligence synchronized to {latest_file}")

if __name__ == "__main__":
    main()
