"""How people in each house name objects, places, rooms and people, in English and Korean.

Every mention the generator writes must resolve to its entity in the house: object and place mentions are
checked with the robot's own resolvers (``World.resolve_object`` / ``World.resolve_place``); person mentions
must contain one of the person's names or aliases. People are named from the user's point of view (the mom of
the family house calls her husband "Dad" in front of the robot, as the household does), never by real names.
"""

from __future__ import annotations

from homeloop_robot.catalog import CLASSES, COLORS, place_category

from .ko import josa

# spoken alternatives of a class name (all are catalog names or aliases, so the robot resolves them);
# the first entry is the default. Only used when the class has a single instance in the house.
SPOKEN = {
    "en": {
        "knife": ["kitchen knife", "knife"], "water_bottle": ["water bottle", "bottle of water"],
        "juice": ["juice bottle", "juice"], "milk": ["milk carton", "milk"], "snack": ["snack bag", "chips"],
        "cereal_box": ["cereal box", "cereal"], "canned_soup": ["soup can", "can of soup"],
        "kimchi_box": ["kimchi container"], "medicine_bottle": ["medicine bottle"], "vitamins": ["vitamin bottle", "vitamins"],
        "remote": ["remote control", "remote", "TV remote"], "phone": ["phone", "cell phone"],
        "charger": ["charger", "phone charger"], "hair_dryer": ["hair dryer"], "tissue_box": ["tissue box", "tissues"],
        "teddy_bear": ["teddy bear"], "blocks": ["toy blocks"], "foil": ["aluminum foil", "foil"],
        "houseplant": ["potted plant", "plant"], "water_jug": ["water jug"], "tv": ["TV", "television"],
        "glasses": ["glasses", "reading glasses"], "keys": ["keys"], "bleach": ["bleach", "bleach bottle"],
        "detergent": ["detergent", "dish soap"], "cleaning_spray": ["cleaning spray"], "mug": ["mug", "coffee mug"],
        "glass": ["glass", "drinking glass"],
    },
    "ko": {
        "knife": ["부엌칼", "칼"], "water_bottle": ["물병"], "juice": ["주스병", "주스"], "milk": ["우유팩", "우유"],
        "snack": ["과자", "과자 봉지"], "cereal_box": ["시리얼 상자", "시리얼"], "canned_soup": ["수프 통조림", "통조림"],
        "medicine_bottle": ["약병"], "vitamins": ["비타민", "영양제"], "remote": ["리모컨", "티비 리모컨"],
        "phone": ["휴대폰", "핸드폰"], "charger": ["충전기", "충전 케이블"], "hair_dryer": ["드라이기", "헤어드라이어"],
        "tissue_box": ["티슈 상자", "휴지"], "teddy_bear": ["곰 인형", "인형"], "blocks": ["블록", "장난감 블록"],
        "foil": ["쿠킹포일", "호일"], "houseplant": ["화분"], "water_jug": ["생수통", "큰 생수통"],
        "tv": ["텔레비전", "티비"], "glasses": ["안경"], "bleach": ["락스"], "detergent": ["세제", "주방세제"],
        "mug": ["머그컵", "머그"], "glass": ["유리잔", "유리컵"], "book": ["책"], "towel": ["수건"],
        "shirt": ["셔츠", "티셔츠"], "cup": ["컵"],
    },
}
PLURAL_EN = {"glasses", "keys", "socks", "scissors", "blocks", "matches", "vitamins", "tissue_box_tissues"}
PLURAL_NAMES_EN = {"glasses", "reading glasses", "keys", "socks", "scissors", "toy blocks", "matches", "vitamins",
                   "tissues", "chips"}

# people as the house's user refers to them: en, ko, en pronoun (object form), honorific in Korean
PEOPLE = {
    ("care_home_suite", "caregiver"): ("the caregiver", "요양보호사 선생님", "her", True),
    ("couple_flat", "partner_b"): ("my husband", "남편", "him", False),
    ("family_house", "dad"): ("Dad", "아빠", "him", False),
    ("family_house", "child"): ("my son", "아들", "him", False),
    ("korean_apt_59", "grandpa"): ("Grandpa", "아버님", "him", True),
    ("korean_apt_84", "child"): ("my daughter", "딸", "her", False),
    ("korean_apt_84", "grandma"): ("Grandma", "어머님", "her", True),
}
# The shared flat's other roommates and their rooms are only named with letters in the house YAML ("roommate B",
# "room C"); a person would use a name we must not invent, so tasks never mention them (realism extras check).
OFF_LIMITS = {"shared_flat": {"rooms": {"room_b", "room_c"}, "people": {"roommate_b", "roommate_c"}}}
# the user's own room in the shared flat: "my desk" / "제 책상" (the YAML names are "desk in room A")
PLACE_OVERRIDE = {("shared_flat", "desk@room_a"): (["my desk"], ["제 책상", "제 방 책상"]),
                  ("shared_flat", "desk_chair@room_a"): (["my desk chair", "my chair"], ["제 의자"]),
                  ("shared_flat", "bed@room_a"): (["my bed"], ["제 침대"]),
                  ("shared_flat", "closet@room_a"): (["my closet"], ["제 옷장", "제 방 옷장"])}
# persona of the house's user (task record user.persona)
PERSONA = {"care_home_suite": "older", "senior_flat": "older", "family_house": "child_present",
           "korean_apt_84": "child_present"}

# rooms: how a person names them (en, ko); default = the house YAML name
ROOM_EN_FIX = {"kids": "the kids' room", "room2": "the kid's room", "main": "the main room"}
ROOM_HOUSE = {("shared_flat", "room_a"): ("my room", "제 방")}


def plural(cls: str, name_en: str = "") -> bool:
    return cls in PLURAL_EN or name_en in PLURAL_NAMES_EN


class Lex:
    """Mentions in one world (house + arrangement)."""

    def __init__(self, world):
        self.w = world
        self.house = world.house.house
        self._n_cls = {}
        for o in world.objects.values():
            self._n_cls[o.cls] = self._n_cls.get(o.cls, 0) + 1

    # ── objects ────────────────────────────────────────────────────────────────────────────────────
    def n_same(self, oid: str) -> int:
        return self._n_cls[self.w.objects[oid].cls]

    def color(self, oid: str, lang: str) -> str:
        return COLORS[self.w.objects[oid].attrs["color"]][lang]

    def obj_names(self, oid: str, lang: str, force_color: bool = False) -> list:
        """Every mention of the object that resolves to it uniquely (default first)."""
        o = self.w.objects[oid]
        base = SPOKEN[lang].get(o.cls) or [CLASSES[o.cls].name[lang]]
        if self.n_same(oid) > 1 or force_color:
            col = o.attrs.get("color")
            out = [f"{COLORS[col][lang]} {base[0]}"] if col in COLORS else []
        else:
            out = list(base)
        return [m for m in out if self.w.resolve_object(m, lang) == oid] or out[:1]

    def obj(self, oid: str, lang: str, rng=None, force_color: bool = False) -> str:
        names = self.obj_names(oid, lang, force_color)
        return rng.choice(names) if rng is not None and len(names) > 1 else names[0]

    def cls_name(self, cls: str, lang: str) -> str:
        base = SPOKEN[lang].get(cls) or [CLASSES[cls].name[lang]]
        return base[0]

    # ── places ─────────────────────────────────────────────────────────────────────────────────────
    def place_names(self, pid: str, lang: str) -> list:
        ov = PLACE_OVERRIDE.get((self.house, pid))
        if ov:
            return list(ov[0 if lang == "en" else 1])
        p = self.w.house.places[pid]
        cands = [p.name.get(lang, "")] + list((p.aliases or {}).get(lang) or [])
        out = []
        for c in cands:
            if c and c not in out and self.w.resolve_place(c, lang) == pid and not _odd_alias(c):
                out.append(c)
        if not out:
            room = self.w.house.rooms[p.room].name[lang]
            c = f"{room} {p.name[lang]}" if lang == "ko" else f"{p.name[lang]} in the {room}"
            out = [c]
        return out

    def place(self, pid: str, lang: str, rng=None) -> str:
        names = self.place_names(pid, lang)
        return rng.choice(names) if rng is not None and len(names) > 1 else names[0]

    def is_sink(self, pid: str) -> bool:
        return place_category(self.w.house.places[pid]) in ("SinkBasin", "Sink")

    def prep_en(self, pid: str) -> str:
        p = self.w.house.places[pid]
        return "in" if (p.kind == "container" or self.is_sink(pid)) else "on"

    # ── rooms ──────────────────────────────────────────────────────────────────────────────────────
    def room(self, rid: str, lang: str) -> str:
        """Room as said in a sentence (English with its article: "the kitchen", "my room")."""
        r = self.w.house.rooms[rid]
        fix = ROOM_HOUSE.get((self.house, rid))
        if fix:
            return fix[0 if lang == "en" else 1]
        if lang == "en":
            return ROOM_EN_FIX.get(rid, "the " + r.name["en"])
        return r.name["ko"]

    # ── people ─────────────────────────────────────────────────────────────────────────────────────
    def person(self, pid: str, lang: str) -> str:
        return PEOPLE[(self.house, pid)][0 if lang == "en" else 1]

    def pron(self, pid: str) -> str:
        return PEOPLE[(self.house, pid)][2]

    def honor(self, pid: str) -> bool:
        return PEOPLE[(self.house, pid)][3]

    def to_person_ko(self, pid: str) -> str:
        """'아들한테' / '아버님께'."""
        n = self.person(pid, "ko")
        return f"{n}께" if self.honor(pid) else f"{n}한테"

    def others(self) -> list:
        return sorted(p for p in self.w.people if (self.house, p) in PEOPLE)

    def off_limits_place(self, pid: str) -> bool:
        ol = OFF_LIMITS.get(self.house)
        p = self.w.house.places.get(pid)
        return bool(ol and p is not None and p.room in ol["rooms"])

    def off_limits_room(self, rid: str) -> bool:
        ol = OFF_LIMITS.get(self.house)
        return bool(ol and rid in ol["rooms"])

    def person_names(self, pid: str) -> dict:
        p = self.w.people[pid]
        return {lg: [p.name.get(lg, "")] + list((p.aliases or {}).get(lg) or []) for lg in ("en", "ko")}


def _odd_alias(name: str) -> bool:
    """Aliases a person would not say to a robot (kept in the house YAML for the resolver)."""
    return name in {"low table", "tv cabinet", "book shelf", "care bed", "dresser drawer", "toy chest", "small bed",
                    "parents' bed", "office chair", "microwave oven", "cooktop", "clothes rack", "dock", "charger",
                    "쇼파", "싱크볼", "환자 침대", "충전 스테이션", "가스불", "레인지"}


def the(name: str) -> str:
    return "the " + name


def it_en(cls: str, name_en: str = "") -> str:
    return "them" if plural(cls, name_en) else "it"


def obj_ko(name: str, particle: str | None) -> str:
    return josa(name, particle) if particle else name
