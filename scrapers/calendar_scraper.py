import os
import re
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote
import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup
from scrapers.filter_rules import evaluate_relevance

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class CalendarScraper:
    """
    Worldwide Rolling Space & Defense Calendar Engine.
    Aggregates:
    1. Global Orbital Launch Manifests (Spaceflight Now & Launch Library 2)
    2. Military Combatant Command Exercises (USSPACECOM, INDOPACOM, SOCOM, NATO, Allied)
    3. Major Symposia & Conferences (SFA Spacepower Orlando, NSSA, POC, AIAA, Space Foundation)
    4. Strategic Webinars & Think Tanks (CSIS, NSSA, Aerospace Corp CSPS, Payload, Mitchell Institute)
    5. Pure-Play Commercial Space & Defense Prime Earnings Calls
    """
    SPACENOW_LAUNCH_URL = "https://spaceflightnow.com/launch-schedule/"
    SPACEPOLICY_FEED_URL = "https://spacepolicyonline.com/feed/"
    LL2_UPCOMING_URL = "https://lldev.thespacedevs.com/2.2.0/launch/upcoming/?limit=30"
    CONGRESS_API_URL = "https://api.congress.gov/v3/committee-meeting"

    # =========================================================================
    # 1. CONFERENCES, SYMPOSIA & SUMMITS (Includes SFA Spacepower Orlando, NSSA, POC)
    # =========================================================================
    CONFERENCES_CATALOG = [
        # --- Fall / Winter 2026 ---
        {
            "title": "NSSA Executive Dinner Series: The Hon. Erich Hernandez-Baquero",
            "date": "2026-10-13",
            "category": "Conferences",
            "location": "Tower Club Tysons, Vienna, VA",
            "description": "National Security Space Association executive dinner addressing national reconnaissance and space architecture modernization.",
            "url": "https://nssaspace.org/upcoming/",
            "source": "NSSA",
            "is_golden_dome": False
        },
        {
            "title": "2026 U.S. Space Forum - Project Constellation",
            "date": "2026-10-15",
            "category": "Conferences",
            "location": "Vienna, Austria",
            "description": "Diplomatic conference hosted by the U.S. Mission to International Organizations addressing international space norms and sustainability.",
            "url": "https://vienna.usmission.gov/",
            "source": "U.S. Department of State",
            "is_golden_dome": False
        },
        {
            "title": "ESPI 20th Annual Space Policy Conference",
            "date": "2026-10-19",
            "category": "Conferences",
            "location": "Vienna, Austria",
            "description": "European Space Policy Institute conference on European strategic autonomy, defense space capabilities, and sovereign launch access.",
            "url": "https://espi.or.at/",
            "source": "ESPI",
            "is_golden_dome": False
        },
        {
            "title": "NSSA International Security Space Forum 2026 (ISSF)",
            "date": "2026-10-20",
            "category": "Conferences",
            "location": "Boeing Long Bridge, Arlington, VA",
            "description": "National Security Space Association signature forum addressing coalition space integration, CSpO interoperability, and allied deterrence.",
            "url": "https://nssaspace.org/upcoming/",
            "source": "NSSA",
            "is_golden_dome": True
        },
        {
            "title": "AAS Division for Planetary Sciences (DPS 2026)",
            "date": "2026-10-25",
            "category": "Conferences",
            "location": "Spokane, WA",
            "description": "Major annual gathering of planetary scientists presenting planetary defense and lunar exploration research.",
            "url": "https://dps.aas.org/meetings",
            "source": "AAS",
            "is_golden_dome": False
        },
        {
            "title": "Payload Space & Defense Investor Summit",
            "date": "2026-11-03",
            "category": "Conferences",
            "location": "Los Angeles, CA",
            "description": "High-level forum bringing together venture capital, private equity, defense primes, and government buyers in dual-use national security space.",
            "url": "https://payloadspace.com/events/",
            "source": "Payload Space",
            "is_golden_dome": False
        },
        {
            "title": "Global MilSatCom 2026",
            "date": "2026-11-03",
            "category": "Conferences",
            "location": "London, United Kingdom",
            "description": "The world's premier military satellite communications conference featuring allied space leadership and commercial satcom providers.",
            "url": "https://www.smgconferences.com/defence/uk/conference/global-milsatcom",
            "source": "SAE Media Group",
            "is_golden_dome": False
        },
        {
            "title": "NSSA Executive Dinner Series: Gen. Douglas Schiess (USSF)",
            "date": "2026-11-17",
            "category": "Conferences",
            "location": "Falls Church, VA",
            "description": "NSSA executive address by Space Operations Command leadership detailing operational readiness and tactical mission deltas.",
            "url": "https://nssaspace.org/upcoming/",
            "source": "NSSA",
            "is_golden_dome": True
        },
        {
            "title": "Space Tech Expo Europe 2026",
            "date": "2026-11-17",
            "category": "Conferences",
            "location": "Bremen, Germany",
            "description": "Europe's largest B2B space exhibition covering manufacturing, space components, test facilities, and launch systems.",
            "url": "https://www.spacetechexpo-europe.com/",
            "source": "Space Tech Expo",
            "is_golden_dome": False
        },
        {
            "title": "NSSA Space Deterrence Forum 2026",
            "date": "2026-11-18",
            "category": "Conferences",
            "location": "Peraton HQ, Chantilly, VA (TS/SCI)",
            "description": "Classified signature forum reviewing adversary counterspace threats, resilient architectures, and operational deterrence posture.",
            "url": "https://nssaspace.org/upcoming/",
            "source": "NSSA",
            "is_golden_dome": True
        },
        {
            "title": "SFA Spacepower Conference 2026 (SPC26)",
            "date": "2026-12-08",
            "category": "Conferences",
            "location": "Hilton Orlando, Orlando, FL",
            "description": "Space Force Association flagship national gathering. Keynote address by Gen. Douglas A. Schiess (Chief of Space Operations). Features 5 stages covering Golden Dome missile defense, space nuclear power, in-space refueling/servicing, and warfighter debriefs.",
            "url": "https://members.ussfa.org/",
            "source": "Space Force Association (SFA)",
            "is_golden_dome": True
        },

        # --- 2027 Flagship Symposia ---
        {
            "title": "AIAA SciTech Forum 2027",
            "date": "2027-01-11",
            "category": "Conferences",
            "location": "Orlando, FL",
            "description": "The world's largest aerospace R&D conference covering hypersonics, autonomous space systems, propulsion, and structural dynamics.",
            "url": "https://www.aiaa.org/scitech",
            "source": "AIAA",
            "is_golden_dome": False
        },
        {
            "title": "AIAA DEFENSE Forum 2027",
            "date": "2027-01-20",
            "category": "Conferences",
            "location": "Laurel, MD (Secret / NOFORN)",
            "description": "Classified defense conference examining military space programs, missile defense tracking layers, and contested orbital domain capabilities.",
            "url": "https://www.aiaa.org/events-learning/event/2027/01/20/default-calendar/2027-aiaa-defense-forum",
            "source": "AIAA",
            "is_golden_dome": True
        },
        {
            "title": "NSSA Defense and Intelligence Space Conference (DISC 2027)",
            "date": "2027-02-08",
            "category": "Conferences",
            "location": "Hyatt Regency Reston, Reston, VA (Unclass & TS/SCI)",
            "description": "Premier annual defense and intelligence space conference uniting leaders from USSF, NRO, NGA, and congressional authorizers.",
            "url": "https://nssaspace.org/upcoming/",
            "source": "NSSA",
            "is_golden_dome": True
        },
        {
            "title": "SmallSat Symposium Silicon Valley 2027",
            "date": "2027-02-09",
            "category": "Conferences",
            "location": "Mountain View, CA",
            "description": "Commercial satellite business convention covering constellation economics, private investment, and miniaturized payload tech.",
            "url": "https://smallsatshow.com/",
            "source": "SatNews",
            "is_golden_dome": False
        },
        {
            "title": "IEEE Aerospace Conference 2027",
            "date": "2027-03-06",
            "category": "Conferences",
            "location": "Big Sky, MT",
            "description": "International technical conference on spacecraft engineering, radar, quantum sensing, and deep space comms.",
            "url": "https://www.aeroconf.org/",
            "source": "IEEE",
            "is_golden_dome": False
        },
        {
            "title": "SRA Satellite 2027 Conference & Exhibition",
            "date": "2027-03-15",
            "category": "Conferences",
            "location": "Washington, DC",
            "description": "Landmark commercial satellite event featuring commercial constellation operators, launch providers, and DoD procurement leadership.",
            "url": "https://www.satshow.com/",
            "source": "Satellite Show",
            "is_golden_dome": False
        },
        {
            "title": "41st Space Symposium",
            "date": "2027-04-12",
            "category": "Conferences",
            "location": "Broadmoor Hotel, Colorado Springs, CO",
            "description": "The world's premier space gathering. Major keynote addresses by Chief of Space Operations, Space Systems Command, and allied space chiefs.",
            "url": "https://www.spacesymposium.org/",
            "source": "Space Foundation",
            "is_golden_dome": True
        },
        {
            "title": "Paris Air Show (SIAE 2027)",
            "date": "2027-06-21",
            "category": "Conferences",
            "location": "Le Bourget, Paris, France",
            "description": "The world's largest aerospace trade exhibition featuring launch vehicle rollouts, defense exhibits, and global space agency agreements.",
            "url": "https://www.siae.fr/en/",
            "source": "SIAE",
            "is_golden_dome": False
        },
        {
            "title": "Potomac Officers Club 2027 Air & Space Summit",
            "date": "2027-07-29",
            "category": "Conferences",
            "location": "Hilton McLean, McLean, VA",
            "description": "Annual Potomac Officers Club gathering of DAF, USSF Portfolio Acquisition Executives (PAEs), and primes addressing DAF Battle Network and Golden Dome.",
            "url": "https://www.potomacofficersclub.com/",
            "source": "Potomac Officers Club",
            "is_golden_dome": True
        },
        {
            "title": "Small Satellite Conference (Utah SmallSat 2027)",
            "date": "2027-08-07",
            "category": "Conferences",
            "location": "Logan, UT",
            "description": "Global smallsat gathering covering bus engineering, rideshare launch integration, and proliferated LEO architectures.",
            "url": "https://www.smallsat.org/",
            "source": "USU / AIAA",
            "is_golden_dome": False
        },
        {
            "title": "SMDC Space and Missile Defense Symposium 2027",
            "date": "2027-08-10",
            "category": "Conferences",
            "location": "Von Braun Center, Huntsville, AL",
            "description": "Premier national missile defense convention reviewing Golden Dome layered homeland architecture, PWSA tracking layers, and GPI interceptors.",
            "url": "https://smdsymposium.org/",
            "source": "SMDC Symposium",
            "is_golden_dome": True
        },
        {
            "title": "AMOS Conference 2027",
            "date": "2027-09-14",
            "category": "Conferences",
            "location": "Wailea, Maui, HI",
            "description": "International technical conference dedicated to space domain awareness, orbital debris tracking, and telescope surveillance.",
            "url": "https://amostech.com/",
            "source": "Maui Economic Development Board",
            "is_golden_dome": True
        },
        {
            "title": "AFA Air, Space & Cyber Conference 2027",
            "date": "2027-09-20",
            "category": "Conferences",
            "location": "National Harbor, MD",
            "description": "Department of the Air Force and Space Force leadership posture addresses, industry exhibits, and acquisition announcements.",
            "url": "https://www.afa.org/air-space-cyber-conference/",
            "source": "AFA",
            "is_golden_dome": False
        },
        {
            "title": "International Astronautical Congress (IAC 2027)",
            "date": "2027-10-11",
            "category": "Conferences",
            "location": "Poznań, Poland",
            "description": "Global congress uniting all international space agencies (NASA, ESA, JAXA, ISRO, CNSA) and the commercial space industry.",
            "url": "https://www.iafastro.org/",
            "source": "IAF",
            "is_golden_dome": False
        }
    ]

    # =========================================================================
    # 2. WEBINARS, THINK TANKS & BRIEFINGS (CSIS, Aerospace CSPS, Mitchell, NSSA)
    # =========================================================================
    WEBINARS_CATALOG = [
        {
            "title": "CSIS Aerospace Security: Proliferated Space & Missile Defense",
            "date": "2026-10-21",
            "category": "Webinars",
            "location": "Virtual / CSIS HQ, Washington, DC",
            "description": "Senior defense panel analyzing Space Development Agency Tranche tracking layers and fire-control interceptor integration.",
            "url": "https://aerospace.csis.org/events/",
            "source": "CSIS Aerospace Security Project",
            "is_golden_dome": True
        },
        {
            "title": "Aerospace Corp CSPS Space Policy Show: Dynamic Space Operations",
            "date": "2026-10-28",
            "category": "Webinars",
            "location": "Virtual Webcast (Aerospace Center for Space Policy)",
            "description": "The Aerospace Corporation briefing exploring dynamic space operations, on-orbit maneuvering without regret, and fuel replenishment.",
            "url": "https://csps.aerospace.org/events",
            "source": "Aerospace Corp CSPS",
            "is_golden_dome": False
        },
        {
            "title": "Mitchell Institute Spacepower Series: Space Domain Awareness Realities",
            "date": "2026-11-04",
            "category": "Webinars",
            "location": "Virtual Webcast",
            "description": "Briefing with Space Operations Command leadership addressing non-cooperative orbital tracking and contested space defense.",
            "url": "https://mitchellaerospacepower.org/events/",
            "source": "Mitchell Institute Spacepower",
            "is_golden_dome": True
        },
        {
            "title": "Payload Digital Roundtable: The Small Satellite Agility Paradigm",
            "date": "2026-11-12",
            "category": "Webinars",
            "location": "Virtual Executive Webcast",
            "description": "Executive roundtable featuring constellation CTOs discussing propulsion, inter-satellite links, and tactically responsive satellite bus design.",
            "url": "https://payloadspace.com/webinars/",
            "source": "Payload Space",
            "is_golden_dome": False
        },
        {
            "title": "Aerospace Corp CSPS: Interagency Space Traffic & Authorization",
            "date": "2026-11-18",
            "category": "Webinars",
            "location": "Virtual Webcast",
            "description": "Panel examining Office of Space Commerce TraCSS operational handoff and FAA Part 450 licensing regulatory updates.",
            "url": "https://csps.aerospace.org/events",
            "source": "Aerospace Corp CSPS",
            "is_golden_dome": False
        },
        {
            "title": "Atlantic Council Scowcroft Center: Allied Deterrence in the Space Domain",
            "date": "2026-12-02",
            "category": "Webinars",
            "location": "Virtual / Washington, DC",
            "description": "Strategic roundtable with Five Eyes space commanders on combined operations and counterspace escalation response options.",
            "url": "https://www.atlanticcouncil.org/events/",
            "source": "Atlantic Council",
            "is_golden_dome": True
        }
    ]

    # =========================================================================
    # 3. MILITARY EXERCISES & WARGAMES CATALOG
    # =========================================================================
    MILITARY_EXERCISES_CATALOG = [
        # --- USSPACECOM & STARCOM ---
        {
            "title": "Exercise Space Flag 27-1",
            "date": "2026-11-09",
            "category": "Military Exercises",
            "location": "Schriever SFB, CO",
            "description": "STARCOM advanced tactical battlespace exercise simulating contested orbital warfighting, electronic warfare jamming, and co-orbital counterspace threats.",
            "url": "https://www.starcom.spaceforce.mil/",
            "source": "USSF STARCOM",
            "is_golden_dome": True
        },
        {
            "title": "Exercise Black Skies 27-1",
            "date": "2026-12-07",
            "category": "Military Exercises",
            "location": "Peterson SFB, CO",
            "description": "STARCOM live-fire tactical electronic warfare exercise training Guardians to operate through contested electromagnetic spectrum jamming.",
            "url": "https://www.starcom.spaceforce.mil/",
            "source": "USSF STARCOM",
            "is_golden_dome": True
        },
        {
            "title": "Exercise Global Sentinel 27",
            "date": "2027-01-18",
            "category": "Military Exercises",
            "location": "Vandenberg SFB, CA",
            "description": "USSPACECOM premier multinational space domain awareness exercise integrating 25+ allied space operations centers in combined sensor data sharing.",
            "url": "https://www.spacecom.mil/",
            "source": "USSPACECOM",
            "is_golden_dome": True
        },
        {
            "title": "Exercise Red Skies 27-1",
            "date": "2027-02-15",
            "category": "Military Exercises",
            "location": "Schriever SFB, CO",
            "description": "Orbital warfare sprint testing satellite defensive maneuvering, rendezvous operations (RPO), and simulated adversary interception.",
            "url": "https://www.starcom.spaceforce.mil/",
            "source": "USSF STARCOM",
            "is_golden_dome": True
        },
        {
            "title": "Exercise Space Flag 27-2",
            "date": "2027-04-19",
            "category": "Military Exercises",
            "location": "Schriever SFB, CO",
            "description": "Spring iteration of Space Flag focusing on rapid satellite reconstitution, tactically responsive space (TacRS) launch, and multi-orbit custody.",
            "url": "https://www.starcom.spaceforce.mil/",
            "source": "USSF STARCOM",
            "is_golden_dome": True
        },
        {
            "title": "Exercise Polaris Hammer 27",
            "date": "2027-05-10",
            "category": "Military Exercises",
            "location": "Buckley SFB, CO",
            "description": "Space Operations Command (SpOC) C2 stress test validating missile warning and tracking deltas under cyber and anti-satellite attacks.",
            "url": "https://www.spoc.spaceforce.mil/",
            "source": "Space Operations Command",
            "is_golden_dome": True
        },
        {
            "title": "Exercise Thor's Hammer 2027",
            "date": "2027-06-14",
            "category": "Military Exercises",
            "location": "Offutt AFB, NE",
            "description": "USSTRATCOM and USSPACECOM joint strategic deterrence tabletop wargame projecting nuclear and counterspace escalation thresholds.",
            "url": "https://www.stratcom.mil/",
            "source": "USSTRATCOM / USSPACECOM",
            "is_golden_dome": True
        },
        {
            "title": "Apollo Maneuvers 2027",
            "date": "2027-09-13",
            "category": "Military Exercises",
            "location": "Multiple Orbital Regimes",
            "description": "USSPACECOM flagship live-fly space exercise demonstrating dynamic on-orbit satellite servicing, refueling, and non-cooperative orbital logistics.",
            "url": "https://www.spacecom.mil/",
            "source": "USSPACECOM",
            "is_golden_dome": False
        },
        {
            "title": "Schriever Wargame 2027",
            "date": "2027-10-18",
            "category": "Military Exercises",
            "location": "Maxwell AFB, AL",
            "description": "Strategic-level multi-domain wargame projecting space conflict scenarios 10 years into the future with Five Eyes and NATO allies.",
            "url": "https://www.spacecom.mil/",
            "source": "USSF / Air University",
            "is_golden_dome": True
        },

        # --- INDOPACOM ---
        {
            "title": "Exercise Keen Sword 27",
            "date": "2026-10-23",
            "category": "Military Exercises",
            "location": "Japan / Western Pacific",
            "description": "US-Japan bilateral field training exercise integrating Japan Self-Defense Forces Space Operations Group with USSPACECOM assets.",
            "url": "https://www.pacom.mil/",
            "source": "INDOPACOM / JSDF",
            "is_golden_dome": False
        },
        {
            "title": "Exercise Balikatan 2027",
            "date": "2027-04-20",
            "category": "Military Exercises",
            "location": "Northern Luzon / South China Sea",
            "description": "Major US-Philippines bilateral exercise incorporating space-based maritime domain awareness, Starlink comms, and coastal missile defense.",
            "url": "https://www.pacom.mil/",
            "source": "INDOPACOM",
            "is_golden_dome": False
        },
        {
            "title": "Exercise Valiant Shield 2027",
            "date": "2027-06-07",
            "category": "Military Exercises",
            "location": "Guam / Mariana Islands Range Complex",
            "description": "Joint all-domain field exercise linking sea, land, air, cyber, and space sensors into a unified sensor-to-shooter kill-web.",
            "url": "https://www.pacom.mil/",
            "source": "INDOPACOM",
            "is_golden_dome": True
        },
        {
            "title": "Exercise Talisman Sabre 2027",
            "date": "2027-07-19",
            "category": "Military Exercises",
            "location": "Queensland, Australia",
            "description": "US-Australia multi-domain exercise featuring deployed Space Operations Command elements and space surveillance radar links.",
            "url": "https://www.pacom.mil/",
            "source": "INDOPACOM / ADF",
            "is_golden_dome": False
        },
        {
            "title": "Exercise Pacific Vanguard 2027",
            "date": "2027-08-23",
            "category": "Military Exercises",
            "location": "Philippine Sea / Guam",
            "description": "Multilateral naval exercise with Japan, Australia, and South Korea exercising tactical space intelligence and missile defense links.",
            "url": "https://www.pacom.mil/",
            "source": "INDOPACOM",
            "is_golden_dome": True
        },

        # --- SOCOM ---
        {
            "title": "Exercise Fused Response / Southern Star 27",
            "date": "2027-03-22",
            "category": "Military Exercises",
            "location": "Antofagasta, Chile",
            "description": "Special operations crisis-action and rapid space-enabled deployment drill integrating commercial satellite imagery.",
            "url": "https://www.socom.mil/",
            "source": "USSOCOM / SOUTHCOM",
            "is_golden_dome": False
        },
        {
            "title": "Exercise Sonic Spear 27",
            "date": "2027-04-12",
            "category": "Military Exercises",
            "location": "MacDill AFB / Key West, FL",
            "description": "SOCOM signature multi-domain exercise synchronizing special operations effects across every spectrum from seabed to low-Earth orbit.",
            "url": "https://www.socom.mil/",
            "source": "USSOCOM",
            "is_golden_dome": True
        },
        {
            "title": "Exercise Fuerzas Comando 2027",
            "date": "2027-06-21",
            "category": "Military Exercises",
            "location": "Dominican Republic",
            "description": "Special operations counter-terrorism competition, joint C2, and operational security seminar across Latin America.",
            "url": "https://www.socom.mil/",
            "source": "USSOCOM / SOUTHCOM",
            "is_golden_dome": False
        },

        # --- Allied & NATO ---
        {
            "title": "Exercise AsterX 2027",
            "date": "2027-03-08",
            "category": "Military Exercises",
            "location": "Toulouse, France",
            "description": "French Space Command (CDE) simulated military space exercise with NATO, CSpO, and German Space Command defending orbital infrastructure.",
            "url": "https://www.defense.gouv.fr/air",
            "source": "French Space Command (CDE)",
            "is_golden_dome": True
        },
        {
            "title": "Exercise Nordic Response 2027",
            "date": "2027-03-15",
            "category": "Military Exercises",
            "location": "Arctic Norway / Sweden",
            "description": "NATO high-latitude cold-weather exercise stressing polar satellite communications and Space Domain Awareness in GPS-denied environments.",
            "url": "https://www.nato.int/",
            "source": "NATO Allied Command",
            "is_golden_dome": False
        }
    ]

    # =========================================================================
    # 4. PURE-PLAY SPACE & DEFENSE PRIME EARNINGS CALLS
    # =========================================================================
    EARNINGS_CYCLES = [
        {"ticker": "LMT", "company": "Lockheed Martin", "period": "Q3 2026 Earnings", "date": "2026-10-20", "source": "Lockheed Martin IR", "url": "https://investors.lockheedmartin.com/", "is_gd": True},
        {"ticker": "RTX", "company": "RTX (Raytheon)", "period": "Q3 2026 Earnings", "date": "2026-10-22", "source": "RTX IR", "url": "https://www.rtx.com/investors", "is_gd": True},
        {"ticker": "NOC", "company": "Northrop Grumman", "period": "Q3 2026 Earnings", "date": "2026-10-22", "source": "Northrop Grumman IR", "url": "https://investor.northropgrumman.com/", "is_gd": True},
        {"ticker": "LHX", "company": "L3Harris Technologies", "period": "Q3 2026 Earnings", "date": "2026-10-29", "source": "L3Harris IR", "url": "https://www.l3harris.com/investors", "is_gd": True},
        {"ticker": "RKLB", "company": "Rocket Lab USA", "period": "Q3 2026 Financial Results", "date": "2026-11-05", "source": "Rocket Lab IR", "url": "https://investors.rocketlabusa.com/", "is_gd": False},
        {"ticker": "ASTS", "company": "AST SpaceMobile", "period": "Q3 2026 Business Update", "date": "2026-11-09", "source": "AST SpaceMobile IR", "url": "https://ast-science.com/investors/", "is_gd": False},
        {"ticker": "BKSY", "company": "BlackSky Technology", "period": "Q3 2026 Financial Results", "date": "2026-11-10", "source": "BlackSky IR", "url": "https://ir.blacksky.com/", "is_gd": False},
        {"ticker": "LUNR", "company": "Intuitive Machines", "period": "Q3 2026 Earnings Call", "date": "2026-11-12", "source": "Intuitive Machines IR", "url": "https://investors.intuitivemachines.com/", "is_gd": False},
        {"ticker": "PL", "company": "Planet Labs PBC", "period": "Q3 FY27 Financial Results", "date": "2026-12-08", "source": "Planet IR", "url": "https://investors.planet.com/", "is_gd": False},
        {"ticker": "LMT", "company": "Lockheed Martin", "period": "Q4 & FY2026 Earnings", "date": "2027-01-26", "source": "Lockheed Martin IR", "url": "https://investors.lockheedmartin.com/", "is_gd": True},
        {"ticker": "NOC", "company": "Northrop Grumman", "period": "Q4 & FY2026 Earnings", "date": "2027-01-28", "source": "Northrop Grumman IR", "url": "https://investor.northropgrumman.com/", "is_gd": True},
        {"ticker": "RKLB", "company": "Rocket Lab USA", "period": "Q4 & FY2026 Financial Results", "date": "2027-02-25", "source": "Rocket Lab IR", "url": "https://investors.rocketlabusa.com/", "is_gd": False}
    ]

    def __init__(self):
        self.congress_api_key = os.getenv("CONGRESS_GOV_API_KEY")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) SpaceCalendarEngine/3.5",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        })

    def fetch_launch_library_manifest(self) -> List[Dict[str, Any]]:
        """Queries Launch Library 2 for live global orbital launch manifests."""
        logging.info("Querying Launch Library 2 for worldwide orbital manifests...")
        launches = []
        try:
            resp = self.session.get(self.LL2_UPCOMING_URL, timeout=10)
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                for item in results:
                    name = item.get("name", "")
                    net = item.get("net", "")
                    pad = item.get("pad", {}).get("name", "")
                    location = item.get("pad", {}).get("location", {}).get("name", "Spaceport")
                    mission = item.get("mission", {}) or {}
                    mission_desc = mission.get("description", "Orbital spaceflight mission.")
                    provider = item.get("launch_service_provider", {}).get("name", "Launch Provider")

                    if not name or not net:
                        continue

                    iso_date = net[:10]
                    display_date = iso_date
                    try:
                        dt = datetime.strptime(iso_date, "%Y-%m-%d")
                        display_date = dt.strftime("%b %d, %Y")
                    except Exception:
                        pass

                    loc_str = f"{pad}, {location}" if pad and location else (location or "Global Spaceport")
                    rel = evaluate_relevance(f"{name} {mission_desc}")

                    launches.append({
                        "date": iso_date,
                        "display_date": display_date,
                        "title": f"{provider} • {name}",
                        "category": "Launches",
                        "location": loc_str[:55],
                        "description": mission_desc[:380],
                        "url": "https://spaceflightnow.com/",
                        "source": f"Global Manifest ({provider})",
                        "is_golden_dome": rel["is_golden_dome"]
                    })
        except Exception as e:
            logging.error(f"Error querying Launch Library 2: {e}")
        return launches

    def fetch_spaceflight_now_launches(self) -> List[Dict[str, Any]]:
        """Scrapes Spaceflight Now launch manifest."""
        logging.info("Scraping Spaceflight Now launch manifest...")
        launches = []
        try:
            resp = self.session.get(self.SPACENOW_LAUNCH_URL, timeout=10)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                blocks = soup.find_all("div", class_=re.compile(r"launch|entry|post", re.I))

                for block in blocks:
                    text = block.get_text(" ", strip=True)
                    if not any(k in text.lower() for k in ["launch site", "mission:", "payload", "rocket:"]):
                        continue

                    h_tag = block.find(["h2", "h3", "h4", "header"])
                    title = h_tag.get_text(strip=True) if h_tag else ""
                    if len(title) < 10:
                        continue

                    date_m = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:,\s+\d{4})?', text, re.I)
                    launch_date_str = date_m.group(0) if date_m else "Upcoming"

                    iso_date = "2026-10-20"
                    try:
                        date_cleaned = launch_date_str
                        if "202" not in date_cleaned:
                            date_cleaned += f", {datetime.now(timezone.utc).year}"
                        dt = datetime.strptime(date_cleaned.replace(".", ""), "%b %d, %Y")
                        iso_date = dt.strftime("%Y-%m-%d")
                    except Exception:
                        pass

                    loc_m = re.search(r'Launch (?:site|site:)\s*([^•\n]+)', text, re.I)
                    location = loc_m.group(1).strip() if loc_m else "Cape Canaveral SLC-40"

                    launches.append({
                        "date": iso_date,
                        "display_date": launch_date_str,
                        "title": title[:140],
                        "category": "Launches",
                        "location": location[:50],
                        "description": text[:350],
                        "url": self.SPACENOW_LAUNCH_URL,
                        "source": "Spaceflight Now Manifest",
                        "is_golden_dome": bool(re.search(r'missile|warning|tracking|sda|tranche|pwsa', text, re.I))
                    })
        except Exception as e:
            logging.error(f"Error scraping Spaceflight Now: {e}")
        return launches

    def fetch_spacepolicyonline_calendar(self) -> List[Dict[str, Any]]:
        """Parses SpacePolicyOnline.com upcoming policy events and briefings."""
        logging.info("Ingesting SpacePolicyOnline.com upcoming events...")
        events = []
        try:
            resp = self.session.get(self.SPACEPOLICY_FEED_URL, timeout=10)
            if resp.status_code == 200:
                root = ET.fromstring(resp.text)
                for item in root.findall(".//item"):
                    title = (item.findtext("title") or "").strip()
                    desc = (item.findtext("description") or "").strip()
                    link = (item.findtext("link") or "").strip()
                    pub = (item.findtext("pubDate") or "").strip()

                    if "what's happening" in title.lower() or "calendar" in title.lower() or "/events/" in link:
                        clean_desc
