import re
from pathlib import Path


def test_action_case_has_default_branch():
    script_path = Path(__file__).resolve().parents[1] / "iam-deploy.sh"
    content = script_path.read_text(encoding="utf-8")

    match = re.search(r'case\s+"?\$ACTION"?\s+in(.*?)esac', content, re.S)
    assert match is not None, "Expected ACTION case block in iam-deploy.sh"

    action_case = match.group(1)
    assert re.search(r"\n\s*\*\)", action_case), "Expected default (*) branch in ACTION case"
