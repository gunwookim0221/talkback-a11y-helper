from __future__ import annotations

from tools import validate_qa_frontend


def test_validation_script_main_passes():
    assert validate_qa_frontend.main() == 0
