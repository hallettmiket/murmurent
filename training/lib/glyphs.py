"""Each agent's glyph, as the seminar slides mark them (blacksmith ⚒, bookworm 📚, artist 🎨,
adversary ⚔), extended to the rest of the commons. In its own module so the front page and the
hook can read it without the drawing libraries."""

GLYPHS = {"oracle": "🔮", "lab_oracle": "📜", "bookworm": "📚", "blacksmith": "⚒️", "adversary": "⚔️",
          "artist": "🎨", "teacher": "🎓", "conscience": "🧭", "scribe": "✒️", "docent": "🗺️",
          "lawyer": "⚖️", "millwright": "🔧", "centre_millwright": "🏗️", "judge": "🧮",
          "registrar": "🗂️", "security_guard": "🛡️", "clerk": "📋"}
MEMBER_GLYPH = "🧑‍🔬"


def glyph_of(agent: str) -> str:
    return GLYPHS.get(agent, "🤖")
