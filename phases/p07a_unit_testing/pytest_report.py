"""Read a pytest run from its JUnit XML report and exit code, not from words in its output (KAN-250).

p07a counted tests by searching the output for "passed" / "failed". When the generated app crashed on import
(routers/crud.py NameError 'schemas', runs 187dcfc3 + d7395a95) pytest stopped at collection: the output had neither
word, so the run read as "0 tests" with no reason and s06 said only "pytest collected or ran nothing". Here a
collection error is reported as "collection error: <first error line>".

pytest exit codes: 0 all passed, 1 some tests failed, 2 interrupted (collection errors), 3 internal error,
4 usage error, 5 no tests collected.
"""
from __future__ import annotations

import logging
import re
# stdlib parser on purpose: a report with a DTD is refused before parsing, in _from_junit.
import xml.etree.ElementTree as ET  # nosec B405
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_EXIT_MEANING = {2: "pytest was interrupted (collection errors)", 3: "pytest internal error",
                 4: "pytest usage error", 5: "no tests collected"}


def first_error(text: str) -> str:
    """The line that says what broke: pytest's first `E   ...` line, else the last `SomethingError: ...` line."""
    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    e_lines = [ln[1:].strip() for ln in lines if ln.startswith("E ") and ln[1:].strip()]
    if e_lines:
        named = [ln for ln in e_lines if re.search(r"\w*(Error|Exception)\b", ln)]
        return (named[0] if named else e_lines[0])[:300]
    errs = [ln.strip() for ln in lines if re.search(r"\b\w*(Error|Exception): ", ln)]
    if errs:
        return errs[-1][:300]
    tail = [ln.strip() for ln in lines if ln.strip()]
    return (tail[-1] if tail else "no output")[:300]


MAX_REPORT = 5_000_000  # callers read at most this many bytes (safe_fs.read_text_or_none)


def _from_junit(xml_text: str) -> Optional[Dict[str, Any]]:
    # Generated code runs in the same run dir and could rewrite the report: pytest never writes a DTD, so one (the
    # carrier of entity-expansion and external-entity attacks) or an oversized file means "do not trust it".
    if len(xml_text) > MAX_REPORT or "<!DOCTYPE" in xml_text or "<!ENTITY" in xml_text:
        logger.warning("[p07a] junit report refused (DTD or oversized); reading the pytest output instead")
        return None
    try:
        root = ET.fromstring(xml_text)  # nosec B314
    except ET.ParseError as exc:
        logger.warning("[p07a] junit report unreadable: %s", exc)
        return None
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    passed = failed = errored = skipped = 0
    collection: Optional[str] = None
    for case in (c for s in suites for c in s.iter("testcase")):
        err = case.find("error")
        fail = case.find("failure")
        if err is not None and "collection" in (err.get("message") or "").lower():
            collection = collection or first_error(err.text or err.get("message") or "")
        elif err is not None:
            errored += 1
        elif fail is not None:
            failed += 1
        elif case.find("skipped") is not None:
            skipped += 1
        else:
            passed += 1
    return {"passed": passed, "failed": failed, "error_count": errored, "skipped": skipped,
            "collection_error": collection}


def _from_output(output: str) -> Dict[str, Any]:
    """Fallback when no JUnit report was written: the final summary line, e.g. "3 passed, 1 failed, 2 errors"."""
    def _n(word: str) -> int:
        m = re.findall(rf"(\d+) {word}", output)
        return int(m[-1]) if m else 0
    collection = None
    if "ERROR collecting" in output or "errors during collection" in output:
        start = output.find("ERROR collecting")
        collection = first_error(output[start:] if start >= 0 else output)
    return {"passed": _n("passed"), "failed": _n("failed"), "error_count": _n("errors?"), "skipped": _n("skipped"),
            "collection_error": collection}


def parse_run(returncode: int, output: str, junit_xml: Optional[str]) -> Dict[str, Any]:
    """{passed, failed, error_count, skipped, collected, collection_error} for one pytest run.

    failed counts failing AND erroring tests (an error in a fixture is a failed test); collection_error is set
    whenever the tests could not all be collected, and then no test result is trusted.
    """
    out = (_from_junit(junit_xml) if junit_xml else None) or _from_output(output or "")
    m = re.findall(r"collected (\d+) items?", output or "")
    out["collected"] = int(m[-1]) if m else out["passed"] + out["failed"] + out["error_count"] + out["skipped"]
    out["failed"] += out.pop("error_count")
    if returncode in _EXIT_MEANING and not out["collection_error"]:
        out["collection_error"] = (_EXIT_MEANING[returncode] if returncode == 5
                                   else f"{_EXIT_MEANING[returncode]}: {first_error(output)}")
    if out["collection_error"]:
        # Tests that ran next to a collection error do not stand for the app: the module that failed has none.
        out["passed"] = out["failed"] = 0
    return out
