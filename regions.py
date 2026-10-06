from itertools import product
from typing import List, Tuple

REGIONS = {
    # Baltic states
    "Baltics":   ["VNO", "KUN", "RIX", "TLL"],
    # Eastern Europe
    "Eastern":   [ "PRG", "ATH", "OTP", "WAW", "BUD"],

    # Western Europe
    "Western":   ["BRU", "DUS", "MUC","CDG", "FRA", "AMS"],

    # Britain & Ireland
    "Britain":   ["STN", "BHX", "DUB", "GLA", "LHR", "LGW", "MAN"],

    # Nordics 
    "Nordics":   ["OSL", "HEL", "CPH", "ARN"],  # Stockholm, Copenhagen, Oslo, Helsinki
    # Iberia peninsula
    "Iberia":    ["LIS", "OPO", "VLC", "MAD", "BCN"],

    # North America – major U.S. hubs
    "North America": [
        "ORD",  # Chicago O’Hare /m/01_d4
        "DFW",  # Dallas/Fort Worth /m/01_d4
        "JFK",  # New York JFK /m/01_d4
        "SFO",  # San Francisco /m/01_d4
        "ATL",  # Atlanta: /m/013yq
        "LAX",  # Los Angeles /m/030qb3t
    ],
}
 

REGIONS_AIRPORTS= {
    # Baltic states
    "Baltics": [
        "/m/06cn5",   # RIX - Riga
        "/m/07r_p",   # TLL - Tallinn
        #"/m/0171b8",  # KUN - Kaunas
        "/m/07_kq",  # VNO - Vilnius
    ],

    # Eastern Europe
    "Eastern": [
        "/m/081m_",   # WAW - Warsaw
        "/m/095w_",   # BUD - Budapest
        "/m/05ywg",   # PRG - Prague
        "/m/0n2z",    # ATH - Athens
        "/m/096gm",   # OTP - Bucharest Otopeni
    ],

    # Western Europe
    "Western": [
        "/m/05qtj",   # CDG - Paris 
        "/m/02z0j",   # FRA - Frankfurt
        "/m/0k3p",    # AMS - Amsterdam
        "/m/0hf7l",   # DUS - Düsseldorf
        "/m/02h6_6p",  # MUC - Munich
        "/m/0947l",    # MXP - Milan Malpensa
    ],

    # Britain & Ireland
    "Britain": [
        "/m/04jpl",   # LHR - London
        "/m/052bw",   # MAN - Manchester
        "/m/0k33p",   # BHX - Birmingham
        "/m/02cft",   # DUB - Dublin
        "/m/0hyxv",    # GLA - Glasgow
    ],

    # Nordics
    "Nordics": [
        "/m/01lfy",   # CPH - Copenhagen
        "/m/06mxs",   # ARN - Stockholm Arlanda
        "/m/05l64",   # OSL - Oslo
        "/m/03khn",   # HEL - Helsinki
    ],

    # Iberia peninsula
    "Iberia": [
        "/m/056_y",   # MAD - Madrid
        "/m/01f62",   # BCN - Barcelona
        "/m/04llb",   # LIS - Lisbon
        "/m/0pmn7",   # OPO - Porto
        "/m/0h3tv",    # VLC - Valencia
    ],

    # North America – major U.S. hubs
    "North America": [
        "/m/013yq",   # ATL - Atlanta
        "/m/030qb3t", # LAX - Los Angeles
        "/m/01_d4",   # ORD - Chicago O’Hare
        "/m/0f2rq",   # DFW - Dallas/Fort Worth
        "/m/02_286",   # JFK - New York JFK
        "/m/0d6lp",   # SFO - San Francisco
    ],
}






def region_pairs() -> List[Tuple[List[str], List[str]]]:
    """
    Returns a list of all possible pairs of regions.
    """

    REGION_PAIRS = [pair for pair in product(REGIONS.values(), repeat=2)]

    return REGION_PAIRS

def construct_routes():
    ROUTES = region_pairs()
    for pair in ROUTES:
        src, dst = pair
        regions = [[region for region, airports in REGIONS.items() if airports == src][0], 
                   [region for region, airports in REGIONS.items() if airports == dst][0]]
        yield regions, src, dst


