#!/usr/bin/env python3
import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from scrapers.defense_scraper import DefenseGovScraper
from scrapers.congress_scraper import CongressGovSpaceClient, CongressionalHearingPipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def main():
    api_key = os.getenv("CONGRESS_GOV_API_KEY")
    if not api_key:
        raise ValueError("CONGRESS_GOV_API_KEY environment variable is missing.")

    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    logging.info("Starting Space & Golden Dome Intelligence Pull...")

    # 1. Scrape Defense.gov Contracts across the last 5 daily releases
    defense_scraper = DefenseGovScraper()
    contracts = defense_scraper.scrape_recent_releases(limit=5)
    logging.info(f"Captured {len(contracts)} relevant Defense.gov contracts across recent releases.")

    # 2. Scrape Congress.gov Hearings
    congress_client = CongressGovSpaceClient(api_key=api_key)
    raw_hearings = congress_client.process_and_filter(days_back=7, days_forward=21)
    
    # 3. Enrich with Witness Statements & Policy Quotes
    hearing_pipeline = CongressionalHearingPipeline(api_key=api_key)
    enriched_hearings = []
    for h in raw_hearings:
        logging.info(f"Checking testimony attachments for: {h['title']}")
        enriched_hearings.append(hearing_pipeline.process_hearing_testimony(h))

    # 4. Compile Intelligence Summary
    daily_report = {
        "report_date": today_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_contracts": len(contracts),
            "total_hearings": len(enriched_hearings),
            "golden_dome_priority_count": sum(
                1 for c in contracts if c.get("is_golden_dome")
            ) + sum(1 for h in enriched_hearings if h.get("is_golden_dome"))
        },
        "defense_contracts": contracts,
        "congressional_hearings": enriched_hearings
    }

    # Save reports to data/
    report_file = data_dir / f"intel_report_{today_str}.json"
    latest_file = data_dir / "latest.json"

    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(daily_report, f, indent=2)

    with open(latest_file, "w", encoding="utf-8") as f:
        json.dump(daily_report, f, indent=2)

    logging.info(f"Pipeline complete. Intel written to {report_file} and {latest_file}")

if __name__ == "__main__":
    main()
