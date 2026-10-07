import re

# Negative filters: base facilities, civil works, aviation aircraft & mechanical false positives
EXCLUSION_TERMS = [
    # Non-space "space" phrases
    r"\bconfined\s+space\b", r"\bair\s*space\b", r"\bwork\s*space\b",
    r"\bstorage\s*space\b", r"\boffice\s*space\b", r"\bparking\s*space\b",
    r"\bcyber\s*space\b",
    # Aviation & Aircraft hardware (non-orbital)
    r"\baircraft\b", r"\bairplane\b", r"\baviation\b", r"\bairframe\b",
    r"\bfuselage\b", r"\blanding\s+gear\b", r"\bjet\s+engine\b",
    r"\bturbine\s+blade\b", r"\bhelicopter\b", r"\brotorcraft\b",
    r"\bhydraulic\s+valve\b", r"\bball\s+valve\b", r"\bcheck\s+valve\b",
    r"\bplumbing\s+valve\b", r"\bpneumatic\s+valve\b",
    # Ground & Maritime vehicles
    r"\btank\b", r"\barmored vehicle\b", r"\bhowitzer\b", r"\bmortar\b",
    r"\bsubmarine\b", r"\bdestroyer\b", r"\bfrigate\b", r"\bdrydock\b",
    r"\bfuel oil\b", r"\bbarracks\b", r"\bdormitory\b", r"\bmess hall\b",
    r"\buniform\b", r"\btruck\b", r"\btreadmill\b", r"\bdental\b",
    # Civil works & base maintenance
    r"\basphalt\b", r"\bpaving\b", r"\broad repair\b", r"\broof\b", r"\broofing\b",
    r"\bjanitorial\b", r"\bcustodial\b", r"\brefuse\b", r"\bgarbage\b",
    r"\bmowing\b", r"\blandscaping\b", r"\bgrounds maintenance\b",
    r"\bdemolition\b", r"\bhvac\b", r"\bair conditioning\b", r"\bchiller\b",
    r"\bsewer\b", r"\bsewage\b", r"\bplumbing\b", r"\bpainting\b",
    r"\bconcrete\b", r"\bfence\b", r"\bfencing\b", r"\benvironmental remediation\b"
]

SPACE_CORE_TERMS = [
    r"\bspace\s+force\b", r"\bussf\b", r"\bspace\s+systems\s+command\b", r"\bssc\b",
    r"\bspace\s+operations\s+command\b", r"\bspoc\b", r"\bstarcom\b",
    r"\bspace\s+development\s+agency\b", r"\bsda\b", r"\busspacecom\b",
    r"\bspacewerx\b",
    r"\bnational\s+reconnaissance\s+office\b", r"\bnro\b",
    r"\bsatellite\b", r"\bspacecraft\b", r"\bpayload\b", r"\borbital\b",
    r"\bvleo\b", r"\bleo\b", r"\bmeo\b", r"\bgeo\b", r"\bcislunar\b",
    r"\blaunch\s+vehicle\b", r"\bnssl\b", r"\btactically\s+responsive\s+space\b",
    r"\btacrs\b", r"\bspace\s+domain\s+awareness\b", r"\bssa\b",
    r"\bcommercial\s+augmentation\s+space\s+reserve\b", r"\bcasr\b",
    r"\bcommercial\s+space\s+office\b", r"\bcomso\b",
    r"\bvandenberg\b", r"\bcape\s+canaveral\b", r"\bpatrick\s+sfb\b",
    r"\bschriever\b", r"\bpeterson\s+sfb\b", r"\bbuckley\s+sfb\b", r"\blos\s+angeles\s+sfb\b"
]

GOLDEN_DOME_TERMS = [
    r"\bgolden\s+dome\b",
    r"\bmissile\s+defense\s+agency\b", r"\bmda\b",
    r"\bproliferated\s+warfighter\s+space\s+architecture\b", r"\bpwsa\b",
    r"\btracking\s+layer\b", r"\btransport\s+layer\b",
    r"\btranche\s+[0-4]\b",
    r"\bmissile\s+warning\b", r"\bmissile\s+tracking\b", r"\bmw/mt\b",
    r"\boverhead\s+persistent\s+infrared\b", r"\bopir\b", r"\bnext-gen\s+opir\b",
    r"\bhypersonic\s+and\s+ballistic\s+tracking\s+space\s+sensor\b", r"\bhbtss\b",
    r"\bglide\s+phase\s+interceptor\b", r"\bgpi\b",
    r"\bnext\s+generation\s+interceptor\b", r"\bngi\b",
    r"\bspace-based\s+interceptor\b", r"\bboost-phase\s+intercept\b",
    r"\bc2bmc\b", r"\bcommand\s+and\s+control,\s+battle\s+management\b",
    r"\bresilient\s+missile\s+warning\b", r"\bhomeland\s+defense\s+radar\b"
]

EXCLUSION_REGEX = re.compile("|".join(EXCLUSION_TERMS), re.IGNORECASE)
SPACE_REGEX = re.compile("|".join(SPACE_CORE_TERMS), re.IGNORECASE)
GOLDEN_DOME_REGEX = re.compile("|".join(GOLDEN_DOME_TERMS), re.IGNORECASE)

def evaluate_relevance(text: str) -> dict:
    is_excluded = bool(EXCLUSION_REGEX.search(text))
    has_space = bool(SPACE_REGEX.search(text))
    has_golden_dome = bool(GOLDEN_DOME_REGEX.search(text))

    # Relevant only if matched to space/missile terms and not flagged by negative hardware/civil patterns
    is_relevant = (has_space or has_golden_dome) and not is_excluded

    return {
        "is_relevant": is_relevant,
        "is_space": has_space,
        "is_golden_dome": has_golden_dome,
        "classification": (
            "Golden Dome Priority" if has_golden_dome 
            else ("Space Relevant" if has_space else "Non-Relevant")
        )
    }
