"""The security guard movie: narration, plain cards checked against agents/security_guard.md, and the real exchange in transcript.md."""
from lib.agent_movie import AgentSpec, Exchange, Quote
from lib.draw import RED

SPEC = AgentSpec(
    agent="security_guard",
    title="The security guard",
    tagline="Checks what leaves your lab for passwords and patient data",
    colour=RED,
    icon="lock",
    intro=["This is the security guard. Before something leaves your lab, a change you are about to share or a "
           "file you are sending, it checks it for passwords and patient information."],
    does=[
        Quote("Finds passwords, access keys and tokens in what you share.", "passwords"),
        Quote("Finds patient details: health numbers, record numbers, birth dates near names.", "record numbers"),
        Quote("Fails any change to your lab's original data.", "original data"),
        Quote("It also looks for social insurance numbers.", "social insurance"),
    ],
    does_narration=[
        "It reads what you are about to share and looks for passwords, access keys and tokens. In a project that "
        "holds patient data, it also looks for health card numbers, record numbers, social insurance numbers, and a birth date beside a name.",
        "It fails any change to your lab's original data, which stays as it was collected."],
    refuses=[
        Quote("It checks what leaves; the adversary checks the science.", "adversary"),
        Quote("It reports each problem and its fix; you make the change.", "fix"),
        Quote("It works offline, so the check itself sends nothing out.", "offline"),
    ],
    refuses_narration=[
        "Its scope is what leaves the lab. The adversary checks the science, and the conscience checks how people "
        "are described.",
        "The guard reports each problem, where it is, and how to fix it; you make the change. It works offline, "
        "so the check itself sends nothing anywhere."],
    examples=[
        Exchange("1", ["A real run, on a practice folder with a fake password and an invented patient line. "
                       "The member is about to share it.",
                       "The first line says Blocked. Below it, each problem and its fix: a Slack "
                       "access key in a settings file, and a record number with a birth date in the notes. Both are "
                       "already in the project's saved history, so deleting them now is not enough."],
                 [("read the changes", True), ("passwords and keys", True), ("patient details", True), ("who can edit each file", True)]),
    ],
    prompt="ask the security guard to check my project before I share it",
    give="The folder or the change you are about to share. Say if it holds patient data.",
    verdicts="Clear, Concerns or Blocked, then each problem with where it is and its fix.",
    howto_narration=[
        "To use it, type to Claude Code: ask the security guard to check my project before I share it. Say if "
        "the project holds patient data.",
        "The first line is the answer: Clear, Concerns or Blocked. Blocked means fix what it lists before "
        "anything leaves."],
    docs=["rules/data-storage.md"],
)
