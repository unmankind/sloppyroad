"""Fantasy character name pools organized by phonetic style.

Names are categorized by how they SOUND, not by ethnicity or cultural origin.
Each phonetic style has 40 names per gender category (female, male, nonbinary).
Surnames are organized into 7 style pools with 30 entries each.

Usage:
    from aiwebnovel.story.name_pools import FIRST_NAMES, SURNAMES
    import random

    style = random.choice(list(FIRST_NAMES.keys()))
    gender = "female"  # or "male", "nonbinary"
    name = random.choice(FIRST_NAMES[style][gender])
    surname_style = random.choice(list(SURNAMES.keys()))
    surname = random.choice(SURNAMES[surname_style])
"""

from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════════════════
# FIRST NAMES — 9 phonetic styles x 3 genders x 40 names = 1,080 unique names
# ═══════════════════════════════════════════════════════════════════════════════

FIRST_NAMES = {
    # ── FLOWING: vowel-heavy, melodic, soft consonants ──────────────────────
    "flowing": {
        "female": [
            "Aisara", "Olienna", "Iseyo", "Yuenai", "Avoria",
            "Ielune", "Anuessa", "Omalei", "Elivaine", "Uolani",
            "Aiyesa", "Iomara", "Eoleia", "Ailuvie", "Ourana",
            "Iovella", "Ameleia", "Yuesola", "Eilonai", "Umaira",
            "Ovelise", "Iavenne", "Aiselle", "Eumaia", "Uliane",
            "Oluvani", "Iamurei", "Auvenya", "Eolienne", "Yualei",
            "Iovisse", "Aisuvae", "Oleniya", "Iamouri", "Uelessa",
            "Auvalia", "Yoimera", "Eovaine", "Uleiana", "Omaive",
        ],
        "male": [
            "Iolaren", "Auestin", "Oremei", "Iyuven", "Eliovar",
            "Uenaro", "Aiolus", "Oemiran", "Yualen", "Ilevari",
            "Oranei", "Auvelen", "Euloran", "Iavomir", "Umeyai",
            "Olievane", "Auesomar", "Yeiluen", "Iomavel", "Euronai",
            "Aivolen", "Uoleivar", "Oeluvin", "Iaunero", "Aliovane",
            "Oumelan", "Eivonar", "Yualimen", "Iorevai", "Aumoven",
            "Olianev", "Ialuven", "Euomari", "Uevalon", "Ayelimu",
            "Oivalen", "Iaumero", "Eoluvain", "Yovienai", "Ulemaro",
        ],
        "nonbinary": [
            "Aolei", "Iouvane", "Eumali", "Yuavei", "Olviane",
            "Iaulem", "Aeyovi", "Ouverai", "Eolimae", "Ulmeia",
            "Yiovenal", "Aouveli", "Iumeya", "Eliova", "Uavenoi",
            "Oivalem", "Auelovi", "Ioyema", "Euvanoi", "Yoluven",
            "Oimelua", "Aeluvia", "Ioumave", "Ualevoi", "Eyomali",
            "Ovienua", "Iauvelm", "Aelomei", "Yuovane", "Uleiova",
            "Oyelumi", "Iovaesu", "Aulmeia", "Eiuvano", "Uovelia",
            "Yalimoe", "Ioavelm", "Eoulyma", "Aumiove", "Olivuen",
        ],
    },
    # ── CLIPPED: consonant-heavy, 1-2 syllables, punchy ────────────────────
    "clipped": {
        "female": [
            "Brek", "Triss", "Jeth", "Korb", "Sniv",
            "Dran", "Plisk", "Grett", "Fenn", "Valt",
            "Kriv", "Tump", "Skell", "Blint", "Neft",
            "Crav", "Dolsk", "Pirn", "Jask", "Wenk",
            "Rilm", "Stev", "Grint", "Volp", "Tumm",
            "Skiv", "Blenn", "Dreft", "Kass", "Mirk",
            "Prell", "Jorv", "Flink", "Trev", "Gwinn",
            "Hulk", "Spritt", "Nolm", "Drenn", "Kelv",
        ],
        "male": [
            "Kolt", "Brask", "Dort", "Gresh", "Storn",
            "Preck", "Vlint", "Jurm", "Tolk", "Krebb",
            "Felg", "Dworn", "Blisk", "Scarn", "Heft",
            "Golm", "Struk", "Drimm", "Pelk", "Bront",
            "Quarv", "Vekk", "Wulm", "Jarsk", "Cleft",
            "Sporn", "Trogg", "Nilm", "Freck", "Gulb",
            "Skrent", "Bolk", "Drust", "Kelm", "Writh",
            "Prank", "Gorv", "Stebb", "Flurn", "Mekt",
        ],
        "nonbinary": [
            "Driv", "Kelp", "Brunt", "Snell", "Grift",
            "Vork", "Plimm", "Tusk", "Frenk", "Jolt",
            "Skrim", "Blort", "Welk", "Crist", "Dunm",
            "Polt", "Strim", "Grelk", "Nift", "Brev",
            "Torsk", "Flenn", "Kurm", "Spelt", "Drelv",
            "Grimm", "Velk", "Plonk", "Jerst", "Twill",
            "Skenk", "Brift", "Nulm", "Creft", "Gulp",
            "Dront", "Felm", "Prisk", "Klenn", "Worv",
        ],
    },
    # ── LYRICAL: 3+ syllables, musical rhythm ──────────────────────────────
    "lyrical": {
        "female": [
            "Seraphina", "Thalassien", "Veranelle", "Calimesta", "Orianthea",
            "Mellisande", "Luminara", "Thessalyne", "Valerienne", "Auristela",
            "Perindala", "Saviolette", "Merindol", "Celestara", "Andivelle",
            "Rosalinde", "Evanthra", "Cassimere", "Pellantine", "Julevianne",
            "Istavella", "Marcelline", "Glorivaine", "Taminelle", "Dorianthe",
            "Oribelle", "Solantine", "Previenne", "Kallistera", "Beruniece",
            "Violandre", "Festienne", "Nimuelle", "Adravaine", "Corellise",
            "Emelinthe", "Gavriella", "Talindrel", "Pirouesse", "Laurivane",
        ],
        "male": [
            "Alariston", "Sebastaire", "Thelonius", "Valenthor", "Peregalan",
            "Meridicus", "Cassivane", "Dorenthal", "Oriclavus", "Amalrion",
            "Belisante", "Corvallen", "Justivane", "Gallianthor", "Phaleron",
            "Torivalde", "Illustran", "Severigne", "Markavell", "Eldivaro",
            "Noctavien", "Glorimand", "Radiverne", "Caelestrom", "Berenvald",
            "Fenristal", "Augustavel", "Trevallion", "Solindare", "Luminarch",
            "Koriander", "Veranthos", "Doriveaux", "Paladine", "Galanthir",
            "Brisivane", "Octaverne", "Mellithor", "Harventhal", "Isildane",
        ],
        "nonbinary": [
            "Amalinde", "Corivayne", "Peliverne", "Theliandre", "Solariste",
            "Melivanthe", "Gallimere", "Orivault", "Destivane", "Juliandre",
            "Korellaine", "Tristivale", "Velinaire", "Castellane", "Aurelinde",
            "Brisantine", "Norivelle", "Peristane", "Selivarre", "Ithavaine",
            "Luminesse", "Dorivaline", "Tremontale", "Estrielle", "Fallaverne",
            "Gallisende", "Ambroiselle", "Kerivallon", "Previndare", "Rossivaine",
            "Tallaverne", "Merivault", "Oristelle", "Celestane", "Illustrine",
            "Vivandiere", "Belloriste", "Corvelaine", "Thalistane", "Andiville",
        ],
    },
    # ── EARTHY: naturalistic, grounded, could be words ─────────────────────
    "earthy": {
        "female": [
            "Moss", "Bramble", "Fallow", "Wren", "Sorrel",
            "Clover", "Hazel", "Tansy", "Meadow", "Larkspur",
            "Rue", "Yarrow", "Briar", "Senna", "Linnea",
            "Heather", "Bracken", "Primrose", "Aster", "Fern",
            "Marigold", "Nettle", "Alder", "Daphne", "Flax",
            "Ivy", "Laurel", "Myrtle", "Sable", "Coral",
            "Thistledown", "Rosehip", "Brindle", "Sedge", "Plover",
            "Barley", "Clove", "Hyssop", "Juniper", "Elm",
        ],
        "male": [
            "Ridge", "Flint", "Cairn", "Stone", "Thorn",
            "Birch", "Reed", "Clay", "Colt", "Garner",
            "Pike", "Basalt", "Forge", "Quarry", "Tiller",
            "Dale", "Brock", "Fennel", "Heath", "Loam",
            "Holt", "Grove", "Marsh", "Glen", "Coppice",
            "Barrow", "Field", "Roan", "Talon", "Rust",
            "Thatch", "Boulder", "Millstone", "Furrow", "Oakley",
            "Gale", "Peat", "Drift", "Cobble", "Summit",
        ],
        "nonbinary": [
            "Lichen", "Burrow", "Loess", "Woad", "Sparrow",
            "Thicket", "Slate", "Quill", "Arbor", "Pebble",
            "Wilder", "Fox", "Raven", "Finch", "Storm",
            "Frost", "Berry", "Dawn", "Dusk", "River",
            "Rain", "Sky", "Brook", "Lark", "Cricket",
            "Hollow", "Cliff", "Mallow", "Twig", "Osprey",
            "Oriole", "Starling", "Flicker", "Shale", "Pondweed",
            "Canopy", "Cinder", "Bramblewood", "Harrow", "Thistle",
        ],
    },
    # ── SHARP: angular, unusual phonemes, distinctive ──────────────────────
    "sharp": {
        "female": [
            "Zivka", "Quilva", "Ixabel", "Tzenka", "Vriska",
            "Kyzhara", "Fjoldi", "Nixelle", "Zhukova", "Quenthi",
            "Kjevla", "Obsyda", "Vyxelle", "Tzarine", "Pjotra",
            "Quirelle", "Zventa", "Djinna", "Fjellka", "Xandelle",
            "Kvilla", "Zypher", "Wrixel", "Qlara", "Jvanna",
            "Tzkala", "Prixma", "Zhelvie", "Vkarla", "Fnessa",
            "Ixava", "Qilith", "Djemra", "Tzivelle", "Kvasha",
            "Zhelda", "Vrenna", "Wxyla", "Pjekka", "Njilva",
        ],
        "male": [
            "Nkosi", "Tzevran", "Quillan", "Vjarek", "Dzhovan",
            "Fjordek", "Xanthrik", "Zkavel", "Qvoryn", "Pjavel",
            "Kvaren", "Jxander", "Tzimran", "Nixovar", "Vjektar",
            "Zhelkov", "Djarek", "Fjolvar", "Quixan", "Wvreth",
            "Kzander", "Tzhovan", "Pjovrek", "Nqvari", "Ixavel",
            "Zkovan", "Vjander", "Qvareth", "Dzhavel", "Fjovren",
            "Xzavien", "Tzeklov", "Kvander", "Pjilvar", "Njovrek",
            "Zhavren", "Wquilar", "Vjelder", "Dzkoven", "Qzirath",
        ],
        "nonbinary": [
            "Tzivek", "Qvell", "Dzheri", "Kjalve", "Fjoren",
            "Zvikov", "Xanvel", "Njeli", "Pjovek", "Wqava",
            "Vzkeli", "Ixovel", "Tzavel", "Quilven", "Dzhiva",
            "Kveli", "Fjovek", "Zharen", "Nxovel", "Pjivel",
            "Qzaven", "Wjilve", "Tzkoven", "Vjoreli", "Dxavel",
            "Kzhiven", "Fjilve", "Ixorek", "Zvarel", "Njovek",
            "Pqavel", "Tzhiven", "Qvilrek", "Dzjore", "Wzkeli",
            "Kjoven", "Vqzari", "Xjilven", "Fjoveli", "Zhkoven",
        ],
    },
    # ── GUTTURAL: harsh, back-of-throat, forceful ──────────────────────────
    "guttural": {
        "female": [
            "Grokhara", "Drukha", "Barruka", "Gholden", "Kragga",
            "Vorrash", "Thorga", "Drukkha", "Borghild", "Grunga",
            "Khorva", "Dragha", "Vulgara", "Gorveth", "Brakkha",
            "Torgda", "Rughild", "Skorghel", "Duurga", "Grakken",
            "Khurrha", "Borga", "Drothka", "Vurghil", "Grolda",
            "Tharruk", "Kruggha", "Dorghild", "Vrakkha", "Skurra",
            "Ghorvel", "Bargha", "Throkkel", "Druugha", "Korghild",
            "Vrothga", "Buurkha", "Grakhel", "Durgha", "Thorrga",
        ],
        "male": [
            "Grokhaan", "Drukh", "Barruk", "Gholvar", "Kraggor",
            "Vorrath", "Thorgrim", "Drukkhar", "Borgvald", "Grungir",
            "Khorvak", "Dragar", "Vulgarr", "Gorvald", "Brakkhor",
            "Torgrath", "Rughard", "Skorghul", "Duurgrim", "Grakkoth",
            "Khurroth", "Borgrath", "Drothgar", "Vurghald", "Groldak",
            "Tharrukh", "Krugghar", "Dorghast", "Vrakkhan", "Skurrath",
            "Ghorvald", "Barghor", "Throkkul", "Druugar", "Korgrath",
            "Vrothgar", "Buurkhan", "Grakhol", "Durghast", "Thorrgar",
        ],
        "nonbinary": [
            "Grokhul", "Drukhev", "Barrukh", "Gholven", "Kraggel",
            "Vorrikh", "Thorgvel", "Drukkhen", "Borgvel", "Grungev",
            "Khorvel", "Draghul", "Vulgrev", "Gorvel", "Brakkhev",
            "Torgvel", "Rughev", "Skorghev", "Duurghev", "Grakkhel",
            "Khurrvel", "Borghev", "Drothvel", "Vurghev", "Groldev",
            "Tharruv", "Kruggvel", "Dorghev", "Vrakkhev", "Skurrvel",
            "Ghorvek", "Barghev", "Throkkev", "Druughev", "Korgrevel",
            "Vrothvel", "Buurkhev", "Grakhev", "Durghev", "Thorrgel",
        ],
    },
    # ── SIBILANT: s/sh/z/th-heavy, whispery ───────────────────────────────
    "sibilant": {
        "female": [
            "Sashiel", "Zhessra", "Thessika", "Sisalve", "Shezara",
            "Zephessa", "Synthara", "Thissela", "Shalisse", "Zashira",
            "Shessiva", "Thassia", "Sizelle", "Zhissel", "Sessalyne",
            "Shanthis", "Zeshara", "Thissora", "Syzelle", "Shezivra",
            "Zhassiel", "Thessiva", "Sashelle", "Shizara", "Zyssela",
            "Theshira", "Sizhelle", "Shessira", "Zashiel", "Thessila",
            "Syzanthis", "Zhessila", "Shathira", "Szessiva", "Thasshiel",
            "Zishelle", "Shezissa", "Thessura", "Sizhara", "Zhassiela",
        ],
        "male": [
            "Thessik", "Shasvar", "Zhessok", "Sizavel", "Shezran",
            "Zephissar", "Synthavel", "Thissoran", "Shalissek", "Zashirok",
            "Shessival", "Thassiel", "Sizavorn", "Zhissolen", "Sessavran",
            "Shanthros", "Zeshavorn", "Thessovan", "Syzavek", "Shezivran",
            "Zhassivek", "Thessivorn", "Sashevran", "Shizavorn", "Zysselan",
            "Theshirok", "Sizhavorn", "Shessirak", "Zashivorn", "Thessilak",
            "Syzanthrok", "Zhessilak", "Shathirok", "Szessivorn", "Thasshivek",
            "Zishavorn", "Shezissak", "Thessuran", "Sizhavek", "Zhassivor",
        ],
        "nonbinary": [
            "Sashev", "Zhessil", "Thessiv", "Sizael", "Shezren",
            "Zephisse", "Syntheve", "Thissol", "Shalisev", "Zashive",
            "Shessiv", "Thassiv", "Sizoven", "Zhissol", "Sessave",
            "Shanthev", "Zeshave", "Thissev", "Syzavel", "Sheziv",
            "Zhassiv", "Thessive", "Sashenve", "Shizavel", "Zyssel",
            "Theshive", "Sizhavel", "Shessive", "Zashivel", "Thessile",
            "Syzanthe", "Zhessile", "Shathive", "Szessive", "Thasshive",
            "Zishavel", "Shezisse", "Thessuve", "Sizhave", "Zhassive",
        ],
    },
    # ── RHYTHMIC: repeated syllables or patterns, percussive ───────────────
    "rhythmic": {
        "female": [
            "Tamatu", "Kokora", "Babajide", "Nenelle", "Lalinde",
            "Mamassa", "Didivelle", "Totomei", "Papashel", "Kakarina",
            "Ninifel", "Rororei", "Sasanne", "Tutuvelle", "Jajinda",
            "Vivashi", "Bababelle", "Mimimei", "Dududara", "Fefenne",
            "Gagalei", "Lililei", "Tatashel", "Kokobelle", "Nunumei",
            "Rerenne", "Ababelle", "Sisivelle", "Totorei", "Pupujinde",
            "Kekeshel", "Wawanne", "Didirei", "Momomei", "Falafelle",
            "Jujubelle", "Zazazei", "Hahashel", "Ninivelle", "Rurumei",
        ],
        "male": [
            "Babajidek", "Kokoran", "Tamaturo", "Nenello", "Lalindor",
            "Mamassek", "Didivorn", "Totomero", "Papashek", "Kakaron",
            "Niniforn", "Rororan", "Sasandor", "Tutuvorn", "Jajindor",
            "Vivashek", "Bababorn", "Mimimorn", "Dududorn", "Fefennor",
            "Gagalorn", "Lilliorn", "Tatashok", "Kokobor", "Nunumor",
            "Rerennor", "Ababorn", "Sisivorn", "Totorion", "Pupujorn",
            "Kekeshorn", "Wawannor", "Didirion", "Momornor", "Falaforn",
            "Jujubor", "Zazazorn", "Hahashok", "Ninivorn", "Rurumor",
        ],
        "nonbinary": [
            "Babaji", "Kokori", "Tamati", "Neneli", "Lalindi",
            "Mamassi", "Didivei", "Totomae", "Papashi", "Kakari",
            "Ninifi", "Rorori", "Sasandi", "Tutuvei", "Jajindi",
            "Vivashae", "Bababei", "Mimimae", "Dududei", "Fefenni",
            "Gagalae", "Lililae", "Tatashi", "Kokobi", "Nunumi",
            "Rerenni", "Ababei", "Sisivei", "Totori", "Pupuji",
            "Kekeshi", "Wawanni", "Didirae", "Momorei", "Falafei",
            "Jujubei", "Zazazi", "Hahashi", "Ninivei", "Rurumi",
        ],
    },
    # ── ANCIENT: archaic-sounding, weathered, Old English/Latin/Sanskrit ───
    "ancient": {
        "female": [
            "Aldhelma", "Suthwyn", "Verimunda", "Brunhyld", "Aethelfled",
            "Cwenthryth", "Hrothvilde", "Ealdgyth", "Gundrada", "Hildegyth",
            "Leofwynn", "Osthryth", "Wulfhild", "Cynethrith", "Aelgifu",
            "Sigefled", "Beornwynn", "Frithugyth", "Godgifu", "Aethelburga",
            "Tatfrith", "Wendreda", "Heregyth", "Mildritha", "Eorcengota",
            "Saethryth", "Withburga", "Aelfthrith", "Raedwynn", "Torhtgyth",
            "Praecilia", "Vedantika", "Sulochana", "Bhagirathi", "Chandravati",
            "Jahnvika", "Dharitri", "Pushpavati", "Mriganka", "Taravali",
        ],
        "male": [
            "Aldhelm", "Verimund", "Suthric", "Beornwulf", "Ealdred",
            "Cynewulf", "Hrothgar", "Wulfstan", "Leofric", "Godwine",
            "Aethelstan", "Sigeric", "Osmund", "Aelfric", "Gundovald",
            "Theoberic", "Childeric", "Merovald", "Fritigern", "Radagast",
            "Grimwald", "Hildebrand", "Chlodovech", "Eorconwald", "Cenwalh",
            "Tatfridh", "Raedwald", "Caedmon", "Aethelbald", "Wiglaf",
            "Dharmasena", "Vikramdev", "Suryavarn", "Chandragupt", "Arjunvald",
            "Bhagavesh", "Jahnvesh", "Mrigandhar", "Pushpavarn", "Taravald",
        ],
        "nonbinary": [
            "Aelfhere", "Cynebald", "Wulfhere", "Hrothvel", "Ealdhere",
            "Suthhere", "Leofhere", "Godhere", "Sighere", "Oshere",
            "Beornhere", "Aethelmere", "Gundhere", "Theohere", "Childehere",
            "Merohere", "Fritihere", "Grimhere", "Hildehere", "Raedhere",
            "Tathere", "Cenhere", "Caedhere", "Wiglafhere", "Eorcenhere",
            "Dharmakel", "Vikramvel", "Suryakel", "Chandrakel", "Arjunkel",
            "Bhagavel", "Jahnvel", "Mrigavel", "Pushpavel", "Tarakel",
            "Vedankel", "Sulocavel", "Jagatvel", "Praecavel", "Withavel",
        ],
    },
}

# ═══════════════════════════════════════════════════════════════════════════════
# SURNAMES — 7 style pools x 30 surnames = 210 unique surnames
# ═══════════════════════════════════════════════════════════════════════════════

SURNAMES = {
    # ── PATRONYMIC: derived from an ancestor's name ────────────────────────
    "patronymic": [
        "Alderson", "Thorsdottir", "Wulfgard", "Cynemark", "Beornhild",
        "Godwinsen", "Leofricson", "Hildevard", "Sigerson", "Osricsdottir",
        "Ealdredsen", "Hrothvaldson", "Suthricsdottir", "Guntherson", "Merovaldsen",
        "Aelfricson", "Grimsward", "Tatfridhson", "Raedwaldsen", "Vikramsen",
        "Dharmawardson", "Childericsen", "Brunhyldsdottir", "Fritisward", "Caedmonsen",
        "Theobericsdottir", "Cenricson", "Verimundsen", "Aethelwardson", "Wulfhelmdottir",
    ],
    # ── PLACE-BASED: derived from geography or landmarks ───────────────────
    "place_based": [
        "Ashenmere", "Thornwick", "Coldhollow", "Greymarch", "Stonebight",
        "Duskwater", "Ironmoor", "Fellgate", "Ravenmire", "Deepwell",
        "Highcairn", "Mistfell", "Blacktarn", "Silverburn", "Windreach",
        "Darkholme", "Starfall", "Gloomhaven", "Pineshade", "Cragmount",
        "Saltmarsh", "Frostholm", "Ashvale", "Copperhill", "Nightshore",
        "Mosswick", "Stormfirth", "Willowfen", "Dreadmoor", "Hearthwick",
    ],
    # ── OCCUPATION: derived from trades, roles, or skills ──────────────────
    "occupation": [
        "Forgewright", "Tidewalker", "Spelldust", "Lorekeeper", "Wardcarver",
        "Glyphbinder", "Oathsworn", "Stonewright", "Hearthkeeper", "Runecatcher",
        "Threadweaver", "Vaultkeeper", "Farwalker", "Dawnwatcher", "Ironbender",
        "Chainwright", "Ashspeaker", "Pathfinder", "Wavebreaker", "Grimscribe",
        "Flamecaster", "Nightwalker", "Bonecaller", "Rootbinder", "Windreader",
        "Stormsinger", "Bladewright", "Deepcaller", "Shellbreaker", "Dustwalker",
    ],
    # ── SINGLE-WORD: evocative standalone words ────────────────────────────
    "single_word": [
        "Silence", "Kindling", "Dread", "Vestige", "Sunder",
        "Ruin", "Tempest", "Requiem", "Sorrow", "Cairn",
        "Hollow", "Wither", "Covenant", "Remnant", "Gloam",
        "Lament", "Vigil", "Perdition", "Blight", "Revenant",
        "Crucible", "Barren", "Fulcrum", "Oblivion", "Dirge",
        "Harbinger", "Schism", "Riven", "Gallows", "Solstice",
    ],
    # ── COMPOUND: multi-part surnames with separators ──────────────────────
    "compound": [
        "Del Marque", "Ko Sienne", "Van Aldric", "De Thoral", "Al Severik",
        "Von Kessler", "El Tavarin", "Do Carvane", "Na Velisse", "Te Morvane",
        "Or Fessiden", "Ul Grevane", "Lo Thessan", "Re Corvaine", "Di Marchell",
        "Ka Ondraev", "Ve Solarin", "Ta Brevonne", "Su Kelvarne", "Mo Drevaine",
        "Sha Vorentis", "Ni Kessarde", "Zu Bellavan", "Ri Thorvane", "Fe Galisten",
        "Pa Ondrevic", "Ji Corvellen", "Wu Tessaran", "Ha Belvoine", "Qi Marchivel",
    ],
    # ── BEAST/NATURE: derived from animals, plants, or natural forces ──────
    "beast_nature": [
        "Wolfmane", "Crowhollow", "Bearfang", "Hawkrest", "Serpentcoil",
        "Staghelm", "Viperthorn", "Owlmere", "Foxhollow", "Lynxclaw",
        "Ravensteel", "Elkhart", "Boargrove", "Falconcrest", "Mantisward",
        "Eaglebone", "Waspsting", "Badgercroft", "Mothwing", "Heronwick",
        "Pinecrest", "Thorncrest", "Ivywood", "Briarhollow", "Mossgrave",
        "Thistleward", "Fernhollow", "Willowmere", "Oakenhart", "Cedarvane",
    ],
    # ── ABSTRACT: conceptual or philosophical surnames ─────────────────────
    "abstract": [
        "Solace", "Reckoning", "Valor", "Providence", "Absolution",
        "Temperance", "Dominion", "Severance", "Defiance", "Perdurance",
        "Ascension", "Tribulation", "Sovereignty", "Deliverance", "Fortitude",
        "Penitence", "Eminence", "Transcendence", "Steadfast", "Vengeance",
        "Perpetuance", "Endurance", "Sufferance", "Accordance", "Divergence",
        "Temperance", "Remembrance", "Forbearance", "Jubilance", "Luminance",
    ],
}


# ═══════════════════════════════════════════════════════════════════════════════
# Utility: style metadata for name generation prompts
# ═══════════════════════════════════════════════════════════════════════════════

PHONETIC_STYLE_DESCRIPTIONS = {
    "flowing": "vowel-heavy, melodic, soft consonants — names that roll off the tongue",
    "clipped": "consonant-heavy, 1-2 syllables, punchy — names that snap",
    "lyrical": "3+ syllables, musical rhythm — names that sound like incantations",
    "earthy": "naturalistic, grounded — names that feel like the land itself",
    "sharp": "angular, unusual phonemes, distinctive — names that catch the ear",
    "guttural": "harsh, back-of-throat, forceful — names forged in fire",
    "sibilant": "s/sh/z/th-heavy, whispery — names that hiss and whisper",
    "rhythmic": "repeated syllables or patterns, percussive — names with internal rhythm",
    "ancient": "archaic-sounding, weathered — names that have survived centuries",
}

SURNAME_STYLE_DESCRIPTIONS = {
    "patronymic": "derived from an ancestor's name (e.g., Alderson, Thorsdottir)",
    "place_based": "derived from geography or landmarks (e.g., Ashenmere, Thornwick)",
    "occupation": "derived from trades, roles, or skills (e.g., Forgewright, Tidewalker)",
    "single_word": "evocative standalone words (e.g., Silence, Kindling)",
    "compound": "multi-part surnames with separators (e.g., Del Marque, Ko Sienne)",
    "beast_nature": "derived from animals, plants, or natural forces (e.g., Wolfmane, Crowhollow)",
    "abstract": "conceptual or philosophical surnames (e.g., Solace, Reckoning)",
}
