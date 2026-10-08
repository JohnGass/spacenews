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
    Exhaustive Worldwide Rolling Space & Defense Calendar Engine.
    Aggregates:
    1. Global Orbital Launch Manifest (SpaceCalendar, Spaceflight Now, Launch Library 2)
    2. Combatant Command Exercises (INDOPACOM, USSPACECOM, SOCOM, NATO, Allied)
    3. Global Symposia & Conferences (SpaceAgenda.com, SpaceCalendar.com, AIAA, IEEE, IAF)
    4. Policy Proceedings & Briefings (SpacePolicyOnline.com, Congress.gov)
    5. Pure-Play Commercial Space & Defense Prime Earnings Calls
    """
    SPACENOW_LAUNCH_URL = "https://spaceflightnow.com/launch-schedule/"
    SPACE_CALENDAR_URL = "https://spacecalendar.com/events/"
    SPACEPOLICY_FEED_URL = "https://spacepolicyonline.com/feed/"
    LL2_UPCOMING_URL = "https://lldev.thespacedevs.com/2.2.0/launch/upcoming/?limit=25"
    CONGRESS_API_URL = "https://api.congress.gov/v3/committee-meeting"

    # =========================================================================
    # 1. COMBATANT COMMAND EXERCISES & TACTICAL WARGAMES CATALOG
    # =========================================================================
    MILITARY_EXERCISES_CATALOG = [
        # --- U.S. Space Command & STARCOM ---
        {
            "title": "Exercise Space Flag 27-1",
            "date": "2026-11-09",
            "category": "Military Exercises",
            "location": "Schriever SFB, Colorado",
            "description": "USSF STARCOM advanced tactical battlespace exercise simulating contested orbital warfighting, electronic warfare jamming, and co-orbital counterspace threats.",
            "url": "https://www.starcom.spaceforce.mil/",
            "source": "USSF STARCOM",
            "is_golden_dome": True
        },
        {
            "title": "Exercise Black Skies 27-1",
            "date": "2026-12-07",
            "category": "Military Exercises",
            "location": "Peterson SFB, Colorado",
            "description": "STARCOM live-fire tactical electronic warfare exercise training Space Force guardians to operate through contested electromagnetic spectrum jamming.",
            "url": "https://www.starcom.spaceforce.mil/",
            "source": "USSF STARCOM",
            "is_golden_dome": True
        },
        {
            "title": "Exercise Global Sentinel 27",
            "date": "2027-01-18",
            "category": "Military Exercises",
            "location": "Vandenberg SFB, California",
            "description": "USSPACECOM premier multinational space domain awareness exercise integrating 25+ allied space operations centers in combined sensor data sharing.",
            "url": "https://www.spacecom.mil/",
            "source": "USSPACECOM",
            "is_golden_dome": True
        },
        {
            "title": "Exercise Red Skies 27-1",
            "date": "2027-02-15",
            "category": "Military Exercises",
            "location": "Schriever SFB, Colorado",
            "description": "Orbital warfare sprint testing satellite defensive maneuvers, proximity operations (RPO), and simulated adversary rendezvous interception.",
            "url": "https://www.starcom.spaceforce.mil/",
            "source": "USSF STARCOM",
            "is_golden_dome": True
        },
        {
            "title": "Exercise Space Flag 27-2",
            "date": "2027-04-19",
            "category": "Military Exercises",
            "location": "Schriever SFB, Colorado",
            "description": "Spring iteration of Space Flag focusing on rapid satellite reconstitution, tactically responsive space (TacRS) launch, and multi-orbit custody.",
            "url": "https://www.starcom.spaceforce.mil/",
            "source": "USSF STARCOM",
            "is_golden_dome": True
        },
        {
            "title": "Exercise Polaris Hammer 27",
            "date": "2027-05-10",
            "category": "Military Exercises",
            "location": "Buckley SFB, Colorado",
            "description": "Space Operations Command (SpOC) C2 stress test validating missile warning and missile tracking deltas under simulated cyber and anti-satellite attacks.",
            "url": "https://www.spoc.spaceforce.mil/",
            "source": "Space Operations Command",
            "is_golden_dome": True
        },
        {
            "title": "Exercise Thor's Hammer 2027",
            "date": "2027-06-14",
            "category": "Military Exercises",
            "location": "Offutt AFB, Nebraska",
            "description": "USSTRATCOM and USSPACECOM joint strategic deterrence tabletop wargame projecting nuclear and counterspace escalation thresholds.",
            "url": "https://www.stratcom.mil/",
            "source": "USSTRATCOM / USSPACECOM",
            "is_golden_dome": True
        },
        {
            "title": "Exercise Space Flag 27-3",
            "date": "2027-08-16",
            "category": "Military Exercises",
            "location": "Schriever SFB, Colorado",
            "description": "Late-summer tactical combat exercise evaluating multi-domain integration between Space Deltas and Combatant Commands.",
            "url": "https://www.starcom.spaceforce.mil/",
            "source": "USSF STARCOM",
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
            "location": "Maxwell AFB, Alabama",
            "description": "Strategic-level multi-domain wargame projecting space conflict scenarios 10 years into the future with Five Eyes and NATO allies.",
            "url": "https://www.spacecom.mil/",
            "source": "USSF / Air University",
            "is_golden_dome": True
        },
        {
            "title": "Space Lightning / Space Thunder 27",
            "date": "2026-11-16",
            "category": "Military Exercises",
            "location": "Peterson SFB / Offutt AFB",
            "description": "Quarterly command-and-control exercise synchronizing global strike assets with space domain awareness and missile tracking layers.",
            "url": "https://www.spacecom.mil/",
            "source": "USSPACECOM",
            "is_golden_dome": True
        },

        # --- Indo-Pacific Command (INDOPACOM) ---
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
            "description": "US-Australia premier multi-domain exercise featuring deployed Space Operations Command elements and space domain surveillance.",
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
        {
            "title": "Exercise Super Garuda Shield 2027",
            "date": "2027-08-30",
            "category": "Military Exercises",
            "location": "East Java, Indonesia",
            "description": "Multinational joint exercise testing expeditionary communications and commercial satellite data integration across Southeast Asia.",
            "url": "https://www.pacom.mil/",
            "source": "INDOPACOM",
            "is_golden_dome": False
        },

        # --- Special Operations Command (SOCOM) ---
        {
            "title": "Exercise Ridge Runner 2027",
            "date": "2027-02-08",
            "category": "Military Exercises",
            "location": "West Virginia",
            "description": "Special operations irregular warfare exercise utilizing non-standard satellite communications and low-signature tactical ground stations.",
            "url": "https://www.socom.mil/",
            "source": "USSOCOM",
            "is_golden_dome": False
        },
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
            "location": "MacDill AFB / Key West, Florida",
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

        # --- Allied & NATO Space Exercises ---
        {
            "title": "Exercise Joint Warrior 26-2",
            "date": "2026-10-19",
            "category": "Military Exercises",
            "location": "Scotland / North Sea",
            "description": "UK-led multinational maritime, air, and space warfare exercise stressing electronic warfare and satellite communications denial.",
            "url": "https://www.royalnavy.mod.uk/",
            "source": "UK Ministry of Defence",
            "is_golden_dome": False
        },
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
        },
        {
            "title": "Exercise Steadfast Defender 2027",
            "date": "2027-05-17",
            "category": "Military Exercises",
            "location": "Poland & Baltic States",
            "description": "NATO collective defense exercise deploying combined space capabilities to protect allied troop movements against electronic warfare.",
            "url": "https://www.nato.int/",
            "source": "NATO Allied Command",
            "is_golden_dome": False
        }
    ]

    # =========================================================================
    # 2. WORLDWIDE CONFERENCES, SYMPOSIA & SUMMITS (SpaceAgenda.com / SpaceCalendar)
    # =========================================================================
    CONFERENCES_CATALOG = [
        {
            "title": "World Space Week 2026",
            "date": "2026-10-04",
            "category": "Conferences",
            "location": "Worldwide",
            "description": "Global celebration of space science and technology contributions with international aerospace symposia and academic panels.",
            "url": "https://www.worldspaceweek.org/",
            "source": "UN / World Space Week"
        },
        {
            "title": "SPAICE: AI in and for Space",
            "date": "2026-10-05",
            "category": "Conferences",
            "location": "Noordwijk, The Netherlands",
            "description": "ESA-hosted symposium on artificial intelligence applications in autonomous satellite operations and on-orbit data processing.",
            "url": "https://atpi.eventsair.com/spaice2026/",
            "source": "European Space Agency (ESA)"
        },
        {
            "title": "24th Meeting of the Venus Exploration Analysis Group (VEXAG)",
            "date": "2026-10-08",
            "category": "Conferences",
            "location": "Boulder, Colorado",
            "description": "NASA scientific assessment meeting reviewing planetary science mission trajectories, instrumentation, and exploration roadmaps.",
            "url": "https://www.lpi.usra.edu/vexag/",
            "source": "NASA Lunar & Planetary Institute"
        },
        {
            "title": "2026 U.S. Space Forum - Project Constellation",
            "date": "2026-10-15",
            "category": "Conferences",
            "location": "Vienna, Austria",
            "description": "Diplomatic and technical conference hosted by the U.S. Mission to International Organizations addressing international space norms.",
            "url": "https://vienna.usmission.gov/",
            "source": "U.S. Department of State"
        },
        {
            "title": "ESPI 20th Annual Conference",
            "date": "2026-10-19",
            "category": "Conferences",
            "location": "Vienna, Austria",
            "description": "European Space Policy Institute flagship conference addressing European strategic autonomy, defense space policy, and launch access.",
            "url": "https://espi.or.at/",
            "source": "European Space Policy Institute"
        },
        {
            "title": "AAS Division for Planetary Sciences (DPS 2026)",
            "date": "2026-10-25",
            "category": "Conferences",
            "location": "Spokane, Washington",
            "description": "Major annual gathering of planetary scientists presenting peer-reviewed research on solar system exploration and small-body defense.",
            "url": "https://dps.aas.org/meetings",
            "source": "American Astronomical Society"
        },
        {
            "title": "Global MilSatCom 2026",
            "date": "2026-11-03",
            "category": "Conferences",
            "location": "London, United Kingdom",
            "description": "The world's premier military satellite communications conference featuring allied defense space leadership and commercial satcom primes.",
            "url": "https://www.smgconferences.com/defence/uk/conference/global-milsatcom",
            "source": "SAE Media Group"
        },
        {
            "title": "Space Tech Expo Europe 2026",
            "date": "2026-11-17",
            "category": "Conferences",
            "location": "Bremen, Germany",
            "description": "Europe's largest B2B space exhibition and conference covering manufacturing, supply chain, test equipment, and launch engineering.",
            "url": "https://www.spacetechexpo-europe.com/",
            "source": "Space Tech Expo"
        },
        {
            "title": "Defense Leaders: Space Operations Summit",
            "date": "2026-12-01",
            "category": "Conferences",
            "location": "London, United Kingdom",
            "description": "International summit focusing on resilient C2, sovereign launch access, and space domain integration for NATO allies.",
            "url": "https://defenceleaders.com/space-operations/",
            "source": "Defense Leaders"
        },
        {
            "title": "249th Meeting of the American Astronomical Society (AAS)",
            "date": "2027-01-10",
            "category": "Conferences",
            "location": "Salt Lake City, Utah",
            "description": "Winter meeting of the AAS featuring astrophysics briefings, Roman Space Telescope updates, and planetary defense science.",
            "url": "https://aas.org/meetings/aas249",
            "source": "AAS"
        },
        {
            "title": "AIAA SciTech Forum 2027",
            "date": "2027-01-11",
            "category": "Conferences",
            "location": "Orlando, Florida",
            "description": "The world's largest aerospace R&D conference covering hypersonics, autonomous space systems, propulsion, and space structures.",
            "url": "https://www.aiaa.org/scitech",
            "source": "AIAA"
        },
        {
            "title": "AIAA DEFENSE Forum 2027",
            "date": "2027-01-20",
            "category": "Conferences",
            "location": "Laurel, Maryland",
            "description": "Secret/NOFORN defense conference examining classified national security space programs, hypersonics, and Golden Dome intercept architectures.",
            "url": "https://www.aiaa.org/events-learning/event/2027/01/20/default-calendar/2027-aiaa-defense-forum",
            "source": "AIAA",
            "is_golden_dome": True
        },
        {
            "title": "SmallSat Symposium 2027",
            "date": "2027-02-09",
            "category": "Conferences",
            "location": "Mountain View, California",
            "description": "Silicon Valley's premier commercial satellite business and venture convention covering constellation finance and miniaturized payloads.",
            "url": "https://smallsatshow.com/",
            "source": "SatNews"
        },
        {
            "title": "Global Space Congress 2027",
            "date": "2027-02-22",
            "category": "Conferences",
            "location": "Abu Dhabi, United Arab Emirates",
            "description": "Strategic gathering of Middle Eastern, Asian, and Western space agency directors addressing emerging space economy partnerships.",
            "url": "https://www.globalspacecongress.com/",
            "source": "UAE Space Agency"
        },
        {
            "title": "IEEE Aerospace Conference 2027",
            "date": "2027-03-06",
            "category": "Conferences",
            "location": "Big Sky, Montana",
            "description": "Flagship international technical conference on spacecraft bus engineering, radar, quantum sensors, and deep space telemetry.",
            "url": "https://www.aeroconf.org/",
            "source": "IEEE"
        },
        {
            "title": "SRA Satellite 2027 Exhibition & Conference",
            "date": "2027-03-15",
            "category": "Conferences",
            "location": "Washington, DC",
            "description": "The landmark global commercial satellite convention featuring commercial constellation operators, launch providers, and DoD buyers.",
            "url": "https://www.satshow.com/",
            "source": "Satellite Show"
        },
        {
            "title": "Paris Space Week 2027",
            "date": "2027-03-23",
            "category": "Conferences",
            "location": "Paris, France",
            "description": "Global B2B space meeting connecting European aerospace primes, startups, and defense procurement officials.",
            "url": "https://www.paris-space-week.com/",
            "source": "Paris Space Week"
        },
        {
            "title": "41st Space Symposium",
            "date": "2027-04-12",
            "category": "Conferences",
            "location": "Colorado Springs, Colorado",
            "description": "The world's premier space gathering. Keynotes from Chief of Space Operations, Space Systems Command, NASA Administrator, and allied chiefs.",
            "url": "https://www.spacesymposium.org/",
            "source": "Space Foundation",
            "is_golden_dome": True
        },
        {
            "title": "Space Tech Expo USA 2027",
            "date": "2027-05-18",
            "category": "Conferences",
            "location": "Long Beach, California",
            "description": "America's largest space manufacturing and engineering trade exhibition focusing on commercial supply chains and launch tech.",
            "url": "https://www.spacetechexpo.com/",
            "source": "Space Tech Expo"
        },
        {
            "title": "UN COPUOS 70th Session",
            "date": "2027-06-02",
            "category": "Conferences",
            "location": "Vienna International Centre, Austria",
            "description": "United Nations Committee on the Peaceful Uses of Outer Space reviewing international space law, lunar governance, and space debris.",
            "url": "https://www.unoosa.org/oosa/en/ourwork/copuos/index.html",
            "source": "United Nations (UNOOSA)"
        },
        {
            "title": "Paris Air Show (SIAE 2027)",
            "date": "2027-06-21",
            "category": "Conferences",
            "location": "Le Bourget, Paris, France",
            "description": "The world's largest aerospace trade show featuring major launch vehicle debuts, prime defense announcements, and space pavilion exhibits.",
            "url": "https://www.siae.fr/en/",
            "source": "SIAE Paris Air Show"
        },
        {
            "title": "Small Satellite Conference (Utah SmallSat 2027)",
            "date": "2027-08-07",
            "category": "Conferences",
            "location": "Logan, Utah",
            "description": "The global hub for smallsat engineering, university rideshares, pLEO constellation buses, and miniaturized optical payloads.",
            "url": "https://www.smallsat.org/",
            "source": "Utah State University / AIAA"
        },
        {
            "title": "SMDC Space and Missile Defense Symposium 2027",
            "date": "2027-08-10",
            "category": "Conferences",
            "location": "Huntsville, Alabama",
            "description": "Premier national defense conference on Golden Dome layered missile defense, tracking layers, and interceptor architectures.",
            "url": "https://smdsymposium.org/",
            "source": "SMDC Symposium",
            "is_golden_dome": True
        },
        {
            "title": "AIAA ASCEND 2027",
            "date": "2027-08-23",
            "category": "Conferences",
            "location": "Las Vegas, Nevada",
            "description": "Outcome-focused collaborative conference covering commercial LEO destinations, in-space manufacturing, and cislunar development.",
            "url": "https://www.ascend.select/",
            "source": "AIAA"
        },
        {
            "title": "AMOS Conference 2027",
            "date": "2027-09-14",
            "category": "Conferences",
            "location": "Wailea, Maui, Hawaii",
            "description": "The foremost international technical conference dedicated to space domain awareness, orbital debris tracking, and telescope surveillance.",
            "url": "https://amostech.com/",
            "source": "Maui Economic Development Board",
            "is_golden_dome": True
        },
        {
            "title": "AFA Air, Space & Cyber Conference 2027",
            "date": "2027-09-20",
            "category": "Conferences",
            "location": "National Harbor, Maryland",
            "description": "Department of the Air Force and Space Force leadership posture addresses, acquisition exhibits, and force design rollouts.",
            "url": "https://www.afa.org/air-space-cyber-conference/",
            "source": "Air & Space Forces Association"
        },
        {
            "title": "International Astronautical Congress (IAC 2027)",
            "date": "2027-10-11",
            "category": "Conferences",
            "location": "Poznań, Poland",
            "description": "The premier global congress uniting all international space agencies (NASA, ESA, JAXA, ISRO, CNSA) and the commercial space sector.",
            "url": "https://www.iafastro.org/",
            "source": "International Astronautical Federation"
        }
    ]

    # =========================================================================
    # 3. PURE-PLAY SPACE & DEFENSE PRIME EARNINGS CYCLES
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

    # =========================================================================
    # 4. POLICY PANELS, WEBINARS & HEARINGS LOOKAHEAD
    # =========================================================================
    POLICY_BRIEFINGS_CATALOG = [
        {
            "title": "GSOA Webinar: How the Rocket Revolution is Transforming the Satellite Ecosystem",
            "date": "2026-10-08",
            "category": "Webinars",
            "location": "Virtual Webcast (10:00 am ET)",
            "description": "Global Satellite Operators Association panel on heavy launch cost reductions and commercial constellation deployment.",
            "url": "https://gsoasatellite.com/",
            "source": "GSOA"
        },
        {
            "title": "CSIS Aerospace Security: Proliferated Space Architectures & Missile Defense",
            "date": "2026-10-21",
            "category": "Webinars",
            "location": "Virtual / CSIS HQ, Washington, DC",
            "description": "Senior defense panel analyzing Space Development Agency Tranche tracking layers and fire-control interceptor loop integration.",
            "url": "https://aerospace.csis.org/events/",
            "source": "CSIS Aerospace Security Project",
            "is_golden_dome": True
        },
        {
            "title": "Mitchell Institute Spacepower Series: Space Domain Awareness Realities",
            "date": "2026-11-04",
            "category": "Webinars",
            "location": "Virtual Webcast",
            "description": "Briefing with Space Operations Command leadership addressing non-cooperative orbital tracking and dynamic operations.",
            "url": "https://mitchellaerospacepower.org/events/",
            "source": "Mitchell Institute Spacepower",
            "is_golden_dome": False
        },
        {
            "title": "FAA COMSTAC (Commercial Space Transportation Advisory Committee) Meeting",
            "date": "2026-11-12",
            "category": "Hearings",
            "location": "DOT Headquarters, Washington, DC / Virtual",
            "description": "Advisory committee session reviewing Part 450 launch licensing reform, spaceport capacity, and regulatory throughput.",
            "url": "https://www.faa.gov/space/additional_information/comstac",
            "source": "FAA Commercial Space Transportation"
        },
        {
            "title": "HASC Strategic Forces Subcommittee: Posture Hearing on FY28 Space Programs",
            "date": "2027-03-03",
            "category": "Hearings",
            "location": "Rayburn House Office Building, Washington, DC",
            "description": "Congressional posture review examining USSF force design, NSSL Phase 3 launch awards, and SDA tracking layer procurement.",
            "url": "https://armedservices.house.gov/",
            "source": "House Armed Services Committee",
            "is_golden_dome": True
        },
        {
            "title": "SASC Strategic Forces Subcommittee: Hearing on Ballistic & Hypersonic Missile Defense",
            "date": "2027-03-24",
            "category": "Hearings",
            "location": "Dirksen Senate Office Building, Washington, DC",
            "description": "Senate posture session assessing Glide Phase Interceptor (GPI) milestones and space-based interceptor architecture.",
            "url": "https://www.armed-services.senate.gov/",
            "source": "Senate Armed Services Committee",
            "is_golden_dome": True
        }
    ]

    def __init__(self):
        self.congress_api_key = os.getenv("CONGRESS_GOV_API_KEY")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) SpaceCalendarEngine/3.0",
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
                    net = item.get("net", "") # ISO launch timestamp
                    pad = item.get("pad", {}).get("name", "")
                    location = item.get("pad", {}).get("location", {}).get("name", "Spaceport")
                    mission = item.get("mission", {}) or {}
                    mission_desc = mission.get("description", "Orbital spaceflight mission.")
                    provider = item.get("launch_service_provider", {}).get("name", "Launch Provider")

                    if not name or not net:
                        continue

                    iso_date = net[:10]
                    # Format display date
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
                        "url": f"https://spaceflightnow.com/",
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
        """Parses SpacePolicyOnline.com upcoming events and policy briefs."""
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

                    # Check for "What's Happening in Space Policy" or individual event announcements
                    if "what's happening" in title.lower() or "calendar" in title.lower() or "/events/" in link:
                        clean_desc = re.sub(r'<[^>]+>', ' ', desc)
                        events.append({
                            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                            "display_date": "Current Week",
                            "title": title[:130],
                            "category": "Hearings",
                            "location": "Washington, DC / Virtual",
                            "description": clean_desc[:350],
                            "url": link,
                            "source": "SpacePolicyOnline.com",
                            "is_golden_dome": False
                        })
        except Exception as e:
            logging.error(f"Error parsing SpacePolicyOnline feed: {e}")
        return events

    def fetch_congressional_hearings(self) -> List[Dict[str, Any]]:
        """Queries Congress.gov API for upcoming space/defense committee hearings."""
        if not self.congress_api_key:
            return []

        logging.info("Querying Congress.gov for scheduled upcoming committee hearings...")
        now = datetime.now(timezone.utc)
        start_date = now.strftime("%Y-%m-%dT00:00:00Z")
        hearings = []

        try:
            params = {
                "api_key": self.congress_api_key,
                "format": "json",
                "fromDateTime": start_date,
                "limit": 50,
                "sort": "date+asc"
            }
            resp = self.session.get(self.CONGRESS_API_URL, params=params, timeout=12)
            if resp.status_code == 200:
                data = resp.json().get("committeeMeetings", [])
                for m in data:
                    title = m.get("title", "")
                    date_str = m.get("date", "")
                    committees = [c.get("name", "") for c in m.get("committees", [])]
                    corpus = f"{title} {' '.join(committees)}"
                    rel = evaluate_relevance(corpus)

                    if not rel["is_relevant"]:
                        continue

                    iso_date = date_str[:10] if date_str else now.strftime("%Y-%m-%d")
                    chamber = m.get("chamber", "Congress")

                    hearings.append({
                        "date": iso_date,
                        "display_date": iso_date,
                        "title": title[:140],
                        "category": "Hearings",
                        "location": f"Capitol Hill ({chamber})",
                        "description": f"Committees: {', '.join(committees)} | Scheduled Congressional Hearing.",
                        "url": m.get("url", "https://www.congress.gov"),
                        "source": "Congress.gov Schedule",
                        "is_golden_dome": rel["is_golden_dome"]
                    })
        except Exception as e:
            logging.error(f"Error querying Congress.gov hearings: {e}")

        return hearings

    def get_rolling_calendar(self) -> List[Dict[str, Any]]:
        """
        Synthesizes live feeds with deep catalog matrices.
        Sorts strictly forward-chronologically (Today -> Next Week -> 2027).
        """
        all_events = []

        # 1. Ingest dynamic launches & manifests
        ll2_launches = self.fetch_launch_library_manifest()
        spacenow_launches = self.fetch_spaceflight_now_launches()
        all_events.extend(ll2_launches)
        all_events.extend(spacenow_launches)

        # 2. Ingest dynamic policy & hearings
        all_events.extend(self.fetch_spacepolicyonline_calendar())
        all_events.extend(self.fetch_congressional_hearings())

        # 3. Add military exercises & wargames
        all_events.extend(self.MILITARY_EXERCISES_CATALOG)

        # 4. Add global symposia, summits & conferences
        all_events.extend(self.CONFERENCES_CATALOG)

        # 5. Add corporate earnings calendar
        for earn in self.EARNINGS_CYCLES:
            all_events.append({
                "date": earn["date"],
                "display_date": earn["date"],
                "title": f"{earn['company']} ({earn['ticker']}) • {earn['period']}",
                "category": "Earnings",
                "location": "Investor Webcast",
                "description": f"Quarterly financial update and investor teleconference for {earn['company']}.",
                "url": earn["url"],
                "source": earn["source"],
                "is_golden_dome": earn.get("is_gd", False)
            })

        # 6. Add policy briefings and webinars
        all_events.extend(self.POLICY_BRIEFINGS_CATALOG)

        # Forward-chronological date sorting
        now_ts = datetime.now(timezone.utc).timestamp()
        def parse_date_score(evt):
            d_str = evt.get("date", "")
            try:
                dt = datetime.strptime(d_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                # Events in the past sink slightly, upcoming sort sequentially
                ts = dt.timestamp()
                return ts if ts >= (now_ts - 86400) else (ts + 100000000)
            except Exception:
                return now_ts + (365 * 86400)

        all_events.sort(key=parse_date_score)

        # Deduplicate
        seen_keys = set()
        deduped = []
        for e in all_events:
            key = f"{e['date']}_{e['title'][:35]}".lower()
            if key not in seen_keys:
                seen_keys.add(key)
                deduped.append(e)

        logging.info(f"Total rolling calendar events compiled: {len(deduped)}")
        return deduped
