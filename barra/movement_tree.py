"""Naming the movement by asking small questions instead of one large one.

The classifier this replaces asked a vision model to name the exercise with no
vocabulary at all - `detected_exercise: "<movement name or none>"` - and took
whatever string came back. On the author's own clips that produced
`back_lever`, `handstand` and `monkey_bar_traverse`: plausible English, and
none of it a node in `barra.skills`, so nothing downstream could use it.

The obvious repair is to paste all 88 skill ids into the prompt. That trades
one failure for a worse one. A flat list asks the model to hold every
distinction at once - dip against korean dip, tuck planche against advanced
tuck planche - when most of those pairs are irrelevant the moment you know the
body is hanging rather than on the floor. Long option lists also bias toward
whatever sits near the start, and a wrong answer arrives with no record of
where the reasoning went astray.

So this asks in stages. Each node poses ONE question with a handful of options,
each option carrying a description of what the camera would actually see, and
the answer selects the next question. Three or four small questions reach a
leaf, and the PATH is kept: "hanging → body horizontal, face up → straddle"
is auditable in a way that "front_lever, confidence 0.7" is not, and when it
goes wrong you can see which question was answered badly.

Two properties make the tree small enough to be worth it:

  * **The first split is what a camera sees, not what a coach means.** The
    families in `barra.skills` are push/pull/core/legs/balance/bar, which group
    by training purpose - `knee_raise` is core and `pull_up` is pull, yet both
    are a person hanging from a bar and the difference is only what moves. The
    root here splits on how the body is supported, because that is the fact a
    still frame states most loudly.
  * **Progressions share one vocabulary.** Tuck, advanced tuck, straddle, half,
    full is the same axis for planche, front lever, back lever and human flag.
    Asking "how are the legs held" once, as a reusable node, replaces four
    near-identical branches.

Every leaf is a real skill id and every skill is reachable; `validate()` proves
both against `barra.skills`, and the test suite calls it, so the tree cannot
quietly drift from the graph it names.

`unclear` is an answer at every node, never a forced choice. A camera behind a
pillar, a clip that cuts before the hold - collapsing those into a guess is how
a classifier manufactures confidence it has not got. A walk that ends unclear
returns the path it managed and no skill, which is a usable answer: it says
which distinction the footage could not support.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .skills import SKILLS

UNCLEAR = "unclear"


@dataclass(frozen=True)
class Option:
    """One answer to a node's question.

    Exactly one of `then` (ask this node next) or `skill` (stop, this is the
    movement) is set. `seen` is the whole point of the class: it is what the
    camera would show, written so that a model choosing between options is
    comparing observations rather than guessing at vocabulary.
    """
    key: str
    seen: str
    then: str = ""
    skill: str = ""

    def __post_init__(self):
        # `unclear` is the one option that leads nowhere by design: it ends the
        # walk without naming a movement. Every other option must go somewhere.
        if self.key == UNCLEAR:
            if self.then or self.skill:
                raise ValueError(
                    f"the {UNCLEAR!r} option must not lead anywhere - it is "
                    "how a walk declines to answer")
            return
        if bool(self.then) == bool(self.skill):
            raise ValueError(f"option {self.key!r} needs exactly one of then/skill")


@dataclass(frozen=True)
class Node:
    id: str
    question: str
    options: tuple[Option, ...]
    # Shown above the options. Use it for the one thing that most often gets
    # answered wrongly at this node, not for general encouragement.
    hint: str = ""

    def option(self, key: str) -> Option | None:
        for o in self.options:
            if o.key == key:
                return o
        return None


def _n(id, question, options, hint=""):
    return Node(id, question, tuple(options), hint)


# --------------------------------------------------------------------------
# Shared progression node.
#
# Tuck / advanced tuck / straddle / half / full is one axis used by four
# different holds. Writing it once and pointing four branches at it is not
# only shorter - it means the descriptions of "straddle" cannot drift apart
# between front lever and planche, which is exactly the kind of inconsistency
# that makes a long prompt unreliable.
# --------------------------------------------------------------------------

def _progression(node_id: str, tuck: str, adv: str, straddle: str,
                 full: str, half: str = "", question: str = "") -> Node:
    opts = [
        Option("tuck", "Knees pulled tight to the chest, hips and knees fully "
                       "folded. The body makes a small ball.", skill=tuck),
        Option("advanced_tuck", "Knees still bent but carried away from the "
                                "chest, thighs roughly in line with the torso. "
                                "Longer than a tuck, not straight.", skill=adv),
        Option("straddle", "Legs straight and spread wide apart in a V.",
               skill=straddle),
        Option("full", "Legs straight and held together, the whole body in one "
                       "line.", skill=full),
    ]
    if half:
        opts.insert(3, Option(
            "half", "Legs straight and together but the hips folded, so the "
                    "torso and legs make an L rather than one line.", skill=half))
    opts.append(Option(UNCLEAR, "The leg position is not visible."))
    return _n(node_id,
              question or "How are the legs held during the hold?",
              opts,
              hint="Judge from the frame where the hold is most established, "
                   "not the entry or the exit.")


NODES: dict[str, Node] = {}


def _add(node: Node) -> Node:
    NODES[node.id] = node
    return node


# ---- root: how is the body supported? ------------------------------------

_add(_n(
    "support",
    "How is the body supported?",
    [
        Option("hanging",
               "The hands grip a bar, rings or a high surface ABOVE the head, "
               "and the body hangs below them.", then="hang_what"),
        Option("bars_support",
               "The hands grip parallel bars, rings, a bench or a dip station "
               "at roughly HIP height, arms pressing down, and the torso is "
               "held ABOVE the hands.", then="support_what"),
        Option("floor_prone",
               "The hands or forearms are on the floor or a raised surface and "
               "the body is face-DOWN and roughly horizontal.",
               then="prone_what"),
        Option("inverted",
               "The body is upside down with the weight on the hands and the "
               "hips ABOVE the shoulders.", then="inverted_what"),
        Option("standing",
               "The weight is on the FEET - standing, squatting, lunging or "
               "kneeling.", then="legs_what"),
        Option("floor_supine",
               "The person is lying on their back, or sitting on the floor, "
               "with the back or hips in contact with the ground.",
               then="supine_what"),
        Option("side_pole",
               "The hands grip a VERTICAL pole or bar and the body is held out "
               "to the SIDE of it.", then="flag_what"),
        Option(UNCLEAR,
               "The framing, lighting or camera angle does not show how the "
               "body is supported.", skill=""),
    ],
    hint="Answer for the part of the clip where the exercise is actually being "
         "performed, ignoring any walk-up, rest or talking to camera.",
))

# ---- hanging -------------------------------------------------------------

_add(_n(
    "hang_what",
    "While hanging, what is happening?",
    [
        Option("feet_down",
               "The FEET stay on the ground under a low bar and the body is "
               "angled, pulling the chest up toward the bar.",
               skill="australian_row"),
        Option("arms_pull",
               "The body stays roughly VERTICAL and the ARMS bend to pull the "
               "chest up toward the bar.", then="pull_how"),
        Option("legs_lift",
               "The torso stays roughly vertical and the LEGS lift up in front "
               "of the body.", then="hang_legs"),
        Option("horizontal_faceup",
               "The body is held HORIZONTAL with the chest and face pointing "
               "UP, the back toward the ground.", then="front_lever_how"),
        Option("horizontal_facedown",
               "The body is held HORIZONTAL with the chest and face pointing "
               "DOWN, the back toward the ceiling.", then="back_lever_how"),
        Option("over_the_bar",
               "The person travels from BELOW the bar to ABOVE it, ending with "
               "the arms straight and the torso over the bar.",
               then="muscle_up_how"),
        Option("rotating",
               "The body rotates backwards through the arms, passing upside "
               "down between them, and returns.", skill="skin_the_cat"),
        Option("shoulders_only",
               "The arms stay STRAIGHT throughout and only the shoulders move, "
               "lifting and lowering the body a few centimetres.",
               skill="scapular_pull"),
        Option("static_hang",
               "The person simply hangs still with straight arms and does not "
               "pull, lift or rotate.", skill="dead_hang"),
        Option(UNCLEAR,
               "The person is hanging but what they are doing is not visible.",
               skill=""),
    ],
))

_add(_n(
    "pull_how",
    "What is distinctive about the pull?",
    [
        Option("one_arm_only",
               "Only ONE hand is on the bar, with no assistance.",
               skill="one_arm_pull_up"),
        Option("one_arm_assisted",
               "One hand is on the bar and the other holds a band, towel, or "
               "the assisting wrist.", skill="assisted_one_arm_pull_up"),
        Option("one_arm_lowering",
               "Only one hand is on the bar and the person is LOWERING under "
               "control, never pulling up.", skill="one_arm_negative"),
        Option("side_to_side",
               "Both hands stay on a wide bar and the body travels SIDEWAYS "
               "from one hand to the other while staying high.",
               skill="typewriter_pull_up"),
        Option("one_arm_straight",
               "Both hands are on a wide bar; one arm bends to pull while the "
               "other stays STRAIGHT, so the body rises beside one hand.",
               skill="archer_pull_up"),
        Option("added_weight",
               "A belt, vest, dumbbell or plate adds visible external load.",
               skill="weighted_pull_up"),
        Option("chest_touches",
               "The bar is met by the CHEST or collarbone, clearly higher than "
               "chin height.", skill="chest_to_bar"),
        Option("explosive",
               "The pull is fast enough that the hands LEAVE the bar, or the "
               "body rises to waist height, without going over the bar.",
               skill="explosive_pull_up"),
        Option("lowering_only",
               "The person starts at the top with both hands and only LOWERS, "
               "never pulling up.", skill="negative_pull_up"),
        Option("palms_toward",
               "An ordinary two-arm pull with the palms facing TOWARD the "
               "person (underhand grip).", skill="chin_up"),
        Option("palms_away",
               "An ordinary two-arm pull with the palms facing AWAY from the "
               "person (overhand grip).", skill="pull_up"),
        Option(UNCLEAR,
               "It is a pull, but the grip, load or range cannot be made out.",
               skill=""),
    ],
    hint="Check for one arm, added weight and grip direction before settling "
         "on an ordinary pull-up.",
))

_add(_n(
    "hang_legs",
    "How far do the legs travel, and are they straight?",
    [
        Option("feet_to_bar",
               "The feet travel all the way up to TOUCH the bar beside or "
               "outside the hands.", skill="toes_to_bar"),
        Option("straight_legs",
               "The legs stay STRAIGHT and rise to roughly horizontal.",
               skill="leg_raise"),
        Option("bent_knees",
               "The knees BEND and the thighs rise to roughly horizontal.",
               skill="knee_raise"),
        Option(UNCLEAR,
               "The legs lift but the height or knee angle is not visible.",
               skill=""),
    ],
))

_add(_progression(
    "front_lever_how",
    tuck="tuck_front_lever", adv="adv_tuck_front_lever",
    straddle="straddle_front_lever", half="half_front_lever",
    full="front_lever",
))

_add(_n(
    "back_lever_how",
    "How are the legs held during the face-down hold?",
    [
        Option("tuck", "Knees pulled tight to the chest.",
               skill="tuck_back_lever"),
        Option("advanced_tuck",
               "Knees bent but carried away from the chest, thighs roughly in "
               "line with the torso.", skill="adv_tuck_back_lever"),
        Option("straddle", "Legs straight and spread wide apart.",
               skill="straddle_back_lever"),
        Option("full", "Legs straight and together, the whole body in one line.",
               skill="back_lever"),
        Option(UNCLEAR, "The leg position is not visible.", skill=""),
    ],
))

_add(_n(
    "muscle_up_how",
    "What is distinctive about getting over the bar?",
    [
        Option("rings",
               "The hands are on RINGS, which turn out at the top, rather than "
               "a fixed bar.", skill="ring_muscle_up"),
        Option("added_weight",
               "A belt, vest or dumbbell adds visible external load.",
               skill="weighted_muscle_up"),
        Option("elbows_back",
               "The person passes over the bar BACKWARDS, elbows rotating "
               "behind the body rather than the chest coming forward.",
               skill="hefesto"),
        Option("full_turn",
               "The person releases the bar and rotates a full 360 degrees "
               "before catching it again.", skill="bar_360"),
        Option("legs_kick",
               "The legs SWING or kick to generate the upward momentum, the "
               "hips leading the movement.", skill="kipping_muscle_up"),
        Option("no_kick",
               "The legs stay still and the body rises by arm and shoulder "
               "strength alone.", skill="strict_muscle_up"),
        Option("partial",
               "The person practises only the passage around the bar, starting "
               "already high or using a band, and does not complete a full "
               "repetition from a hang.", skill="transition_drill"),
        Option("ordinary",
               "A complete repetition over a fixed bar where the use of the "
               "legs cannot be judged.", skill="muscle_up"),
        Option(UNCLEAR,
               "The person gets over the bar but the manner is not visible.",
               skill=""),
    ],
    hint="Choose 'ordinary' rather than guessing between strict and kipping "
         "when the legs are out of frame.",
))

# ---- support (hands at hip height, body above) ---------------------------

_add(_n(
    "support_what",
    "With the body held above the hands, what happens?",
    [
        Option("legs_forward_hold",
               "The body does not travel. The LEGS are held out in front and "
               "the position is held still.", then="lsit_how"),
        Option("press_down",
               "The body LOWERS and presses back up by bending and extending "
               "the elbows.", then="dip_how"),
        Option(UNCLEAR,
               "The body is supported on the hands but what happens is not "
               "visible.", skill=""),
    ],
))

_add(_n(
    "lsit_how",
    "How high are the legs relative to the hands?",
    [
        Option("horizontal",
               "The legs are horizontal, making an L with the torso.",
               skill="l_sit"),
        Option("legs_high",
               "The legs are raised ABOVE horizontal, closer to the chest, "
               "making a V.", skill="v_sit"),
        Option("legs_past_vertical",
               "The legs are carried past vertical toward the head while the "
               "hips stay low, the body bending backwards.", skill="manna"),
        Option(UNCLEAR, "The leg height is not visible.", skill=""),
    ],
))

_add(_n(
    "dip_how",
    "What is distinctive about the press?",
    [
        Option("hands_behind",
               "The hands are BEHIND the person on a bench or chair and the "
               "feet are out in front on the ground.", skill="bench_dip"),
        Option("rings",
               "The hands are on RINGS rather than fixed bars.",
               skill="ring_dip"),
        Option("added_weight",
               "A belt, vest or dumbbell adds visible external load.",
               skill="weighted_dip"),
        Option("behind_the_back",
               "The bar is BEHIND the person's back and the arms press down "
               "behind the body.", skill="korean_dip"),
        Option("ordinary",
               "An ordinary dip on parallel bars, chest between the hands.",
               skill="dip"),
        Option(UNCLEAR, "The equipment or load is not visible.", skill=""),
    ],
))

# ---- prone (hands on floor, body face down) ------------------------------

_add(_n(
    "prone_what",
    "Face down with the hands or forearms down, what is happening?",
    [
        Option("feet_off",
               "The FEET are off the ground and the whole body is balanced on "
               "the hands or elbows alone.", then="prone_balance"),
        Option("press",
               "The feet stay on the ground and the body LOWERS and presses "
               "back up by bending and extending the elbows.",
               then="push_up_how"),
        Option("static",
               "The feet stay on the ground, the body is held STILL in a "
               "straight line and nothing bends.", skill="plank"),
        Option("wheel",
               "The person kneels and rolls a WHEEL or bar forward away from "
               "the knees, then back.", skill="ab_wheel"),
        Option(UNCLEAR,
               "The body is face down but what happens is not visible.",
               skill=""),
    ],
))

_add(_n(
    "prone_balance",
    "How is the balance held?",
    [
        Option("elbows_in_belly",
               "The ELBOWS are tucked into the abdomen and carry the body's "
               "weight like a shelf.", skill="elbow_lever"),
        Option("knees_on_arms",
               "The KNEES rest on the backs of the upper arms and the body is "
               "tucked over the hands.", skill="frog_stand"),
        Option("leaning",
               "The arms are straight and the shoulders lean well forward of "
               "the hands, but the FEET stay in contact with the ground.",
               skill="planche_lean"),
        Option("free_horizontal",
               "The arms are straight, the feet are clear of the ground and "
               "the body is held horizontal, unsupported.",
               then="planche_how"),
        Option(UNCLEAR, "The manner of the balance is not visible.", skill=""),
    ],
))

_add(_progression(
    "planche_how",
    tuck="tuck_planche", adv="adv_tuck_planche",
    straddle="straddle_planche", full="full_planche",
))

_add(_n(
    "push_up_how",
    "What is distinctive about the push-up?",
    [
        Option("one_arm",
               "Only ONE hand is on the ground.", skill="one_arm_push_up"),
        Option("one_arm_straight",
               "Both hands are down and wide; one arm bends while the other "
               "stays STRAIGHT, so the chest lowers beside one hand.",
               skill="archer_push_up"),
        Option("hands_at_waist",
               "The hands are down beside the WAIST rather than the chest, and "
               "the shoulders lean far forward of them.",
               skill="pseudo_planche_push_up"),
        Option("elbows_to_sides",
               "The arms bend until the upper arms are horizontal and the body "
               "presses forward to level, the hips staying high.",
               skill="ninety_degree_push_up"),
        Option("horizontal_press",
               "The body stays HORIZONTAL and unsupported by the feet "
               "throughout, pressing up and down in a planche.",
               skill="planche_push_up"),
        Option("hands_together",
               "The hands are close together under the chest, thumbs and index "
               "fingers nearly touching.", skill="diamond_push_up"),
        Option("hands_wide",
               "The hands are placed noticeably WIDER than the shoulders.",
               skill="wide_push_up"),
        Option("feet_raised",
               "The FEET are on a bench, box or step, higher than the hands.",
               skill="decline_push_up"),
        Option("hands_raised",
               "The HANDS are on a bench, box or bar, higher than the feet, "
               "and the body is at a shallow angle.", skill="incline_push_up"),
        Option("hands_on_wall",
               "The hands are on a WALL and the person stands nearly upright.",
               skill="wall_push_up"),
        Option("on_knees",
               "The KNEES are on the ground rather than the toes.",
               skill="knee_push_up"),
        Option("ordinary",
               "An ordinary push-up: toes down, hands under the chest at "
               "shoulder width.", skill="push_up"),
        Option(UNCLEAR,
               "It is a push-up but the hand position is not visible.",
               skill=""),
    ],
    hint="Check hand position and what the feet rest on before choosing "
         "'ordinary'.",
))

# ---- inverted ------------------------------------------------------------

_add(_n(
    "inverted_what",
    "Upside down on the hands, what is happening?",
    [
        Option("feet_on_wall_low",
               "The hands are on the floor away from a wall and the FEET are "
               "on the wall with the body at an ANGLE, not vertical.",
               skill="wall_plank"),
        Option("press_up_down",
               "The body LOWERS until the head approaches the ground and "
               "presses back up.", then="hspu_how"),
        Option("rises_from_floor",
               "The person RISES into the handstand slowly from the floor "
               "under control, without jumping or kicking.",
               skill="press_to_handstand"),
        Option("one_hand",
               "Only ONE hand is on the ground.", skill="one_arm_handstand"),
        Option("against_wall",
               "The body is vertical and STILL, with the chest or the back "
               "toward a wall for support.", skill="chest_to_wall_handstand"),
        Option("free_still",
               "The body is vertical and STILL with no wall and no support.",
               skill="freestanding_handstand"),
        Option(UNCLEAR,
               "The person is inverted but what happens is not visible.",
               skill=""),
    ],
))

_add(_n(
    "hspu_how",
    "How is the handstand press-up performed?",
    [
        Option("deficit",
               "The hands are raised on blocks, parallettes or bars so the "
               "head travels BELOW the hands.", skill="deficit_hspu"),
        Option("wall",
               "The feet or back rest against a WALL throughout.",
               skill="wall_hspu"),
        Option("free",
               "The handstand is FREESTANDING, with no wall or support.",
               skill="freestanding_hspu"),
        Option(UNCLEAR, "The support and depth are not visible.", skill=""),
    ],
))

# ---- legs ----------------------------------------------------------------

_add(_n(
    "legs_what",
    "With the weight on the feet, what is happening?",
    [
        Option("kneeling_lower",
               "The person KNEELS with the ankles held down and lowers the "
               "whole body forward under control.", skill="nordic_curl"),
        Option("one_leg",
               "The weight is on ONE leg only.", then="one_leg_how"),
        Option("split_stance",
               "The feet are SPLIT front and back, one foot well ahead of the "
               "other, and the back knee lowers toward the ground.",
               then="split_how"),
        Option("both_feet_jump",
               "Both feet are down, the person squats and then JUMPS clear of "
               "the ground.", skill="jump_squat"),
        Option("knees_forward_lean_back",
               "The knees travel far FORWARD and the person leans BACKWARDS, "
               "the body staying in one line from knees to head.",
               skill="sissy_squat"),
        Option("both_feet_squat",
               "Both feet stay flat and side by side and the hips lower and "
               "rise.", skill="squat"),
        Option(UNCLEAR,
               "The stance or the movement is not visible.", skill=""),
    ],
))

_add(_n(
    "one_leg_how",
    "How is the free leg carried?",
    [
        Option("leg_forward",
               "The free leg is held straight out in FRONT and the person "
               "squats all the way down on the other.", skill="pistol_squat"),
        Option("leg_behind",
               "The free leg is folded BEHIND with the knee travelling toward "
               "the ground.", skill="shrimp_squat"),
        Option(UNCLEAR, "The free leg is not visible.", skill=""),
    ],
))

_add(_n(
    "split_how",
    "Where is the back foot?",
    [
        Option("foot_elevated",
               "The back foot is RAISED on a bench, box or step behind the "
               "person.", skill="bulgarian_split_squat"),
        Option("foot_on_floor",
               "The back foot is on the GROUND.", skill="split_squat"),
        Option(UNCLEAR, "The back foot is not visible.", skill=""),
    ],
))

# ---- supine / seated on the floor ---------------------------------------

_add(_n(
    "supine_what",
    "On the back or seated, what is happening?",
    [
        Option("shoulders_anchored",
               "The hands hold a bench or bar BEHIND the head and the whole "
               "body lifts as one rigid line, pivoting on the upper back.",
               skill="dragon_flag"),
        Option("hollow",
               "The person lies on their back with the lower back pressed "
               "down, arms overhead and legs straight, both held clear of the "
               "ground.", skill="hollow_hold"),
        Option(UNCLEAR,
               "The person is on the ground but what they are doing is not "
               "visible.", skill=""),
    ],
))

# ---- side pole -----------------------------------------------------------

_add(_n(
    "flag_what",
    "How is the body held against the vertical pole?",
    [
        Option("body_vertical",
               "The body stays VERTICAL alongside the pole, feet below, held "
               "away from it by the arms.", skill="vertical_flag"),
        Option("body_sideways",
               "The body is held out HORIZONTALLY to the side of the pole.",
               then="flag_how"),
        Option(UNCLEAR, "The body position is not visible.", skill=""),
    ],
))

_add(_n(
    "flag_how",
    "How are the legs held in the sideways hold?",
    [
        Option("tuck", "Knees pulled tight to the chest.",
               skill="tuck_human_flag"),
        Option("straddle", "Legs straight and spread wide apart.",
               skill="straddle_human_flag"),
        Option("full", "Legs straight and together, the body in one line.",
               skill="human_flag"),
        Option(UNCLEAR, "The leg position is not visible.", skill=""),
    ],
))

ROOT = "support"

# The one skill the tree deliberately cannot reach. `front_lever_pull_up` and
# `one_arm_front_lever` ARE reachable as their own leaves below; this list is
# for skills that a still frame genuinely cannot isolate, and is asserted
# empty by the tests unless something is named here with a reason.
UNREACHABLE: dict[str, str] = {}


# ---- leaves that need their own branch, added above the validator --------

_add(_n(
    "front_lever_extra",
    "Is anything added to the front lever hold?",
    [
        Option("pulls", "From the hold, the arms bend and pull the body up "
                        "toward the bar, then lower back to horizontal.",
               skill="front_lever_pull_up"),
        Option("one_hand", "Only ONE hand is on the bar during the hold.",
               skill="one_arm_front_lever"),
        Option("held", "The position is simply held still.",
               then="front_lever_how"),
        Option(UNCLEAR, "Not visible.", skill=""),
    ],
))

# Route the hanging face-up branch through the "anything added" question
# first, so the two hardest front-lever variants are asked about explicitly
# rather than being lost inside the leg-position question.
NODES["hang_what"] = _n(
    "hang_what",
    NODES["hang_what"].question,
    tuple(
        Option(o.key, o.seen, then="front_lever_extra")
        if o.key == "horizontal_faceup" else o
        for o in NODES["hang_what"].options
    ),
    NODES["hang_what"].hint,
)


# --------------------------------------------------------------------------
# Validation and walking
# --------------------------------------------------------------------------

def leaves() -> dict[str, str]:
    """skill id -> the node whose option names it."""
    out = {}
    for node in NODES.values():
        for opt in node.options:
            if opt.skill:
                out[opt.skill] = node.id
    return out


def validate() -> list[str]:
    """Every complaint about the tree, as sentences. Empty means sound.

    Called by the tests rather than at import: a tree that refuses to import
    takes the whole server down with it, and a tree with a dangling branch
    should fail a test run, loudly, on the machine that changed it.
    """
    problems: list[str] = []
    seen_skills = leaves()

    for node in NODES.values():
        keys = [o.key for o in node.options]
        if len(keys) != len(set(keys)):
            problems.append(f"node {node.id!r} has duplicate option keys")
        if UNCLEAR not in keys:
            problems.append(
                f"node {node.id!r} offers no {UNCLEAR!r} answer - every node "
                "must let the model decline rather than guess")
        for opt in node.options:
            if opt.then and opt.then not in NODES:
                problems.append(
                    f"node {node.id!r} option {opt.key!r} points at missing "
                    f"node {opt.then!r}")
            if opt.skill and opt.skill not in SKILLS:
                problems.append(
                    f"node {node.id!r} option {opt.key!r} names {opt.skill!r}, "
                    "which is not a skill in barra.skills")

    for skill_id in SKILLS:
        if skill_id in seen_skills or skill_id in UNREACHABLE:
            continue
        problems.append(
            f"skill {skill_id!r} is in the graph but no branch of the tree "
            "reaches it")

    for skill_id, why in UNREACHABLE.items():
        if skill_id in seen_skills:
            problems.append(
                f"skill {skill_id!r} is listed unreachable ({why}) but the "
                "tree does reach it")

    reached = {ROOT}
    frontier = [ROOT]
    while frontier:
        node = NODES[frontier.pop()]
        for opt in node.options:
            if opt.then and opt.then not in reached:
                reached.add(opt.then)
                frontier.append(opt.then)
    for node_id in NODES:
        if node_id not in reached:
            problems.append(f"node {node_id!r} cannot be reached from {ROOT!r}")

    return problems


@dataclass
class Walk:
    """One classification, with the reasoning kept.

    `path` is the list of (node id, option key) actually taken. It is the
    reason this tree exists: a wrong answer can be attributed to the question
    that was answered badly, which a single label and a confidence cannot do.
    """
    path: list[tuple[str, str]] = field(default_factory=list)
    skill: str = ""
    stopped_at: str = ""
    reason: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.skill)

    def as_trace(self) -> dict:
        return {
            "skill": self.skill,
            "path": [{"node": n, "answer": a} for n, a in self.path],
            "stoppedAt": self.stopped_at,
            "reason": self.reason,
        }


def walk(answer, max_depth: int = 8) -> Walk:
    """Descend the tree, asking `answer(node)` for one option key per node.

    `answer` returns an option key, or something falsy to mean unclear. It is
    deliberately not told anything about vision: the same walk is driven by a
    model in the server, by a human in a review UI, and by a dict in the tests.
    """
    out = Walk()
    node_id = ROOT
    for _ in range(max_depth):
        node = NODES.get(node_id)
        if node is None:
            out.stopped_at = node_id
            out.reason = f"no node {node_id!r}"
            return out
        key = answer(node) or UNCLEAR
        opt = node.option(key)
        if opt is None:
            out.path.append((node.id, key))
            out.stopped_at = node.id
            out.reason = f"{key!r} is not an option here"
            return out
        out.path.append((node.id, opt.key))
        if opt.key == UNCLEAR or (not opt.then and not opt.skill):
            out.stopped_at = node.id
            out.reason = "the footage does not answer this question"
            return out
        if opt.skill:
            out.skill = opt.skill
            return out
        node_id = opt.then
    out.stopped_at = node_id
    out.reason = f"the tree did not reach a movement within {max_depth} questions"
    return out


def prompt_for(node: Node) -> str:
    """The question as a model sees it: one question, a few observations.

    Short on purpose. The whole argument for the tree is that a model choosing
    between six described observations does better than one choosing between
    eighty-eight names, and that only holds if each prompt stays small.
    """
    lines = [node.question]
    if node.hint:
        lines.append(node.hint)
    lines.append("")
    for opt in node.options:
        lines.append(f'- "{opt.key}": {opt.seen}')
    lines.append("")
    lines.append('Reply with ONE JSON object and no markdown fences: '
                 '{"choice": "<one key from the list>", '
                 '"why": "<what in the frames decided it, one short sentence>"}')
    return "\n".join(lines)
