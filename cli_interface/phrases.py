import random

_IDLE = [
    "Awaiting your command...",
    "Standing by, fully caffeinated...",
    "Listening intently...",
    "Ready when you are...",
    "Watching the cursor blink...",
    "Patience is a virtue. I have plenty.",
    "All systems nominal. Mostly.",
    "Perfectly idle. This is fine.",
    "Poised on the precipice of action...",
    "Hovering in a state of dignified readiness...",
    "Waiting with the focused calm of a cat near a fish.",
    "Fully present. Entirely unhurried.",
    "Silence before the storm of configuration...",
    "Refreshingly unbothered by the passage of time...",
    "Alert. Attentive. Absolutely not daydreaming.",
]

_NAVIGATING = [
    "Charting a course through your settings...",
    "Consulting the configuration oracle...",
    "Unfolding the menu parchment...",
    "Traversing the option landscape...",
    "Following the breadcrumbs...",
    "Descending into the preference architecture...",
    "Plotting the optimal route through the options...",
    "Reading the lay of the configurational land...",
    "The menu yields its secrets willingly...",
    "Stepping purposefully deeper into the hierarchy...",
    "Orientation confirmed. Proceeding inward.",
    "The path is clear. More or less.",
]

_LOADING = [
    "Summoning the appropriate modules...",
    "Persuading the dependencies to cooperate...",
    "Unboxing your preferences...",
    "Warming up the configuration engine...",
    "Conjuring settings from the void...",
    "Coaxing the relevant components into position...",
    "Dispatching a request to the inner workings...",
    "Marshalling resources with quiet authority...",
    "Gently waking the subsystems...",
    "Loading. Do not be alarmed.",
    "Negotiating with the runtime...",
    "Assembling the necessary ingredients...",
]

_APPLYING = [
    "Weaving your choices into reality...",
    "Committing this to the annals of config...",
    "Inscribing your preference in stone...",
    "Negotiating with the system...",
    "Making it so...",
    "Sealing the decision with quiet confidence...",
    "Writing your will into the configuration layer...",
    "Propagating the change through the relevant strata...",
    "The system acknowledges your authority...",
    "Carefully folding your preference into the state...",
    "Crystallising the choice...",
    "Done. Probably. Almost certainly.",
]

_THINKING = [
    "Pondering the implications...",
    "Cross-referencing the ancient tomes...",
    "Running the numbers through the vibes engine...",
    "Consulting an inner council of options...",
    "Deliberating with great thoroughness...",
    "Weighing options on the scales of reason...",
    "Performing a full cost-benefit analysis of vibes...",
    "Thinking about it very hard indeed...",
    "The gears are turning. Listen for them.",
    "Constructing a mental model of the situation...",
    "Processing. Cogitating. Being thoughtful.",
    "Holding the full context in mind simultaneously...",
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
