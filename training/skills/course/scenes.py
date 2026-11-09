"""teacher course: a course across sessions, the COURSE mode of the teacher (issue #290)."""
from lib.draw import AMBER, TEAL
from lib.movie import Movie, Part, Quote

T_DIR = """
$ ls courses/permutation_tests
MISSION.md  PLAN.md  RESOURCES.md  learning-records  lessons  reference
$ ls courses/permutation_tests/lessons courses/permutation_tests/learning-records
lessons:
lesson_1.html
learning-records:
record_0.md
$ head -3 courses/permutation_tests/learning-records/record_0.md
# Record 0: baseline from the interview (2026-11-07)
No lesson has been taken yet. This record exists so the next session has
something to open with.
"""

MOVIE = Movie(
    key="course",
    title="Learning a subject with teacher course",
    tagline="A subject taught over weeks, remembering what you know",
    glyph="🎓",
    colour=AMBER,
    summary="The teacher's course mode: an interview for your goal, lessons you mark up, a quiz in each, and a record of what you have shown you know, so nothing is taught twice.",
    parts=[
        Part("title", ["This is the teacher's course mode. When a subject takes weeks rather than one sitting, you "
                       "type teacher course and the subject. It teaches you over several sessions, with lessons you "
                       "mark up and a record of what you have shown you know."]),
        Part("cards", chapter="The interview", heading="It interviews you first", source="skills/murmurent-course/SKILL.md",
             colour=TEAL,
             quotes=[Quote("It interviews you before it writes any lesson.", "interviewing"),
                     Quote("One question at a time, waiting for each answer.", "one question"),
                     Quote("Where you get stuck matters most.", "stuck")],
             narration=["It starts by interviewing you, one question at a time: what you will do with the subject, by "
                        "when, what you already have, and where you get stuck.",
                        "That last answer matters most, and the goal as a whole tells the course what to leave out. Your goal is "
                        "written down and re-read every session."]),
        Part("chat", chapter="A real first session", key="1", agent="teacher", colour=AMBER, who="Learner",
             chips=[("interview", True), ("write your goal", True), ("write lesson 1", True), ("reading list (later)", False)],
             narration=["Here is a real first session, with a practice learner whose answers were set in advance. The "
                        "goal: choose a permutation test, which shuffles the group labels, for colony sizes, and defend "
                        "it at lab meeting in three weeks.",
                        "The first lesson has a figure you play with: shuffle the labels and watch the gaps pile up. "
                        "In this practice run the reading had not come back yet; a real course finds its sources "
                        "through the bookworm before writing a lesson."]),
        Part("terminal", chapter="The course folder", heading="The course folder is its memory", transcript=T_DIR,
             title="The course folder", colour=TEAL,
             notes=[("Your goal, sources, lessons and learning records.", "records"),
                    ("A record notes what you showed you know.", "showed")],
             narration=["Everything lives in one course folder: your goal, the sources, the lessons and the learning "
                        "records. After each lesson, a record notes what you showed you know and what you fumbled, "
                        "so nothing you have mastered is taught twice. Each session picks the next smallest step "
                        "toward your goal, from what the records show you know."]),
        Part("cards", chapter="Later sessions", heading="Later sessions start with questions", source="skills/murmurent-course/SKILL.md",
             colour=AMBER,
             quotes=[Quote("Each session opens with two or three questions.", "two or three"),
                     Quote("The questions lean on what you fumbled.", "fumbled"),
                     Quote("Struggling to recall is how memory lasts.", "struggling")],
             narration=["Later sessions start with two or three questions from earlier lessons, weighted to what you "
                        "fumbled. Struggling to recall is where lasting memory comes from, so the teacher gives you "
                        "time to think."]),
        Part("howto", heading="How to use it",
             prompt="teacher course survival analysis",
             cards=[("Type it", "teacher course and the subject, in your own Claude Code session."),
                    ("Answer the interview", "What you will do with it, by when, where you are stuck."),
                    ("Mark up the lesson", "Mark the sentence that lost you, then take the quiz.")],
             docs=["skills/murmurent-course/SKILL.md", "agents/teacher.md"],
             narration=["To use it, type teacher course and the subject. Answer the interview. Open each lesson, mark "
                        "the sentence that lost you, and take the quiz; the next session starts from there. For one "
                        "method or one paper, teacher explain is enough."]),
    ],
)
