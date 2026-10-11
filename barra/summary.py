"""What happened in this session, in sentences a person would actually read.

The report this replaces was a metric dump: every rep listed with its
robustness class in capitals, `r1 - Transition through the bar 0.33 s
(INVARIANT) - Concentric duration 3.50 s (INVARIANT)`. Every number in it was
correct and none of it answered the question the athlete opened the app to ask,
which is "how did that go?".

So the numbers stay - they are on the rep cards, where someone looking for them
will find them - and this module says what they amount to. The rules it works
under are the ones the rest of the project works under:

  * Never a claim the measurement does not support. No "your transition is
    improving" from one session, no cause attributed to a number.
  * A refusal is a result. A clip that produced nothing gets a description of
    what stopped it and what to do differently, not an apology.
  * Say which part is weakest, because that is the one sentence of a report
    anybody acts on.
"""
from __future__ import annotations

from . import i18n

# The alpha is Spanish (2026-10-11). This text is the fallback when no model
# writes the report, so it is the one the phone shows on a bad day.
BAND_WORD = {
    "strong": "fuerte",
    "solid": "sólida",
    "shaky": "irregular",
    "broken down": "desmoronándose",
    "unmeasured": "sin medir",
}

# Plain names for the score's parts. The component keys are internal; these are
# what the sentence says. Not "fluidez del tirón": the same component scores a
# push-up, and a push-up has no pull.
PART = {
    "range": "el recorrido",
    "control": "el control de la bajada",
    "smoothness": "la fluidez durante la repetición",
}

# (singular, plural, feminine) per movement key, for agreement in Spanish.
NOUN = {
    "muscle_up": ("muscle-up", "muscle-ups", False),
    "pull_up": ("dominada", "dominadas", True),
    "dip": ("fondo", "fondos", False),
    "push_up": ("flexión", "flexiones", True),
    "squat": ("sentadilla", "sentadillas", True),
    "knee_raise": ("elevación de rodillas", "elevaciones de rodillas", True),
    "front_lever": ("front lever", "front levers", False),
    "planche": ("plancha", "planchas", True),
    "pistol_squat": ("sentadilla pistol", "sentadillas pistol", True),
    "split_squat": ("sentadilla split", "sentadillas split", True),
    "bulgarian_split_squat": ("sentadilla búlgara", "sentadillas búlgaras", True),
}
_REP = ("repetición", "repeticiones", True)

# What to film differently, per reason the clip failed. Keyed by a distinctive
# fragment of the ENGLISH blocker - the text barra wrote and the trace keeps -
# so the match does not depend on the translation.
FILMING_ADVICE = [
    ("out of frame", "Inclina la cámara hacia arriba o aléjate para que las manos "
                     "queden dentro del plano toda la serie: son la referencia con "
                     "la que se mide todo lo demás."),
    ("fixed bar", "Empieza a grabar cuando ya estés en la barra y para antes de "
                  "bajarte. Moverse por la estructura se mide como parte del "
                  "movimiento."),
    ("around the rig", "Empieza a grabar cuando ya estés en la barra y para antes "
                       "de bajarte. Moverse por la estructura se mide como parte "
                       "del movimiento."),
    ("not on anything fixed", "Empieza a grabar cuando ya estés en la barra. Ir y "
                              "volver de la estructura se mide como parte del "
                              "movimiento."),
    ("hold", "Barra cuenta repeticiones, así que un mantenimiento no tiene nada que "
             "contar. Graba una serie de repeticiones."),
    ("turnaround", "Que se vea la repetición entera en el encuadre, de arriba "
                   "abajo. Un cambio de dirección que se sale del encuadre no se "
                   "puede cronometrar."),
    ("interpolated", "Más luz, o un móvil más estable. Demasiados fotogramas se "
                     "adivinaron en vez de verse."),
]


def _sentence(text: str) -> str:
    """Notes are written as fragments so they can be listed under a heading;
    dropped into running prose they need a capital and a full stop."""
    text = (text or "").strip()
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text[-1] in ".!?" else text + "."


def _es(text: str) -> str:
    return i18n.localize_text(text) if isinstance(text, str) else text


def _pct(x: float) -> str:
    return f"{x:.0%}".replace("%", " %")


def _num(x: float, fmt: str = ".1f") -> str:
    return format(x, fmt).replace(".", ",")


def _noun(payload: dict) -> tuple[str, str, bool]:
    key = (payload.get("detected") or {}).get("exercise") or payload.get("exercise") or ""
    if key in NOUN:
        return NOUN[key]
    label = _es((payload.get("detected") or {}).get("label") or key.replace("_", " "))
    return ((label or "movimiento").lower(),) * 2 + (False,)


def _count(n: int, noun: tuple[str, str, bool], adjective: str = "") -> str:
    """"4 muscle-ups verificados", "1 dominada verificada"."""
    word = noun[0] if n == 1 else noun[1]
    if not adjective:
        return f"{n} {word}"
    ending = ("a" if noun[2] else "o") + ("" if n == 1 else "s")
    return f"{n} {word} {adjective}{ending}"


def _advice(blockers: list[str]) -> str:
    """Advice for the FIRST blocker before any other.

    A clip usually fails for more than one reason, and the pipeline reports
    them in the order it hit them. Searching all of them at once lets a later,
    incidental blocker win: one clip whose real problem was the athlete walking
    around the rig was told to keep the turnaround in frame, because a
    secondary blocker happened to contain the word.
    """
    ordered = [b.lower() for b in blockers if b] or [""]
    for haystack in (ordered[0], " ".join(ordered)):
        for needle, text in FILMING_ADVICE:
            if needle in haystack:
                return text
    return ("Graba una serie desde un punto fijo, con todo el movimiento dentro "
            "del plano de principio a fin.")


def _spread(reps: list[dict]) -> str:
    """How the set held together. Only said when there are enough reps for the
    comparison to mean anything - two reps have a difference, not a trend."""
    times = []
    for r in reps:
        try:
            times.append(float(str(r.get("total_s")).replace(",", ".").split()[0]))
        except (TypeError, ValueError, IndexError):
            continue
    if len(times) < 3:
        return ""
    first, last = times[0], times[-1]
    if max(times) <= 0:
        return ""
    drift = (last - first) / first if first > 0 else 0.0
    if abs(drift) < 0.15:
        return (f"Los tiempos por repetición se mantuvieron estables "
                f"({_num(min(times))}-{_num(max(times))} s).")
    if drift > 0:
        return (f"Las repeticiones se fueron ralentizando: de {_num(first)} s al "
                f"principio a {_num(last)} s al final, un {_pct(drift)} más.")
    return f"Las repeticiones se aceleraron a lo largo de la serie: de {_num(first)} s a {_num(last)} s."


def _weakest(reps: list[dict]) -> str:
    """The lowest-scoring part of the movement, averaged over the scored reps,
    quoted with the measurement that produced it."""
    totals: dict[str, list[float]] = {}
    why: dict[str, str] = {}
    for r in reps:
        if r.get("score") is None:
            continue
        for c in r.get("components") or []:
            name = c.get("name")
            if name is None or c.get("value") is None:
                continue
            totals.setdefault(name, []).append(float(c["value"]))
            why.setdefault(name, str(c.get("why") or ""))
    if not totals:
        return ""
    means = {k: sum(v) / len(v) for k, v in totals.items()}
    worst = min(means, key=means.get)
    best = max(means, key=means.get)
    if means[worst] >= 0.95:
        return "Todas las partes del movimiento puntuaron cerca del máximo."
    line = f"Lo más flojo fue {PART.get(worst, worst)}, al {_pct(means[worst])}"
    if why.get(worst):
        line += f" ({_es(why[worst])})"
    if best != worst:
        line += f"; lo mejor, {PART.get(best, best)}, al {_pct(means[best])}"
    return line + "."


def _unmeasured(reps: list[dict]) -> str:
    """Reps that were found but could not be scored, and how many. Silence here
    would let a set of six report a score built from two."""
    missing = [r for r in reps if r.get("score") is None]
    if not missing:
        return ""
    notes = [_es(r.get("scoreNote")) for r in missing if r.get("scoreNote")]
    n = len(missing)
    line = (f"{_count(n, _REP)} no se pudo puntuar y queda fuera de la cifra de arriba"
            if n == 1 else
            f"{_count(n, _REP)} no se pudieron puntuar y quedan fuera de la cifra de arriba")
    return line + (f": {notes[0][:1].lower() + notes[0][1:]}" if notes else "") + "."


def describe(payload: dict) -> tuple[str, str]:
    """(headline, narrative) for one analysed clip."""
    reps = payload.get("reps") or []
    n = int(payload.get("n_reps") or 0)
    noun = _noun(payload)
    blockers = [str(b) for b in (payload.get("blockers") or [])]
    first = _sentence(_es(blockers[0])) if blockers else ""
    score = payload.get("sessionScore")
    band = str(payload.get("sessionBand") or "unmeasured")
    band_word = BAND_WORD.get(band, band)

    # ---- nothing countable -------------------------------------------------
    if n == 0:
        detected = payload.get("detected") or {}
        if not detected.get("exercise") or detected.get("exercise") == "unknown":
            headline = "Ningún ejercicio que barra pueda medir"
            opening = "Barra no pudo saber qué se ve en este vídeo." + (f" {first}" if first else "")
        else:
            headline = f"{noun[0].capitalize()}: nada que contar"
            candidates = int(payload.get("n_candidates") or 0)
            opening = (
                f"Reconocido como {noun[0]}"
                + (f" y con {_count(candidates, ('posible repetición', 'posibles repeticiones', True))}, "
                   "pero ninguna pasó las comprobaciones. " if candidates else
                   ", pero no se pudo separar ninguna repetición. ")
                + first
            ).strip()
        return headline, " ".join(x for x in [opening, _advice(blockers)] if x)

    # ---- a measured set ----------------------------------------------------
    parts: list[str] = []
    trim = payload.get("trim") or {}
    duration = payload.get("duration_s")
    working = None
    if trim.get("startS") is not None and trim.get("endS") is not None:
        working = float(trim["endS"]) - float(trim["startS"])

    # "verificadas" is earned, not decorative: it means barra measured the rep.
    # A set where nothing could be scored is a set of found reps, not verified
    # ones - "19 flexiones verificadas" above "ninguna se pudo puntuar" was a
    # contradiction inside one paragraph. See docs/MARKET.md.
    verified = sum(1 for r in reps if r.get("score") is not None)
    opening = _count(n, noun, "verificad" if verified else "encontrad")
    if working:
        opening += f" en una serie de trabajo de {working:.0f} segundos"
        if duration and float(duration) - working > 2.0:
            opening += f", recortada de {float(duration):.0f} segundos de vídeo"
    parts.append(opening + ".")

    if score is None:
        headline = f"{_count(n, noun)}: ninguna verificada"
        note = next((_es(r.get("scoreNote")) for r in reps if r.get("scoreNote")), "")
        parts.append("No se pudo puntuar ninguna, así que esta sesión no tiene cifra "
                     "y ninguna de estas repeticiones cuenta para una progresión."
                     + (f" {_sentence(note)}" if note else ""))
    elif n < 3:
        headline = f"{_count(n, noun, 'verificad')}, {band_word}"
        parts.append(f"Puntuación: {int(score)} sobre 100 ({band_word}). Hacen falta "
                     "tres repeticiones para que la mediana de una sesión signifique "
                     "algo, así que tómalo como una sola observación y no como una sesión.")
    else:
        headline = f"{_count(n, noun, 'verificad')}, {band_word}"
        parts.append(f"Puntuación: {int(score)} sobre 100 ({band_word}).")

    # _unmeasured is suppressed when nothing scored at all: the line above has
    # already said so, and repeating it points at a number that does not exist.
    extras = [_weakest(reps), _spread(reps)]
    if verified:
        extras.append(_unmeasured(reps))
    for extra in extras:
        if extra:
            parts.append(extra)

    if blockers:
        parts.append("También: " + first)

    return headline, " ".join(parts)
