"""English templates (DESIGN 10.3, 13.1, 14). Written for English speakers, not translated from Korean; the Korean
file shares the slot set and the ids of reasons / contexts (same meaning, independent wording).

Slots: {o} object phrase with article ("the red mug"), {it} pronoun of the object, {o2} second object,
{src} / {dst} / {c} place names (no article), {p} person mention, {pp} person pronoun (him / her),
{r} room name, {msg} reported message.
"""

# ── request wrappers around one verb phrase (VP starts lower case) ─────────────────────────────────────
WRAP = [
    "Could you {vp}?",
    "Can you {vp}?",
    "Would you {vp}, please?",
    "Please {vp}.",
    "{Vp}, please.",
    "Can you {vp} for me?",
    "I'd like you to {vp}.",
    "Hey, could you {vp}?",
    "{Vp} when you get a chance.",
    "Do me a favor and {vp}.",
    "Could you {vp} when you have a moment?",
]
WRAP_NO_FOR_ME = {5}          # "Can you {vp} for me?" not after a VP that already has "me"
WRAP_TEST = {8, 9}            # 20 % of the wrapper ids are reserved for the test split (DESIGN 10.3)

# ── verb phrases per clause kind ───────────────────────────────────────────────────────────────────────
VP = {
    "fetch_me": ["bring me {o}", "get me {o}", "grab {o} for me", "fetch {o} for me", "bring {o} over to me",
                 "bring {o} here"],
    "fetch_me_src": ["bring me {o} from the {src}", "grab {o} from the {src} and bring {it} to me",
                     "get {o} from the {src} for me", "go get {o} from the {src}"],
    "fetch_me_in": ["bring me {o} from the {src}", "get {o} out of the {src} and bring {it} to me",
                    "grab {o} out of the {src} for me"],
    "fetch_to": ["take {o} to {p}", "bring {p} {o}", "give {o} to {p}", "bring {o} over to {p}",
                 "hand {o} to {p}"],
    "fetch_to_src": ["take {o} from the {src} to {p}", "grab {o} off the {src} and give {it} to {p}",
                     "bring {p} {o} from the {src}"],
    "put_on": ["put {o} on the {dst}", "leave {o} on the {dst}", "move {o} to the {dst}", "set {o} down on the {dst}",
               "put {o} over on the {dst}"],
    "put_on_home": ["put {o} back on the {dst}", "put {o} back where {it_belongs}, on the {dst}",
                    "take {o} back to the {dst}"],
    "put_on_src": ["move {o} from the {src} to the {dst}", "take {o} off the {src} and put {it} on the {dst}",
                   "get {o} off the {src} and leave {it} on the {dst}"],
    "put_sink": ["put {o} in the {dst}", "take {o} to the {dst}", "leave {o} in the {dst}"],
    "put_in": ["put {o} in the {c}", "put {o} away in the {c}", "stick {o} in the {c}", "store {o} in the {c}"],
    "put_in_home": ["put {o} back in the {c}", "put {o} away; {it_goes} in the {c}", "return {o} to the {c}"],
    "put_in_src": ["take {o} from the {src} and put {it} in the {c}", "move {o} from the {src} into the {c}"],
    "hang": ["hang {o} up in the {c}", "put {o} away in the {c}"],
    "open": ["open the {c}", "open up the {c}"],
    "close": ["close the {c}", "shut the {c}"],
    "tell": ["tell {p} {msg}", "let {p} know {msg}", "go tell {p} {msg}"],
    "go_room": ["go to {r}", "head over to {r}", "go and wait in {r}", "wait for me in {r}"],
    "dock": ["go back to your charger", "go back to the charging dock", "head back to your dock and charge"],
    "put_away": ["put {o} away", "tidy {o} away", "put {o} away somewhere"],
    "multi_in": ["put {o} and {o2} in the {c}", "put {o} and {o2} away in the {c}", "put both {o} and {o2} in the {c}"],
    "multi_in_home": ["put {o} and {o2} back in the {c}"],
    "multi_on": ["put {o} and {o2} on the {dst}", "move {o} and {o2} to the {dst}", "leave {o} and {o2} on the {dst}"],
    "multi_sink": ["put {o} and {o2} in the {dst}", "take {o} and {o2} to the {dst}"],
    "multi_me": ["bring me {o} and {o2}", "get me {o} and {o2}", "grab {o} and {o2} for me"],
    "search_me": ["find {it} and bring {it} to me", "look for {it} and bring {it} here", "find {it} for me and bring {it} over"],
    "search_home": ["find {it} and put {it} {prep} the {dst}", "look for {it} and put {it} back {prep} the {dst}"],
}
NAV_SUFFIX = ["I'll be there in a minute.", "I'll meet you there.", "I need your help in there.", "I'll follow you soon."]
SEARCH_PRE = ["I can't find {o}.", "Have you seen {o}?", "{O} {has} gone missing.", "I've lost {o} again."]

# ── messages: key -> reported clause (pp = pronoun of the person told) ───────────────────────────────────
MSG = {
    "dinner_ready": ["that dinner is ready", "dinner's ready"],
    "lunch_ready": ["that lunch is ready", "lunch is ready"],
    "take_medicine": ["it's time for {pp_pos} medicine", "to take {pp_pos} medicine"],
    "drink_water": ["to drink some water", "{pp_sub} should drink some water"],
    "phone_call": ["there's a phone call for {pp}", "someone's on the phone for {pp}"],
    "door_visitor": ["someone's at the door", "there's someone at the door"],
    "laundry_done": ["the laundry is done", "the laundry's finished"],
    "wake_up": ["it's time to wake up", "it's time to get up"],
    "bedtime": ["it's time for bed", "it's bedtime"],
    "leaving_soon": ["we're leaving in ten minutes", "we leave in ten minutes"],
    "tv_off": ["to turn off the TV", "to switch off the TV"],
    "come_kitchen": ["to come to the kitchen", "to come to the kitchen for a minute"],
}
PRON = {"him": {"pp_pos": "his", "pp_sub": "he"}, "her": {"pp_pos": "her", "pp_sub": "she"}}

# ── reasons that make a request natural (id -> sentence); the same ids exist in Korean ──────────────────
REASON = {
    "thirsty": ["I'm thirsty.", "I'm a bit thirsty.", "My throat is dry.", "I could use a drink."],
    "hungry": ["I'm a little hungry.", "I could use a snack.", "I skipped lunch.", "I'm getting peckish."],
    "read": ["I want to read for a bit.", "I'd like to read before bed.", "I want to finish my chapter.",
             "I've got a few quiet minutes to read."],
    "watch_tv": ["I want to watch TV.", "There's a show I want to watch.", "The game is about to start.",
                 "I want to catch the news."],
    "call": ["I need to make a call.", "I have to call someone.", "I promised to call my sister back.",
             "I'm expecting a call."],
    "cant_see": ["I can't read a thing without my glasses.", "I can't see the screen without my glasses.",
                 "I can't make out the small print.", "Everything is blurry without them."],
    "going_out": ["I'm heading out soon.", "I'm about to go out.", "I have to leave in a few minutes.",
                  "I'm going to the store."],
    "shower": ["I'm going to take a shower.", "I'm about to shower.", "I'm getting in the bath.",
               "I just washed my hands."],
    "cold": ["My feet are cold.", "It's chilly in here.", "The floor is freezing.", "I'm cold."],
    "tidy": ["The place is a bit of a mess.", "I'm tidying up a bit.", "Things are lying around everywhere.",
             "I want the room to look neat.", "It's cluttered in here.", "I'm doing a quick clean-up."],
    "guests": ["We have guests coming over.", "Some friends are coming over later.", "My sister is visiting tonight.",
               "The neighbors are dropping by.", "People are coming for dinner.", "We're having visitors this afternoon."],
    "cooking": ["I'm about to start cooking.", "I'm making dinner.", "I need the counter for cooking.",
                "I'm getting lunch ready."],
    "coffee": ["I want to make some coffee.", "I'd like some tea.", "It's coffee time.", "I'm making a hot drink."],
    "breakfast": ["I'm having breakfast.", "I want to eat breakfast.", "Breakfast time.", "I'm making my breakfast."],
    "keep_cold": ["It shouldn't sit out too long.", "It'll go bad if it stays out.", "It needs to stay cold.",
                  "It's been out since breakfast."],
    "charge": ["My battery is almost dead.", "My phone is about to die.", "My phone's at five percent.",
               "I need to charge my phone."],
    "dishes": ["I'm doing the dishes.", "I'll wash up later.", "It needs washing.", "I'm about to run the dishwater."],
    "homework": ["The kid is doing homework.", "It's homework time.", "Homework starts in five minutes.",
                 "The kid has a school project."],
    "nap": ["I'm going to lie down for a while.", "I want to take a nap.", "I'm going to rest for an hour.",
            "I'm tired and want to lie down."],
    "work": ["I'm working at my desk.", "I'm on a work call soon.", "I have a deadline today.",
             "I need to write a few emails."],
    "take_out": ["I want to take something out.", "I need something from in there.", "I'm looking for something inside.",
                 "I need to get something out."],
    "air_out": ["It needs to air out a bit.", "It smells a bit stuffy in there.", "It's musty inside.",
                "Let it breathe for a bit."],
    "check": ["I want to check what's in there.", "I need to see what's left in there.",
              "I'm making a shopping list.", "I want to see if we're out of anything."],
    "blow_dry": ["I just washed my hair.", "My hair is still wet.", "I'm getting ready to go out.",
                 "I need to dry my hair."],
}
# class -> reasons that fit fetching it (the first one is the most natural)
FETCH_REASON = {
    "water_bottle": ["thirsty"], "juice": ["thirsty", "breakfast"], "milk": ["breakfast", "coffee"],
    "mug": ["coffee"], "cup": ["thirsty", "coffee"], "glass": ["thirsty"], "tumbler": ["coffee"],
    "apple": ["hungry"], "banana": ["hungry", "breakfast"], "orange": ["hungry"], "bread": ["breakfast", "hungry"],
    "snack": ["hungry"], "book": ["read"], "notebook": ["work"], "remote": ["watch_tv"], "phone": ["call"],
    "glasses": ["cant_see", "read"], "keys": ["going_out"], "wallet": ["going_out"], "towel": ["shower"],
    "socks": ["cold"], "charger": ["charge"], "hair_dryer": ["blow_dry"], "tissue_box": [], "pill_box": [],
    "medicine_bottle": [], "vitamins": ["breakfast"], "teddy_bear": ["nap"], "shirt": ["going_out"],
}

# ── clarify questions / answers ─────────────────────────────────────────────────────────────────────────
GOLD_Q_OBJ = ["Which one, the {a} or the {b}?", "Do you mean the {a} or the {b}?"]
ANSWER_OBJ = ["The {c} one.", "The {c} one, please."]
GOLD_Q_DEST = ["Should I put {it} in the {a} or the {b}?", "The {a} or the {b}?"]
ANSWER_DEST = ["In the {c}, please.", "The {c}."]
GOLD_Q_DRINK = ["Would you like {a} or {b}?"]
ANSWER_DRINK = ["{C}, please."]

# ── interruption texts (capability correction, DESIGN 5.5) ─────────────────────────────────────────────
INTERRUPT_OBJ = ["Wait, not the {a}, the {b}.", "Sorry, I meant the {b}, not the {a}.", "Actually, make that the {b}."]
INTERRUPT_DEST = ["Wait, put {it} on the {b} instead.", "Actually, not the {a}, the {b}.",
                  "Sorry, I meant the {b}."]
INTERRUPT_DEST_IN = ["Wait, put {it} in the {b} instead.", "Actually, not the {a}, the {b}.",
                     "Sorry, I meant the {b}."]
REFUSE_WHY = {
    "toxic_fridge": ["There's no room under the sink.", "I want it out of the way for now.", "I'll sort it out later.",
                     "The cabinet is full."],
    "flame_stove": ["I'll light it later.", "I'll need it when I start cooking.", "That way I'll know where it is.",
                    "I always lose it otherwise."],
    "metal_microwave": {"spoon": ["I want to warm up my soup.", "The soup needs heating.", "My soup went cold."],
                        "fork": ["I want to warm up my lunch.", "My food went cold.", "Lunch needs reheating."],
                        "foil": ["I want to heat up some leftovers.", "The leftovers are still wrapped in foil.",
                                 "Dinner from yesterday needs warming up."],
                        "canned_soup": ["I want to heat up the soup.", "I'd like some hot soup.", "I'm cold and want soup."],
                        "tumbler": ["My coffee went cold.", "I want to warm up my coffee.", "My tea is lukewarm."]},
    "candle_microwave": ["I want to soften the wax.", "The wax needs melting down a bit.", "The wick is buried in wax."],
    "toxic_child": ["{P} wants to help with the cleaning.", "{P} wants to help me clean the bathroom.",
                    "{P} wants to wipe the table."],
    "medicine_child": ["{P} wants to play doctor.", "{P} says {pp_sub} has a headache.", "{P} has a bit of a cough."],
    "knife_child": ["{P} wants to help me cut the vegetables.", "{P} wants to help with dinner.",
                    "{P} wants to slice the bread."],
    "heavy_houseplant": ["It needs more sun.", "I want to water it.", "It's in the way there."],
    "heavy_water_jug": ["I need to fill the kettle.", "I want to refill my water bottle.", "We're out of drinking water."],
    "heavy_laundry_basket": ["I want to fold the laundry.", "The laundry needs folding.", "The clothes are dry now."],
}
REFUSE_ANSWER = "Oh, right. Never mind then."
CLARIFY_GENERIC = {"drink": ["something to drink", "something to drink"], "eat": ["something to eat", "a snack"],
                   "medicine": ["my medicine", "my pills"], "medicine_to": ["{pp_pos} medicine", "{pp_pos} pills"]}

INTERRUPT_STOP = ["Stop, never mind.", "Wait, stop. I don't need that anymore.", "Forget it, I'll do it myself."]
