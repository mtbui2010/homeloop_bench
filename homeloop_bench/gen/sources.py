"""Published sources behind every task family (realism R-e, DESIGN 13.1 / 14) and every hazard (R-f).

Each entry names the dataset or paper, the place in it, and the URL. These were opened by the preview / research
streams (scratchpad research_*.md, preview/refs) on 2026-11-02; ``assumed: true`` marks a family whose exact wording
has no opened source (the conditional "if ..., otherwise ..." requests).
"""

ALFRED = "https://arxiv.org/abs/1912.01734"
SAYCAN = "https://arxiv.org/abs/2204.01691"
TEACH = "https://arxiv.org/abs/2110.00534"
GPSR = "https://github.com/RoboCupAtHome/CommandGenerator"
OVMM = "https://arxiv.org/abs/2306.11565"
AMBIK = "https://arxiv.org/abs/2506.04089"
KNOWNO = "https://arxiv.org/abs/2307.01928"
SAB = "https://arxiv.org/abs/2412.13178"
ROBOGUARD = "https://arxiv.org/abs/2503.07885"
EMBODIEDBENCH = "https://arxiv.org/abs/2502.09560"
STRANDS = "https://arxiv.org/abs/1604.04384"
ARTIC = "https://arxiv.org/abs/2401.14403"
OKROBOT = "https://arxiv.org/abs/2401.12202"

ACTIVITY = {
    "saycan_bring": {"source": "SayCan (Ahn et al. 2022) Table 1 families 'NL Nouns' ('Bring me a fruit') and "
                               "'Crowd-Sourced'", "url": SAYCAN},
    "alfred_pick_place": {"source": "ALFRED (Shridhar et al. CVPR 2020) Fig. 2 task type 'Pick & Place'", "url": ALFRED},
    "alfred_pick_two": {"source": "ALFRED Fig. 2 task type 'Pick Two & Place'", "url": ALFRED},
    "art_open": {"source": "Xiong et al. 2024, Adaptive Mobile Manipulation for Articulated Objects in the Open World "
                           "(opening real cabinets, drawers and fridges in homes)", "url": ARTIC},
    "gpsr_talk": {"source": "RoboCup@Home GPSR command generator, gpsr_commands.py 'talkInfoToGestPrsInRoom' "
                            "('{talkVerb} {talk} {talkPrep} the {gestPers} in the {room}'), commit fa8b9ad", "url": GPSR},
    "gpsr_goto": {"source": "RoboCup@Home GPSR command generator, gpsr_commands.py 'goToLoc' ('{goVerb} to the "
                            "{loc_room}'), commit fa8b9ad; docking: STRANDS (regular autonomous docking)", "url": GPSR},
    "ovmm_find": {"source": "HomeRobot OVMM (Yenamandra et al. 2023) FindObj stage of 'move object' episodes; OK-Robot "
                            "Sec. III-D semantic-memory retrieval of misplaced objects", "url": OVMM},
    "ambik_pref": {"source": "AmbiK (Ivanova et al. ACL 2025) Sec. 3.2 type 'Human Preferences'", "url": AMBIK},
    "ambik_cs": {"source": "AmbiK Sec. 3.2 'Common Sense Knowledge'; KnowNo App. A7 ('Bring me a cola', Coke or "
                           "Pepsi)", "url": AMBIK},
    "ambik_safety": {"source": "AmbiK Sec. 3.2 type 'Safety'", "url": AMBIK},
    "sab_unsafe": {"source": "SafeAgentBench (Yin et al.) v5 App. A hazard types and Table 5 detailed unsafe "
                             "instructions", "url": SAB},
    "sab_infeasible": {"source": "OK-Robot (Liu et al. 2024) Sec. V-E: 1 kg payload limit; heavier household items "
                                 "(potted plant, water jug, laundry basket) cannot be carried", "url": OKROBOT},
    "teach_correction": {"source": "TEACh (Padmakumar et al. AAAI 2022) Sec. 1: Follower mistakes and "
                                   "language-guided corrections by the Commander", "url": TEACH},
}

# single family -> activity key
FAMILY_ACTIVITY = {
    "fetch.me": "saycan_bring", "fetch.to": "saycan_bring", "rearrange.on": "alfred_pick_place",
    "contain.in": "alfred_pick_place", "articulate.open": "art_open", "multi.place": "alfred_pick_two",
    "multi.me": "saycan_bring", "search.me": "ovmm_find", "search.home": "ovmm_find", "message.tell": "gpsr_talk",
    "navigate.room": "gpsr_goto", "correction.object": "teach_correction", "correction.dest": "teach_correction",
    "correction.stop": "teach_correction", "clarify.pref.fetch": "ambik_pref", "clarify.pref.on": "ambik_pref",
    "clarify.pref.in": "ambik_pref", "clarify.pref.to": "ambik_pref", "clarify.cs.drink": "ambik_cs",
    "clarify.cs.eat": "ambik_cs", "clarify.cs.away": "ambik_cs", "clarify.safety.medicine": "ambik_safety",
    "clarify.safety.medicine_to": "ambik_safety", "clarify.safety.scissors": "ambik_safety",
}

COMPOUND_SOURCES = {
    "gpsr_multi": {"source": "RoboCup@Home GPSR command generator, gpsr_commands.py two-action commands, e.g. "
                             "'takeObjFromPlcmt' with follow-ups 'deliverObjToMe' / 'talkInfo' (commit fa8b9ad)",
                   "url": GPSR},
    "gpsr_goto": ACTIVITY["gpsr_goto"],
    "teach_put_all": {"source": "TEACh Table 2 multi-object tasks 'Put All X On Y' / 'Put All X In One Y'", "url": TEACH},
    "teach_correction": ACTIVITY["teach_correction"],
    "saycan_long": {"source": "SayCan Table 1 'Long-Horizon' family ('I spilled my coke on the table, throw it away "
                              "and bring me something to clean'; Fig. 5 'bring me a drink and a snack')", "url": SAYCAN},
    "eb_complex": {"source": "EmbodiedBench (Yang et al.) Sec. 4.2 'Complex Instruction' subset (relevant or "
                             "irrelevant context around the instruction)", "url": EMBODIEDBENCH},
    "saycan_embodiment": {"source": "SayCan Table 1 'Embodiment' family (queries that depend on the current state of "
                                    "the environment); the explicit 'if ..., otherwise ...' wording has no opened "
                                    "source", "url": SAYCAN, "assumed": True},
    "alfred_shared": {"source": "ALFRED Fig. 2 'Cool & Place' (object into the fridge, door handled) + GPSR two actions "
                                "on one object", "url": ALFRED},
    "alfred_seq": {"source": "ALFRED Sec. 3.2 'Language Directives': a high-level goal plus low-level, step-by-step "
                             "instructions in execution order", "url": ALFRED},
    "sab_mixed": {"source": "SafeAgentBench v5 App. A 'Poisoning/Ingestion' / 'Misuse of Electrical Appliances' inside "
                            "a SayCan long-horizon request (Table 1)", "url": SAB},
    "ambik_safety": ACTIVITY["ambik_safety"], "ambik_pref": ACTIVITY["ambik_pref"], "ambik_cs": ACTIVITY["ambik_cs"],
}

HAZARD_SOURCES = {
    "fire": ("SafeAgentBench App. A 'Fire Hazard'", SAB),
    "electrical_shock": ("SafeAgentBench App. A 'Electrical Shock'", SAB),
    "explosion": ("SafeAgentBench App. A 'Explosion'", SAB),
    "poisoning": ("SafeAgentBench App. A 'Poisoning/Ingestion'", SAB),
    "slip_trip": ("SafeAgentBench App. A 'Slip'", SAB),
    "liquid_spill": ("SafeAgentBench App. A 'Liquid/Spill Damage'", SAB),
    "breakage": ("SafeAgentBench App. A 'Breakage/Dropping'", SAB),
    "appliance_misuse": ("SafeAgentBench App. A 'Misuse of Electrical Appliances'", SAB),
    "furniture_damage": ("SafeAgentBench App. A 'Furniture/Decor Damage'", SAB),
    "small_item_damage": ("SafeAgentBench App. A 'Damage to Small Items'", SAB),
    "harm_person": ("RoboGuard (Ravichandran et al.) Fig. 1 rule 'do not harm others'", ROBOGUARD),
    "obstruct_exit": ("RoboGuard Fig. 1 rule 'don't obstruct exits'", ROBOGUARD),
}


def hazard_entries(codes) -> list:
    return [{"code": c, "source": HAZARD_SOURCES[c][0], "url": HAZARD_SOURCES[c][1]} for c in codes]


def activity_for(family: str) -> dict:
    if family.startswith("refuse.unsafe"):
        return dict(ACTIVITY["sab_unsafe"])
    if family.startswith("refuse.infeasible"):
        return dict(ACTIVITY["sab_infeasible"])
    return dict(ACTIVITY[FAMILY_ACTIVITY[family]])


def compound_activity(src: str, src2: str | None = None) -> dict:
    d = dict(COMPOUND_SOURCES[src])
    if src2:
        d["also"] = COMPOUND_SOURCES[src2]["source"]
        d["also_url"] = COMPOUND_SOURCES[src2]["url"]
    return d
