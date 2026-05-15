"""
config.py — All client configuration and field mappings.
Edit this file to add/update clients without touching app logic.
"""

TEAM_EMAILS = [
    "gleb.semeniuk@360dialog.com",
    "alex@360dialog.com",
    "martina@360dialog.com",
]

GSHEET_DEFAULT_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vRQ3KuYGig7yfxogtLL-_fC5faB-JwZ5E5RRnz3t4fJPX6Wdipg9DpgCr60oGwlEVf8s87Zg4Eg5OT5"
    "/pub?gid=229029622&single=true&output=csv"
)

# G-Sheet column names
GSHEET_COLS = {
    "client":      "Client Name",
    "date":        "Sendout Date",
    "jira_link":   "Link to the ticket in JIRA",
    "sendout_id":  "Sendout Task ID",
    "leaflet":     "Link to the client's Leaflets",
    "include_tags":"INCLUDE Tags",
    "exclude_tags":"EXCLUDE Tags",
}

CLIENT_ALIASES: dict[str, list[str]] = {
    "ALDI Italy":   ["ALDI S.R.L.", "ALDI SRL", "ALDI S.r.l."],
    "ALDI Sued":    ["ALDI Sud", "ALDI SÜD", "ALDI Sued"],
    "ALDI Suisse":  ["ALDI Schweiz", "ALDI CH", "Aldi Suisse"],
    "Kaufland WABA": ["Kaufland (für WhatsApp)", "Kaufland (fur WhatsApp)", "Kaufland WhatsApp"],
    "ALDI Portugal": ["ALDI Portugal", "ALDI PT", "ALDI Portugal Regular", "ALDI Portugal Northern", "ALDI PT Regular", "ALDI PT Northern"],
    "Kaufland RCS":  ["Kaufland"],  # Fallback — checked after WABA aliases
    "PENNY Austria":["PENNY.Angebote", "PENNY. Angebote", "Penny AG"],
    "Famila NordWest": ["Famila NW", "Famila NordWest"],
}

JIRA_FIELD_IDS: dict[str, str] = {
    "segment":            "customfield_14287",
    "date":               "customfield_12665",
    "timezone":           "customfield_12671",
    "segment_priority":   "customfield_15977",
    "ai_checked":         "customfield_16417",
    "cta_link":           "customfield_12667",
    "cta_button":         "customfield_12668",
    "footer_text":        "customfield_12670",
    "additional_comments":"customfield_12693",
    "description":        "description",
    "request_type":       "customfield_12664",
}

JIRA_AI_STATUS_FIELD = "customfield_16417"

SYMBOLIC_API_VALUES = frozenset({"@leaflet_url_path", "@leaflet_image_url"})

TYPE_CAROUSEL      = "carousel"
TYPE_BUTTON_CTA    = "button_cta"
TYPE_HEADER_IMAGE  = "header_image"
SOURCE_LEAFLET_URL = "leaflet_url_path"

# ALDI Portugal Regular shop numbers
_ALDI_PT_REGULAR_SHOPS = [
    "0","1","7800-395--125","7630-068--4","7670-253--123","7000-171--167","8200-269--98",
    "8365-011--1","8135-120--7","8950-411--87","8100-069--51","8005-334--14","8005-549--57",
    "8200-559--127","8200-424--6","8200-428--77","8400-395--39","8600-709--13","8100-299--116",
    "8700-224--21","8400-618--155","8500-313--3","8150-132--153","8300-180--101","8800-255--2",
    "8650-421--143","8900-487--113","8200-125--41","2460-920--118","2500-934--8","2450-284--109",
    "2520-267--90","2735-479--52","2735-115--35","2735-521--154","2645-019--110","2610-153--25",
    "2615-277--47","2650-024--64","2645-175--44","1900-134--131","1685-654--46","2050-281--9",
    "2710-694--38","1500-378--146","2695-066--33","1350-321--99","2580-491--26","2605-081--50",
    "2750-834--158","2655-454--29","2670-383--56","1050-999--100","1150-322--122","1750-224--55",
    "1250-172--140","1000-156--151","1600-414--54","2660-038--34","2530-114--117","2640-577--22",
    "2625-214--43","2745-254--28","2745-807--71","2725-466--18","2685-053--149","2690-212--24",
    "2785-575--72","2785-784--111","2710-142--66","2705-866--135","2560-261--20","2665-565--48",
    "2650-432--157","2625-586--97","2600-214--37","7350-091--94","7300-499--32","2080-069--10",
    "2330-027--30","2495-456--63","2490-543--106","2135-079--12","2005-177--62","2350-724--17",
    "2200-233--130","2300-625--144","2890-512--91","7580-254--142","2810-012--36","2814-583--83",
    "2845-358--58","2820-026--49","2835-067--121","2830-095--59","2825-096--161","2840-126--31",
    "2855-574--40","7570-125--139","2860-707--15","2870-484--134","2950-313--60","2955-103--11",
    "2950-037--114","2975-053--103","2970-857--42","7540-236--5","2910-706--23","2910-590--169",
]

_ALDI_PT_NORTHERN_SHOPS = [
    "3830-225--162","4535-014--96","3050-338--145","4520-283--112","3700-241--120","4715-275--84",
    "4835-106--81","4740-574--93","4820-142--136","4805-291--159","4835-472--105","4730-716--156",
    "6200-507--104","6230-346--141","3030-333--61","3040-193--67","3080-012--82","3400-093--128",
    "6300-833--107","6270-481--147","2415-497--74","2410-119--53","2415-449--148","2430-172--45",
    "3100-373--138","4425-112--133","4445-238--85","4600-254--164","4410-226--95","4610-108--163",
    "4460-105--129","4455-212--69","4450-626--79","4465-728--115","4470-312--70","4630-203--124",
    "4580-047--137","4425-653--86","4100-321--152","4435-599--78","4420-356--88","4420-435--92",
    "4440-652--108","4480-666--80","4470-602--132","4400-004--76","4400-026--68","4405-905--65",
    "4430-625--170","4990-011--150","4904-860--119","4910-392--102","4770-260--126","5000-513--73",
    "3500-188--75","4560-532--166","4930-678--165",
]

CLIENT_CONFIGS: dict[str, dict] = {
    "Testing Number": {
        "account_id": 83,
        "timezone_name": "Europe/Berlin",
        "mappings": {},
        "filters": {"Standard": []},
    },
    "ALDI Italy": {
        "account_id": 79,
        "timezone_name": "Europe/Berlin",
        "mappings": {},
        "filters": {
            "Standard":  [{"type": "leaflet_tag", "mode": "include", "offset_days": 1}],
            "Carousel":  [],  # carousel sendouts don't require leaflet_tag filter
        },
    },
    "ALDI Nord": {
        "account_id": 33,
        "timezone_name": "Europe/Berlin",
        "mappings": {},
        "filters": {"Standard": []},
    },
    "ALDI Sued": {
        "account_id": 7,
        "timezone_name": "Europe/Berlin",
        "mappings": {
            "nutrition_042025": {
                "Bio": "bio", "Organic": "bio",
                "Vegetarisch": "vegetarisch", "Vegetarian": "vegetarisch",
                "Vegan": "vegan",
                "Obst/Gemüse": "obtst", "Fruit/Vegetables": "obtst", "Fruits": "obtst",
                "Keine besondere Präferenz": "alles", "No preference": "alles",
            },
            "aldithemen_042025": {
                "Haushalt": "haushalt", "Household": "haushalt", "Home": "haushalt",
                "Kleidung": "kleidung", "Clothing": "kleidung", "Fashion": "kleidung",
                "Wohnen": "wohnen", "Living": "wohnen", "Furniture": "wohnen",
                "Outdoor": "outdoor",
                "Sport": "sport", "Sports": "sport",
                "Kochen": "kochen", "Küche": "kochen", "Kuche": "kochen",
                "Cooking": "kochen", "Kitchen": "kochen",
                "Garten": "garten", "Garden": "garten", "Gardening": "garten",
                "Grillen": "grillen", "Grilling": "grillen", "BBQ": "grillen", "Grill": "grillen",
                "Elektronik": "elektronik", "Electronics": "elektronik", "Technology": "elektronik",
                "Heimwerken": "heimwerken", "DIY": "heimwerken", "Home improvement": "heimwerken",
            },
            "weiterethemen_042025": {
                "Familien": "familien", "Family": "familien", "Families": "familien",
                "Frauen": "frauen", "Women": "frauen", "Female": "frauen",
                "Männer": "manner", "Maenner": "manner", "Men": "manner", "Male": "manner",
                # WhatsApp Chat Prospekt ticket name variants
                "Living": "wohnen",
                "Keins davon": "keins", "None": "keins",
            },
        },
        "filters": {"Standard": [{"name": "leaflet_accepted", "value": "true"}]},
    },
    "ALDI Suisse": {
        "account_id": 36,
        "timezone_name": "Europe/Berlin",
        "mappings": {},
        "requires_jira": False,  # recurring automated sendouts (DE/FR/IT locales)
        "filters": {
            "DE Sendout": [{"type": "locale", "mode": "include", "value": "de"}, {"type": "leaflet_tag", "locale": "de", "offset_days": 1}],
            "FR Sendout": [{"type": "locale", "mode": "include", "value": "fr"}, {"type": "leaflet_tag", "locale": "fr", "offset_days": 1}],
            "IT Sendout": [{"type": "locale", "mode": "include", "value": "it"}, {"type": "leaflet_tag", "locale": "it", "offset_days": 1}],
            # Test sendouts use wids filter — no strict config filter required
            "DE Test Sendout": [],
            "FR Test Sendout": [],
            "IT Test Sendout": [],
        },
    },
    "Nahkauf": {
        "account_id": 41,
        "timezone_name": "Europe/Berlin",
        "mappings": {},
        "filters": {"Standard": [{"type": "leaflet_tag", "mode": "include", "offset_days": 1}]},
    },
    "REWE": {
        "account_id": 5,
        "timezone_name": "Europe/Berlin",
        "mappings": {},
        "filters": {"Standard": [{"type": "tag", "name": "declined_new_terms", "mode": "exclude", "value": "true"}]},
    },
    "Toom": {
        "account_id": 9,
        "timezone_name": "Europe/Berlin",
        "mappings": {},
        "filters": {"Standard": [
            {"type": "leaflet_tag", "mode": "include", "offset_days": 1},
        ]},
    },
    "Netto":    {"account_id": 10, "timezone_name": "Europe/Berlin", "mappings": {}, "filters": {"Standard": []}},
    "Hieber":             {"account_id": 15,  "timezone_name": "Europe/Berlin", "mappings": {}, "filters": {"Standard": []}},
    "Hofer": {
        "account_id": 20,
        "timezone_name": "Europe/Berlin",
        "mappings": {},
        "filters": {"Standard": [
            {"type": "tag", "name": "leaflet_accepted", "mode": "include", "value": "true"},
            {"type": "leaflet_tag", "mode": "include", "offset_days": 1},
        ]},
    },
    "PENNY Austria": {"account_id": 21, "timezone_name": "Europe/Berlin", "mappings": {}, "filters": {"Standard": []}},
    "Sonderpreis Baumarkt": {"account_id": 26, "timezone_name": "Europe/Berlin", "mappings": {}, "requires_jira": False, "filters": {"Standard": []}},
    "Combi":              {"account_id": 29,  "timezone_name": "Europe/Berlin", "mappings": {}, "filters": {"Standard": []}},
    "Famila NordWest":    {"account_id": 30,  "timezone_name": "Europe/Berlin", "mappings": {}, "filters": {"Standard": []}},
    "Pflanzen-Kölle": {"account_id": 40, "timezone_name": "Europe/Berlin", "mappings": {}, "filters": {"Standard": []}},
    "Penny IT":       {"account_id": 39,  "timezone_name": "Europe/Berlin", "mappings": {}, "filters": {"Standard": []}},
    "Penny RO":       {"account_id": 45, "timezone_name": "Europe/Berlin", "mappings": {}, "filters": {"Standard": []}},
    "TUI Belgium": {
        "account_id": 53,
        "timezone_name": "Europe/Berlin",
        "mappings": {},
        "filters": {
            "Third Party FR": [{"type": "tag", "name": "selected_shop_type", "mode": "include", "value": "third_party"}, {"type": "locale", "mode": "include", "value": "fr"}, {"type": "leaflet_tag", "locale": "fr", "mode": "include"}],
            "Regular FR":     [{"type": "tag", "name": "selected_shop_type", "mode": "exclude", "value": "third_party"}, {"type": "locale", "mode": "include", "value": "fr"}, {"type": "leaflet_tag", "locale": "fr", "mode": "include"}],
            "Third Party NL": [{"type": "tag", "name": "selected_shop_type", "mode": "include", "value": "third_party"}, {"type": "locale", "mode": "include", "value": "nl"}, {"type": "leaflet_tag", "locale": "nl", "mode": "include"}],
            "Regular NL":     [{"type": "tag", "name": "selected_shop_type", "mode": "exclude", "value": "third_party"}, {"type": "locale", "mode": "include", "value": "nl"}, {"type": "leaflet_tag", "locale": "nl", "mode": "include"}],
        },
    },
    "Migros": {
        "account_id": 55,
        "timezone_name": "Europe/Berlin",
        "mappings": {},
        "requires_jira": False,  # recurring automated sendout
        "filters": {
            "DE Sendout": [{"type": "locale", "mode": "include", "value": "de"}, {"type": "leaflet_tag", "locale": "de", "mode": "include", "offset_days": 1}],
            "FR Sendout": [{"type": "locale", "mode": "include", "value": "fr"}, {"type": "leaflet_tag", "locale": "fr", "mode": "include", "offset_days": 1}],
            "IT Sendout": [{"type": "locale", "mode": "include", "value": "it"}, {"type": "leaflet_tag", "locale": "it", "mode": "include", "offset_days": 1}],
        },
    },
    "B1": {
        "account_id": 58,
        "timezone_name": "Europe/Berlin",
        "mappings": {},
        "requires_jira": False,  # recurring automated sendout
        "filters": {"Standard": [{"type": "shop_number", "mode": "exclude", "values": ["13573732", "13573471", "13573638", "13573405"]}]},
    },
    "Wreesmann": {
        "account_id": 59,
        "timezone_name": "Europe/Berlin",
        "mappings": {},
        "requires_jira": False,  # recurring automated sendout
        "filters": {
            "Regular Sendout":         [{"type": "shop_number", "mode": "exclude", "values": ["0"]}],
            "Sendout Postal code 0":   [{"type": "shop_number", "mode": "include", "values": ["0"]}],
        },
    },
    "Aldi LUX": {"account_id": 66, "timezone_name": "Europe/Berlin", "mappings": {}, "filters": {"Standard": []}},
    "Wasgau":   {"account_id": 91, "timezone_name": "Europe/Berlin", "mappings": {}, "filters": {"Standard": []}},
    "ALDI Portugal": {
        "account_id": 95,
        "timezone_name": "Europe/Lisbon",
        "mappings": {},
        "filters": {
            # Segment is detected from the JIRA segment field at validation time
            "Regular":  [
                {"type": "shop_number", "mode": "include", "values": _ALDI_PT_REGULAR_SHOPS},
                {"type": "leaflet_tag", "mode": "include", "offset_days": 1},
            ],
            "Northern": [
                # Northern segment: only shop numbers required, no leaflet_tag filter
                {"type": "shop_number", "mode": "include", "values": _ALDI_PT_NORTHERN_SHOPS},
            ],
            "Standard": [
                {"type": "leaflet_tag", "mode": "include", "offset_days": 1},
            ],
        },
    },
    "TUI Fly": {
        "account_id": 97,
        "timezone_name": "Europe/Berlin",
        "mappings": {},
        "filters": {
            "NL Sendout":  [{"type": "locale", "mode": "include", "value": "nl"}],
            "FR Sendout":  [{"type": "locale", "mode": "include", "value": "fr"}],
            "Eng Sendout": [{"type": "locale", "mode": "include", "value": "en"}],
        },
    },
    "Bauhaus": {"account_id": 148, "timezone_name": "Europe/Berlin", "mappings": {}, "filters": {"Standard": []}},
    "Penny Germany": {
        "account_id": 28,
        "timezone_name": "Europe/Berlin",
        "mappings": {},
        "filters": {"Standard": [{"type": "leaflet_tag", "mode": "include", "offset_days": 3}]},
    },
    "Kaufland WABA": {
        "account_id": 190,
        "timezone_name": "Europe/Berlin",
        "mappings": {},
        "filters": {
            "Standard": [{"type": "tag", "name": "leaflet_type", "mode": "include", "value": "regular"}],
            "Sunday": [
                {"type": "tag",        "name": "leaflet_type", "mode": "include", "value": "regular"},
                {"type": "leaflet_tag", "mode": "include", "offset_days": 4},
                {"type": "leaflet_tag", "mode": "include", "offset_days": 1},
                {"type": "tag",        "name": "leaflet_type", "mode": "include", "value": "special"},
            ],
        },
    },
    "Kaufland RCS": {
        "account_id": 162,
        "timezone_name": "Europe/Berlin",
        "mappings": {},
        "filters": {
            "Sunday":    [
                {"type": "tag",        "name": "leaflet_type", "mode": "include", "value": "regular"},
                {"type": "leaflet_tag", "mode": "include", "offset_days": 4},
                {"type": "leaflet_tag", "mode": "include", "offset_days": 1},
                {"type": "tag",        "name": "leaflet_type", "mode": "include", "value": "special"},
            ],
            "Wednesday": [
                {"type": "tag",        "name": "leaflet_type", "mode": "include", "value": "regular"},
                {"type": "leaflet_tag", "mode": "include", "offset_days": 1},
            ],
        },
        # Wednesday RCS: Card 1 = static leaflet card ("Knüller-Angebote")
        # Card 2 = promotional text from JIRA ticket (ticket-specific)
        "wednesday_rcs_card1": {
            "title": "Knüller-Angebote",
            "body_prefix": (
                "Stöbere durch unseren aktuellen Prospekt für deine Filiale in "
                "{{shop_city}} {{shop_address}} mit den Angeboten vom "
                "{{leaflet_start_date}} - {{leaflet_end_date}}"
            ),
            "button": "Zum Prospekt",
        },
        # Static RCS card texts for Sunday sendout (no JIRA description needed)
        "sunday_rcs_cards": [
            {
                "title": "Wochenstart-Angebote",
                "body": (
                    "Hier findest du unseren aktuellen Prospekt für deine Filiale in "
                    "{{shop_city}} {{shop_address}} mit den Angeboten vom "
                    "{{leaflet_start_date}} - {{leaflet_end_date}} ⬇️\n\n"
                    "Viele Grüße  \nKaufland - Hier bin ich richtig.\n\n"
                    'Um das Abo zu beenden, sende uns die Nachricht "STOP"'
                ),
                "button": "Zum Prospekt",
                "leaflet_filter": "leaflet_type=special, offset_days=1",
            },
            {
                "title": "Knüller-Angebote",
                "body": (
                    "Hier findest du unseren aktuellen Prospekt für deine Filiale in "
                    "{{shop_city}} {{shop_address}} mit den Angeboten vom "
                    "{{leaflet_start_date}} - {{leaflet_end_date}} ⬇️\n\n"
                    "Viele Grüße  \nKaufland - Hier bin ich richtig.\n\n"
                    'Um das Abo zu beenden, sende uns die Nachricht "STOP"'
                ),
                "button": "Zum Prospekt",
                "leaflet_filter": "leaflet_type=regular (main filter)",
            },
        ],
    },
}
