"""Hook formulas (after sergebulaev/linkedin-skills hook extractor). Ids are stored in hook_patterns."""

HOOKS: dict[str, str] = {
    "F1": "A specific result with the number that proves it (only if the number is real)",
    "F2": "A mistake the author made, stated plainly",
    "F3": "A short scene: a specific moment, place or conversation",
    "F4": "A question the reader is already asking themselves",
    "F5": "A contrarian opinion the author actually holds, with the reason",
    "F6": "Something a customer or colleague said, quoted",
    "F7": "A before/after of how the author used to do something",
    "F8": "A direct ask for advice from the community",
    "F9": "A small surprising observation from their work",
    "F10": "A list of concrete things that worked (tools, steps), no hype",
    "F11": "The cost of a problem in time or money (only real figures)",
    "F12": "A decision they're stuck on, laid out honestly",
    "F13": "A teardown of how they did something step by step",
    "F14": "A myth in their field and what they saw instead",
    "F15": "A milestone with what it actually took",
    "F16": "An update on a project the community has seen before",
    "F17": "A resource they made that others can use",
    "F18": "A comparison between two approaches they tried",
    "F19": "A question to experts in the community with context",
    "F20": "Plain statement of the topic (no formula)",
}


def hook_list() -> str:
    return "\n".join(f"{k}: {v}" for k, v in HOOKS.items())


# Hooks that only work with a real experience behind them (a mistake, a scene, a quote, a result…).
NEEDS_STORY = frozenset({"F1", "F2", "F3", "F6", "F7", "F11", "F13", "F15", "F16", "F17", "F18"})
# Safe without a story: questions, opinions, observations.
NO_STORY_HOOKS = ("F4", "F5", "F8", "F9", "F14", "F19", "F12")
