import random

_IDLE = [
    "Awaiting your command...",
    "Standing by, fully caffeinated.",
    "Neither thinking nor not thinking.",
    "The void gazes back, patiently.",
    "One keystroke away from chaos.",
    "Genuinely unbothered. Almost concerningly so.",
    "Hovering at the event horizon of doing something.",
    "Stationary but fully alert.",
    "Watching the cursor blink. It's kind of relaxing.",
    "Patiently existing until further notice.",
    "All dressed up and ready to configure.",
    "Alert. Attentive. Absolutely not daydreaming.",
    "Idle, but ideologically committed.",
    "Waiting with the focused calm of a cat near a fish.",
    "Ready for whatever. Mostly whatever.",
]

_NAVIGATING = [
    "Into the labyrinth we go...",
    "Charting a course through the hierarchy.",
    "The options await your judgement, traveller.",
    "Somewhere in here is exactly what you need.",
    "Adventuring deeper into the configuration.",
    "Following the breadcrumbs with great confidence.",
    "Reading the lay of the configurational land.",
    "Orientation confirmed. Proceeding inward.",
    "The path is clear. More or less.",
    "The menu unfolds its secrets willingly.",
    "Stepping boldly into the next level.",
    "Descending. In a good way.",
]

_LOADING = [
    "Summoning the appropriate modules...",
    "Persuading the dependencies to cooperate.",
    "Gently waking the subsystems.",
    "Coaxing the relevant components into position.",
    "Loading. Do not be alarmed.",
    "Negotiating with the runtime.",
    "Assembling the necessary ingredients.",
    "Warming things up. Won't be a moment.",
    "Unboxing your preferences.",
    "Marshalling resources with quiet authority.",
    "Things are happening. Good things.",
    "Consulting the inner workings briefly.",
]

_APPLYING = [
    "Hammering your choice into the config with great care.",
    "Reality is being updated. Please hold.",
    "The deed is done. Or being done. Nearly done.",
    "Making it so.",
    "Reaching into the system with bureaucratic authority.",
    "Committing this to the annals of config.",
    "Sealing the decision with quiet confidence.",
    "Crystallising the choice.",
    "Writing your will into the configuration layer.",
    "Propagating the change with appropriate gravitas.",
    "Done. Probably. Almost certainly.",
    "The system has been informed of your decision.",
]

_THINKING = [
    "The council is deliberating.",
    "This is a big decision. Take your time.",
    "All options considered. Most of them, anyway.",
    "Pondering with genuine thoroughness.",
    "Running the numbers through the vibes engine.",
    "Holding the full context in mind simultaneously.",
    "Cross-referencing the ancient documentation.",
    "Processing. Cogitating. Being very thoughtful.",
    "The gears are turning. Listen for them.",
    "Constructing a complete mental model of the situation.",
    "Weighing options on the scales of reason and instinct.",
    "Thinking about it very hard indeed.",
]


def get_phrase(context: str = "idle") -> str:
    pool = {
        "idle":       _IDLE,
        "navigating": _NAVIGATING,
        "loading":    _LOADING,
        "applying":   _APPLYING,
        "thinking":   _THINKING,
    }.get(context, _IDLE)
    return random.choice(pool)
