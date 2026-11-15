"""The business-rule grammar the generator understands (and nothing else).

Rule expressions are written by a model, so they are never pasted into generated code. They are
parsed here into terms joined by AND, and the generators emit their own text from the parsed parts:

    column  >= | <= | != | <> | == | = | > | <   number | column
    column  between  number  and  number
    column  in  ( number-or-'text' , ... )
    column  is not null

e.g. "salary > 0", "age >= 18 and age <= 65", "status in ('open', 'closed')", "end_date > start_date".
Anything else returns None (the rule is skipped, as before): all terms must parse or none is used.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

_ID = r"[A-Za-z_]\w*"
_NUM = r"-?\d+(?:\.\d+)?"
_STR = r"'[^'\\\"]*'"
_LIT = rf"(?:{_NUM}|{_STR})"
_CMP = re.compile(rf"^({_ID})\s*(>=|<=|!=|<>|==|=|>|<)\s*({_NUM}|{_ID})$")
_BETWEEN = re.compile(rf"\b({_ID})\s+between\s+({_NUM})\s+and\s+({_NUM})\b", re.I)
_IN = re.compile(rf"^({_ID})\s+in\s*\(\s*({_LIT}(?:\s*,\s*{_LIT})*)\s*\)$", re.I)
_NOTNULL = re.compile(rf"^({_ID})\s+is\s+not\s+null$", re.I)
_MAX_TERMS = 6
_SQL_OP = {"==": "=", "<>": "!="}
_PY_OP = {"=": "==", "<>": "!="}


@dataclass(frozen=True)
class Term:
    column: str
    op: str                  # SQL operator, or "IN" / "NOT NULL"
    value: str = ""          # number text, column name, or the raw literal list
    value_is_column: bool = False

    def identifiers(self) -> List[str]:
        return [self.column] + ([self.value] if self.value_is_column else [])

    def sql(self) -> str:
        if self.op == "NOT NULL":
            return f"{self.column} IS NOT NULL"
        if self.op == "IN":
            return f"{self.column} IN ({self.value})"
        return f"{self.column} {self.op} {self.value}"

    def python_check(self, var: str = "v") -> Optional[str]:
        """Python boolean expression over one field, or None for field-vs-field terms."""
        if self.value_is_column:
            return None
        if self.op == "NOT NULL":
            return f"{var} is not None"
        if self.op == "IN":
            return f"{var} in ({self.value},)"
        return f"{var} {_PY_OP.get(self.op, self.op)} {self.value}"


def _unwrap(part: str) -> str:
    """Drop ONE pair of parentheses that wrap the whole term ("(price >= 0)"), never an IN list's own."""
    part = part.strip()
    if part.startswith("(") and part.endswith(")"):
        depth = 0
        for i, ch in enumerate(part):
            depth += (ch == "(") - (ch == ")")
            if depth == 0 and i < len(part) - 1:
                return part  # the first "(" closes before the end: not a wrapper
        return part[1:-1].strip()
    return part


def parse_rule(expression: str) -> Optional[List[Term]]:
    text = _BETWEEN.sub(lambda m: f"{m[1]} >= {m[2]} and {m[1]} <= {m[3]}", str(expression).strip())
    parts = re.split(r"\s+and\s+", text, flags=re.I)
    if not text or len(parts) > _MAX_TERMS:
        return None
    terms: List[Term] = []
    for part in (_unwrap(p) for p in parts):
        if (m := _CMP.match(part)):
            op = _SQL_OP.get(m[2], m[2])
            terms.append(Term(m[1], op, m[3], value_is_column=not re.fullmatch(_NUM, m[3])))
        elif (m := _IN.match(part)):
            terms.append(Term(m[1], "IN", re.sub(r"\s*,\s*", ", ", m[2].strip())))
        elif (m := _NOTNULL.match(part)):
            terms.append(Term(m[1], "NOT NULL"))
        else:
            return None
    return terms
