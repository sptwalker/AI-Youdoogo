"""ADR index synchronization guard — prevent index rot."""

from __future__ import annotations

import re
from pathlib import Path


def test_adr_index_references_all_numbered_adrs() -> None:
    """Assert docs/adr/README.md references exactly the ADRs that exist on disk.

    Scans docs/adr/*.md for NNNN-*.md files, extracts numbers from README.md,
    and asserts the two sets are equal — adding/removing an ADR without updating
    the index will fail this test.
    """
    # ponytail: 只校验编号一一对应（防漏登/悬挂），不校验列内容——列内容漂移由 code review 兜底。
    adr_dir = Path(__file__).parent.parent / "docs" / "adr"
    readme = adr_dir / "README.md"

    # Numbered ADR files on disk (exclude README.md itself)
    adr_files = sorted(adr_dir.glob("[0-9][0-9][0-9][0-9]-*.md"))
    disk_numbers = {f.stem[:4] for f in adr_files}

    # Numbers referenced in README.md (parse [0001](...) links and bare 0001-NNNN tokens)
    readme_text = readme.read_text(encoding="utf-8")
    referenced_numbers = set(re.findall(r"\b(\d{4})[-\)]", readme_text))

    assert disk_numbers == referenced_numbers, (
        f"ADR index out of sync. On disk: {sorted(disk_numbers)}, "
        f"in README: {sorted(referenced_numbers)}"
    )
