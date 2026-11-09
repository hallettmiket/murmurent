"""The security guard movie: narration in the guard's own voice, plain cards checked against agents/security_guard.md, and the real exchange in transcript.md."""
from lib.agent_movie import AgentSpec, Exchange, Quote
from lib.draw import RED

SPEC = AgentSpec(
    agent="security_guard",
    title="The security guard",
    tagline="Checks what leaves your lab for passwords and patient data",
    colour=RED,
    icon="lock",
    intro=["I am the security guard. Before something leaves your lab, a change you are about to share or a "
           "file you are sending, I check it for passwords and patient information."],
    does=[
        Quote("Finds passwords, access keys and tokens in what you share.", "passwords"),
        Quote("Finds patient details: health numbers, record numbers, birth dates near names.", "record numbers"),
        Quote("Fails any change to your lab's original data.", "original data"),
        Quote("Also looks for social insurance numbers (Canada-specific; swap in your own country's identifiers).", "social insurance"),
    ],
    does_narration=[
        "I read what you are about to share and look for passwords, access keys and tokens. In a project that "
        "holds patient data, I also look for health card numbers, record numbers, social insurance numbers, and a birth date beside a name.",
        "I fail any change to your lab's original data, which stays as it was collected."],
    refuses=[
        Quote("Checks what leaves; the science is not its question.", "leaves"),
        Quote("Reports each problem and its fix; you make the change.", "fix"),
        Quote("Works offline, so the check itself sends nothing out.", "offline"),
    ],
    refuses_narration=[
        "My scope is what leaves the lab. Whether the science is right is not my question. When I block "
        "patient data in a protected project, I name the conscience, who reviews how people are described.",
        "I report each problem, where it is, and how to fix it; you make the change. I work offline, "
        "so the check itself sends nothing anywhere."],
    examples=[
        Exchange("1", ["A real run, on a practice folder with a fake password and an invented patient line. "
                       "The member is about to share it.",
                       "My first line says Blocked. Below it, each problem and its fix: a Slack "
                       "access key in a settings file, and a record number with a birth date in the notes. Both are "
                       "already in the project's saved history, so deleting them now is not enough."],
                 [("read the changes", True), ("passwords and keys", True), ("patient details", True), ("who can edit each file", True)]),
    ],
    prompt="ask the security guard to check my project before I share it",
    give="The folder or the change you are about to share. Say if it holds patient data.",
    verdicts="Clear, Concerns or Blocked, then each problem with where it is and its fix.",
    howto_narration=[
        "To use me, type to Claude Code: ask the security guard to check my project before I share it. Say if "
        "the project holds patient data.",
        "The first line is my answer: Clear, Concerns or Blocked. Blocked means fix what I list before "
        "anything leaves."],
    docs=["rules/data-storage.md"],
)
