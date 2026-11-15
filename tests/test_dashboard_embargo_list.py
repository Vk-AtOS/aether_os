"""KAN-154: the designer's embargo list must be the server's, or its 'pipeline will be blocked' warning lies."""
import pathlib
import re

from aether_os.core.policy.compliance import ComplianceEngine

DATA = pathlib.Path(__file__).resolve().parents[1] / "dashboard/src/components/project-designer/DesignerData.jsx"


def _codes(block):
    return set(re.findall(r"'([A-Z]{2})'", block))


def test_designer_embargo_set_equals_the_server_set_and_every_code_is_selectable():
    text = DATA.read_text()
    ui = _codes(re.search(r"export const EMBARGOED = new Set\(\[(.*?)\]\)", text).group(1))
    assert ui == set(ComplianceEngine.EMBARGOED_COUNTRIES)
    listed = set(re.findall(r"code:'([A-Z]{2})'", text))
    assert ui <= listed, "an embargoed country that cannot be picked can never show the warning"
