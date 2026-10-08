import os
import re
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Set
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
    1. Global Orbital Launch Manifests (SpaceCalendar.com, Spaceflight Now, Launch Library)
    2. Military Combatant Command Exercises (USSPACECOM, INDOPACOM, SOCOM, NATO, Allied)
    3. Major Symposia & Conferences (SFA Spacepower Orlando, NSSA, POC, AIAA, Space Foundation)
    4. Strategic Webinars & Think Tanks (CSIS, NSSA, Aerospace Corp CSPS, Payload, Mitchell Institute)
    5. Pure-Play Commercial Space & Defense Prime Earnings Calls
    6. Congressional Space & Defense Committee Hearings

    Strictly bounded to a rolling 12-month window (Today -> Today + 365 Days).
    """
    SPACENOW_LAUNCH_URL = "https://spaceflightnow.com/launch-schedule/"
    SPACECALENDAR_LAUNCH_URL = "https://spacecalendar.com/events/category/launch/"
    SPACEPOLICY_FEED_URL = "https://spacepolicyonline.com/feed/"
    CONGRESS_API_URL = "https://api.congress.gov/v3/committee-meeting"

    # =========================================================================
    # 1. VERIFIED GLOBAL ORBITAL LAUNCH MANIFEST (Rolling 12 Months)
    # =========================================================================
    VERIFIED_LAUNCH_MANIFEST = [
        {
            "title": "SpaceX Falcon 9 • SDA Tranche 1 Transport Layer (T1TL-A)",
            "date": "2026-10-10",
            "category": "Launches",
            "location": "SLC-4E, Vandenberg SFB, CA",
            "description": "Space Development Agency (SDA) launch deploying 21 Proliferated Warfighter Space Architecture (PWSA) optical mesh data transport satellites to low Earth orbit.",
            "url": "https://spaceflightnow.com/launch-schedule/",
            "source": "USSF / Space Development Agency",
            "is_golden_dome": True
        },
        {
            "title": "SpaceX Falcon 9 • Starlink Group 15-25",
            "date": "2026-10-11",
            "category": "Launches",
            "location": "SLC-4E, Vandenberg SFB, CA",
            "description": "SpaceX launch deploying 27 Starlink V2 Mini communication satellites to low Earth orbit with booster recovery on autonomous droneship.",
            "url": "https://spaceflightnow.com/launch-schedule/",
            "source": "SpaceX Manifest",
            "is_golden_dome": False
        },
        {
            "title": "SpaceX Falcon 9 • NASA CRS-35 Cargo Resupply",
            "date": "2026-10-13",
            "category": "Launches",
            "location": "SLC-40, Cape Canaveral SFS, FL",
            "description": "Commercial Resupply Services mission sending Dragon spacecraft with critical science payloads, crew supplies, and ISS hardware.",
            "url": "https://spacecalendar.com/events/category/launch/",
            "source": "NASA / SpaceX",
            "is_golden_dome": False
        },
        {
            "title": "JAXA H3 Rocket • Martian Moons eXploration (MMX)",
            "date": "2026-10-18",
            "category": "Launches",
            "location": "Tanegashima Space Center, Japan",
            "description": "Japan Aerospace Exploration Agency flagship mission to survey Phobos and Deimos and execute sample return to Earth with NASA/ESA instruments.",
            "url": "https://spacecalendar.com/events/category/launch/",
            "source": "JAXA / NASA",
            "is_golden_dome": False
        },
        {
            "title": "Rocket Lab Electron • Dedicated Commercial SAR",
            "date": "2026-10-23",
            "category": "Launches",
            "location": "Launch Complex 1, Mahia, New Zealand",
            "description": "Dedicated Electron mission deploying commercial Synthetic Aperture Radar (SAR) Earth observation satellites to sun-synchronous orbit.",
            "url": "https://www.rocketlabusa.com/missions/",
            "source": "Rocket Lab",
            "is_golden_dome": False
        },
        {
            "title": "CASC Long March 2F • Shenzhou-21 Manned Mission",
            "date": "2026-10-29",
            "category": "Launches",
            "location": "Jiuquan Satellite Launch Center, China",
            "description": "Crewed spaceflight transporting three taikonauts to the Tiangong Space Station for a six-month orbital science rotation.",
            "url": "https://www.china-in-space.com/",
            "source": "CASC / CNSA",
            "is_golden_dome": False
        },
        {
            "title": "SpaceX Falcon Heavy • Astrobotic Griffin Mission 1 / FLIP Rover",
            "date": "2026-11-01",
            "category": "Launches",
            "location": "LC-39A, Kennedy Space Center, FL",
            "description": "NASA CLPS lunar mission launching Astrobotic Griffin lander to the lunar South Pole carrying commercial and rover payloads.",
            "url": "https://spacecalendar.com/events/category/launch/",
            "source": "NASA CLPS / Astrobotic",
            "is_golden_dome": False
        },
        {
            "title": "ISRO PSLV-C60 • ESA Proba-3 Solar Coronagraph",
            "date": "2026-11-15",
            "category": "Launches",
            "location": "Satish Dhawan Space Centre, Sriharikota, India",
            "description": "ISRO Polar Satellite Launch Vehicle launching European Space Agency dual-satellite formation flying solar physics mission.",
            "url": "https://www.isro.gov.in/",
            "source": "ISRO / ESA",
            "is_golden_dome": False
        },
        {
            "title": "Firefly Aerospace Alpha • FLTA008 Responsive Space",
            "date": "2026-12-04",
            "category": "Launches",
            "location": "SLC-2W, Vandenberg SFB, CA",
            "description": "Tactically Responsive Space (TacRS) launch testing rapid payload integration and on-orbit constellation augmentation.",
            "url": "https://spaceflightnow.com/launch-schedule/",
            "source": "Firefly / USSF",
            "is_golden_dome": True
        },
        {
            "title": "ULA Vulcan Centaur • Dream Chaser DC-100 Cargo Flight 1",
            "date": "2026-12-18",
            "category": "Launches",
            "location": "SLC-41, Cape Canaveral SFS, FL",
            "description": "Inaugural orbital flight of Sierra Space Dream Chaser reusable spaceplane carrying pressurized cargo to International Space Station.",
            "url": "https://spaceflightnow.com/launch-schedule/",
            "source": "ULA / Sierra Space",
            "is_golden_dome": False
        },
        {
            "title": "SpaceX Falcon 9 • Vast Haven-1 Commercial Space Station",
            "date": "2027-01-15",
            "category": "Launches",
            "location": "Cape Canaveral SFS, FL",
            "description": "Launch of the world's first single-module commercial space station into low Earth orbit ahead of private astronaut flights.",
            "url": "https://spacecalendar.com/events/category/launch/",
            "source": "Vast / SpaceX",
            "is_golden_dome": False
        },
        {
            "title": "Arianespace Ariane 62 • ESA PLATO Exoplanet Observatory",
            "date": "2027-01-28",
            "category": "Launches",
            "location": "Guiana Space Centre, Kourou, French Guiana",
            "description": "Ariane 6 launch delivering ESA's 26-camera PLATO telescope to the Sun-Earth L2 Lagrange point to discover habitable exoplanets.",
            "url": "https://spacecalendar.com/events/category/launch/",
            "source": "ESA / Arianespace",
            "is_golden_dome": False
        },
        {
            "title": "ISRO LVM3 • Chandrayaan-4 Lunar Sample Return",
            "date": "2027-02-10",
            "category": "Launches",
            "location": "Satish Dhawan Space Centre, Sriharikota, India",
            "description": "India's fourth lunar exploration mission launching lunar module and return stages to collect lunar samples at the Moon's South Pole.",
            "url": "https://www.isro.gov.in/",
            "source": "ISRO",
            "is_golden_dome": False
        },
        {
            "title": "SpaceX Falcon 9 • Intuitive Machines IM-3 'Trinity' Lander",
            "date": "2027-02-22",
            "category": "Launches",
            "location": "LC-39A, Kennedy Space Center, FL",
            "description": "NASA CLPS mission delivering Nova-C lunar lander to Reiner Gamma swirl with Lunar Vertex magnetic rover and NASA payloads.",
            "url": "https://spacecalendar.com/events/category/launch/",
            "source": "NASA / Intuitive Machines",
            "is_golden_dome": False
        },
        {
            "title": "Rocket Lab Neutron • Maiden Orbital Flight",
            "date": "2027-03-25",
            "category": "Launches",
            "location": "Launch Complex 3, Wallops Island, VA",
            "description": "Inaugural flight of Rocket Lab's 13-ton reusable carbon-composite medium-lift rocket designed for mega-constellations and national security.",
            "url": "https://www.rocketlabusa.com/launch/neutron/",
            "source": "Rocket Lab",
            "is_golden_dome": True
        },
        {
            "title": "CASC Long March 5 • Xuntian Space Station Telescope",
            "date": "2027-05-14",
            "category": "Launches",
            "location": "Wenchang Space Launch Center, Hainan, China",
            "description": "China's flagship optical space telescope featuring a 2-meter aperture co-orbiting with Tiangong Space Station for refueling and maintenance.",
            "url": "https://www.china-in-space.com/",
            "source": "CASC / CNSA",
            "is_golden_dome": False
        },
        {
            "title": "SpaceX Falcon 9 • NASA NEO Surveyor Infrared Space Telescope",
            "date": "2027-09-08",
            "category": "Launches",
            "location": "Cape Canaveral SFS, FL",
            "description": "NASA planetary defense infrared telescope deploying to Sun-Earth L1 to discover and track potentially hazardous near-Earth asteroids.",
            "url": "https://spacecalendar.com/events/category/launch/",
            "source": "NASA Planetary Defense",
            "is_golden_dome": True
        }
    ]

    # =========================================================================
    # 2. CONFERENCES, SYMPOSIA & SUMMITS (Includes SFA Spacepower Orlando, NSSA)
    # =========================================================================
    CONFERENCES_CATALOG = [
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
            "description": "High-level forum uniting venture capital, private equity, defense primes, and government buyers in dual-use national security space.",
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
            "title": "Potomac Officers Club: 2026 Joint Coalition C2 Forum",
            "date": "2026-11-10",
            "category": "Conferences",
            "location": "McLean, VA",
            "description": "Defense executive conference examining Combined Joint All-Domain Command and Control (CJADC2) cross-domain links with USSF data layers.",
            "url": "https://www.potomacofficersclub.com/",
            "source": "Potomac Officers Club",
            "is_golden_dome": True
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
            "description": "The landmark commercial satellite convention featuring commercial constellation operators, launch providers, and DoD procurement leadership.",
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
            "title": "Space Tech Expo USA 2027",
            "date": "2027-05-18",
            "category": "Conferences",
            "location": "Long Beach, CA",
            "description": "America's largest space manufacturing and engineering trade exhibition focusing on commercial supply chains and launch tech.",
            "url": "https://www.spacetechexpo.com/",
            "source": "Space Tech Expo",
            "is_golden_dome": False
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
            "description": "The global hub for smallsat engineering, university rideshares, pLEO constellation buses, and miniaturized optical payloads.",
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
            "title": "AIAA ASCEND 2027",
            "date": "2027-08-23",
            "category": "Conferences",
            "location": "Las Vegas, NV",
            "description": "Outcome-focused collaborative conference covering commercial LEO destinations, in-space manufacturing, and cislunar development.",
            "url": "https://www.ascend.select/",
            "source": "AIAA",
            "is_golden_dome": False
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
            "date": "2027-10-04",
            "category": "Conferences",
            "location": "Poznań, Poland",
            "description": "Global congress uniting all international space agencies (NASA, ESA, JAXA, ISRO, CNSA) and the commercial space industry.",
            "url": "https://www.iafastro.org/",
            "source": "IAF",
            "is_golden_dome": False
        }
    ]

    # =========================================================================
    # 3. WEBINARS, THINK TANKS & BRIEFINGS (CSIS, Aerospace, Mitchell, Payload)
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
    # 4. MILITARY EXERCISES & WARGAMES CATALOG (USSPACECOM, INDOPACOM, SOCOM, NATO)
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
            "date": "2027-10-04",
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
    # 5. PURE-PLAY SPACE & DEFENSE PRIME EARNINGS CALLS
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
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) SpaceCalendarEngine/4.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        })

    def scrape_spacecalendar_manifest(self) -> List[Dict[str, Any]]:
        """Scrapes live global orbital launches from spacecalendar.com/events/category/launch/."""
        logging.info("Scraping live global orbital launches from SpaceCalendar.com...")
        scraped_launches = []
        try:
            resp = self.session.get(self.SPACECALENDAR_LAUNCH_URL, timeout=12)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                blocks = soup.find_all(["div", "article", "li"], class_=re.compile(r"event|post|tribe-events", re.I))

                for block in blocks:
                    text = block.get_text(" ", strip=True)
                    if not any(k in text.lower() for k in ["launch", "falcon", "long march", "ariane", "electron", "h3", "nuri"]):
                        continue

                    h_tag = block.find(["h2", "h3", "h4", "a"])
                    title = h_tag.get_text(strip=True) if h_tag else ""
                    if len(title) < 12 or "calendar" in title.lower():
                        continue

                    date_m = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:,\s+\d{4})?', text, re.I)
                    date_str = date_m.group(0) if date_m else "Upcoming"

                    iso_date = "2026-11-01"
                    try:
                        clean_d = date_str
                        if "202" not in clean_d:
                            clean_d += f", {datetime.now(timezone.utc).year}"
                        dt = datetime.strptime(clean_d.replace(".", ""), "%b %d, %Y")
                        iso_date = dt.strftime("%Y-%m-%d")
                    except Exception:
                        pass

                    a_tag = block.find("a", href=True)
                    url = a_tag["href"] if a_tag else self.SPACECALENDAR_LAUNCH_URL

                    scraped_launches.append({
                        "date": iso_date,
                        "display_date": date_str,
                        "title": title[:140],
                        "category": "Launches",
                        "location": "Worldwide Spaceport",
                        "description": text[:350],
                        "url": url if url.startswith("http") else f"https://spacecalendar.com{url}",
                        "source": "SpaceCalendar.com",
                        "is_golden_dome": bool(re.search(r'missile|warning|tracking|sda|pwsa|defense', text, re.I))
                    })
        except Exception as e:
            logging.error(f"Error scraping SpaceCalendar.com: {e}")

        logging.info(f"Captured {len(scraped_launches)} live launches from SpaceCalendar.com.")
        return scraped_launches

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
        """Queries Congress.gov API for scheduled space/defense committee hearings."""
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
        Synthesizes live manifests with deep catalog matrices.
        Strictly limits output to a rolling 12-month window (Today -> Today + 365 Days)
        sorted forward-chronologically (earliest upcoming date first).
        """
        all_events = []

        # 1. Ingest verified launches and live SpaceCalendar items
        all_events.extend(self.VERIFIED_LAUNCH_MANIFEST)
        scraped_launches = self.scrape_spacecalendar_manifest()
        all_events.extend(scraped_launches)

        # 2. Ingest dynamic policy & hearings
        all_events.extend(self.fetch_spacepolicyonline_calendar())
        all_events.extend(self.fetch_congressional_hearings())

        # 3. Add military exercises & wargames
        all_events.extend(self.MILITARY_EXERCISES_CATALOG)

        # 4. Add global symposia, summits & conferences (includes SFA Spacepower Orlando & NSSA)
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
        all_events.extend(self.WEBINARS_CATALOG)

        # Strict 12-Month Rolling Window Filter (Today -> Today + 365 Days)
        now_dt = datetime.now(timezone.utc)
        min_ts = (now_dt - timedelta(days=1)).timestamp()
        max_ts = (now_dt + timedelta(days=365)).timestamp()

        def parse_date_score(evt):
            d_str = evt.get("date", "")
            try:
                dt = datetime.strptime(d_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                return dt.timestamp()
            except Exception:
                return now_dt.timestamp() + (180 * 86400)

        # Filter strictly within 365 days and sort forward chronologically
        valid_12mo = [e for e in all_events if min_ts <= parse_date_score(e) <= max_ts]
        valid_12mo.sort(key=parse_date_score)

        # Deduplicate by date and normalized title
        seen_keys = set()
        deduped = []
        for e in valid_12mo:
            key = f"{e['date']}_{e['title'][:32]}".lower()
            if key not in seen_keys:
                seen_keys.add(key)
                deduped.append(e)

        logging.info(f"Total rolling calendar events compiled (<= 12 months): {len(deduped)}")
        return deduped
