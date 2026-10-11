"""Spanish names for the skill graph (barra/skills.py), for the app.

Kept beside the graph so a new skill without a Spanish name fails
tests/test_skills_export.py instead of reaching the phone in English. Names
the sport uses untranslated in Spain (muscle-up, front lever, back lever,
hefesto, manna) stay as they are.
"""
from __future__ import annotations

# Names used untranslated in Spanish gyms, whose words happen to read as
# English to the language check. Deliberate, so listed.
UNTRANSLATED = {"skin_the_cat"}

FAMILY_ES = {
    "push": "Empuje", "pull": "Tirón", "core": "Core", "legs": "Piernas",
    "balance": "Equilibrio", "bar": "Barra",
}

NAME_ES = {
    # push
    "wall_push_up": "Flexión en pared",
    "incline_push_up": "Flexión inclinada",
    "knee_push_up": "Flexión de rodillas",
    "push_up": "Flexión",
    "wide_push_up": "Flexión abierta",
    "diamond_push_up": "Flexión diamante",
    "decline_push_up": "Flexión declinada",
    "archer_push_up": "Flexión arquero",
    "pseudo_planche_push_up": "Flexión pseudo plancha",
    "one_arm_push_up": "Flexión a una mano",
    "bench_dip": "Fondo en banco",
    "dip": "Fondo",
    "weighted_dip": "Fondo lastrado",
    "ring_dip": "Fondo en anillas",
    "korean_dip": "Fondo coreano",
    # pull
    "dead_hang": "Colgado pasivo",
    "scapular_pull": "Retracción escapular",
    "australian_row": "Remo australiano",
    "negative_pull_up": "Dominada negativa",
    "chin_up": "Dominada supina",
    "pull_up": "Dominada",
    "chest_to_bar": "Dominada al pecho",
    "weighted_pull_up": "Dominada lastrada",
    "typewriter_pull_up": "Dominada máquina de escribir",
    "archer_pull_up": "Dominada arquero",
    "one_arm_negative": "Negativa a una mano",
    "assisted_one_arm_pull_up": "Dominada a una mano asistida",
    "one_arm_pull_up": "Dominada a una mano",
    # bar
    "explosive_pull_up": "Dominada explosiva",
    "transition_drill": "Ejercicio de transición",
    "kipping_muscle_up": "Muscle-up con impulso",
    "muscle_up": "Muscle-up",
    "strict_muscle_up": "Muscle-up estricto",
    "weighted_muscle_up": "Muscle-up lastrado",
    "ring_muscle_up": "Muscle-up en anillas",
    "hefesto": "Hefesto",
    "bar_360": "Dominada 360",
    # core
    "plank": "Plancha abdominal",
    "hollow_hold": "Hollow hold",
    "knee_raise": "Elevación de rodillas colgado",
    "leg_raise": "Elevación de piernas colgado",
    "toes_to_bar": "Pies a la barra",
    "l_sit": "L-sit",
    "ab_wheel": "Rueda abdominal",
    "dragon_flag": "Dragon flag",
    "v_sit": "V-sit",
    "manna": "Manna",
    "tuck_front_lever": "Front lever agrupado",
    "adv_tuck_front_lever": "Front lever agrupado avanzado",
    "straddle_front_lever": "Front lever con piernas abiertas",
    "half_front_lever": "Front lever a media lay",
    "front_lever": "Front lever",
    "front_lever_pull_up": "Dominada en front lever",
    "one_arm_front_lever": "Front lever a una mano",
    "skin_the_cat": "Skin the cat",
    "tuck_back_lever": "Back lever agrupado",
    "adv_tuck_back_lever": "Back lever agrupado avanzado",
    "straddle_back_lever": "Back lever con piernas abiertas",
    "back_lever": "Back lever",
    # balance
    "planche_lean": "Inclinación de plancha",
    "frog_stand": "Postura de la rana",
    "tuck_planche": "Plancha agrupada",
    "adv_tuck_planche": "Plancha agrupada avanzada",
    "straddle_planche": "Plancha con piernas abiertas",
    "full_planche": "Plancha completa",
    "planche_push_up": "Flexión en plancha",
    "wall_plank": "Plancha en pared",
    "chest_to_wall_handstand": "Pino de cara a la pared",
    "freestanding_handstand": "Pino libre",
    "wall_hspu": "Flexión en pino contra la pared",
    "freestanding_hspu": "Flexión en pino libre",
    "deficit_hspu": "Flexión en pino con déficit",
    "press_to_handstand": "Subida a pino",
    "one_arm_handstand": "Pino a una mano",
    "ninety_degree_push_up": "Flexión a 90 grados",
    "elbow_lever": "Palanca de codos",
    "vertical_flag": "Bandera vertical",
    "tuck_human_flag": "Bandera humana agrupada",
    "straddle_human_flag": "Bandera humana con piernas abiertas",
    "human_flag": "Bandera humana",
    # legs
    "squat": "Sentadilla",
    "split_squat": "Sentadilla split",
    "jump_squat": "Sentadilla con salto",
    "bulgarian_split_squat": "Sentadilla búlgara",
    "sissy_squat": "Sentadilla sissy",
    "shrimp_squat": "Sentadilla gamba",
    "pistol_squat": "Sentadilla pistol",
    "nordic_curl": "Curl nórdico",
}
