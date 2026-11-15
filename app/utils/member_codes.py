"""Member ID numbering: MEM-0001, MEM-0002, ...

The next ID is the highest MEM number in use plus one. Codes outside the sequence (for
example TEST-0001 for a temporary test member) are ignored, so they never change it.
"""
import re

from sqlalchemy.orm import Session

MEM_CODE = re.compile(r"^MEM-?(\d+)$", re.IGNORECASE)


def next_member_code(db: Session) -> str:
    from app.models import Member

    highest = 0
    for (code,) in db.query(Member.member_code).all():
        match = MEM_CODE.match(str(code or "").strip())
        if match:
            highest = max(highest, int(match.group(1)))
    return f"MEM-{highest + 1:04d}"
