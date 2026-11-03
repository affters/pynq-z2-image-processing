"""Offline verification of the Nov2 anonymous code/evidence package.

No camera, serial port, JTAG or MMIO is opened. Historical saved data is checked
against the included independent reference; this is not another hardware run.
"""
from collections import Counter
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import re

import verify_submission_package as legacy

ROOT = Path(__file__).resolve().parents[1]
FIXED = 'output/uart_demo/run_20261102_092320_utc_3e021f3a'
CAMERA = 'output/uart_camera/run_20261102_092416_utc_30b93c8f'
GUI = [('session_20261102_101032_950a05f0', 9291, {0:884, 1:8407}),
       ('session_20261102_111935_29c421e6', 750, {2:392, 3:211, 4:147})]


def main():
    # The retained checker proves the complete manifest, old comparison, both
    # archived firmware sets, prior batches and all selected raw GUI samples.
    captured = io.StringIO()
    llm = legacy.read('llm_logs/conversation_submission_anonymous_manifest.json')
    llm_counts = {'user': llm['user_messages'], 'assistant': llm['assistant_messages']}
    assert sum(llm_counts.values()) == llm['messages']
    with redirect_stdout(captured):
        legacy.main(expected_llm_counts=llm_counts)
    original = json.loads(captured.getvalue())
    fixed, _ = legacy.batch(FIXED)
    camera, _ = legacy.batch(CAMERA)
    assert camera['camera_test'] and camera['camera_capture_test'] and not camera['sd_used']
    assert not fixed['camera_test']
    union = set()
    for session, count, modes in GUI:
        d = legacy.read(f'output/uart_live/{session}/result.json')
        assert len(d['cases']) == count
        assert Counter(c['mode'] for c in d['cases']) == modes
        assert d['verified_modes'] == sorted(modes) and d['all_modes_verified'] is False
        assert d['camera_test'] and d['hardware_test'] and not d['linux_test'] and not d['sd_used']
        assert d['error'] is None and d['cleanup_errors'] == []
        assert all(c['exact_match'] and c['mismatch_pixels'] == 0 and c['max_abs_error'] == 0 for c in d['cases'])
        union.update(modes)
    assert union == set(range(5))
    selection = legacy.read('evidence/selection.json')
    cap = selection['bounded_gui_capture']
    d = legacy.read(f"output/uart_live/{cap['session']}/result.json")
    assert len(d['cases']) == 10 and d['verified_modes'] == [4]
    assert d['max_frames'] == 10 and d['frame_limit_reached'] is True
    assert d['all_modes_verified'] is False and d['camera_test'] and d['hardware_test']
    assert not d['linux_test'] and not d['sd_used']
    assert d['error'] is None and d['cleanup_errors'] == []
    assert all(c['mode'] == 4 and c['exact_match'] and c['mismatch_pixels'] == 0 for c in d['cases'])
    summary = legacy.read('output/test_resume_20261102.json')
    for rec in summary['results']:
        raw = (ROOT / rec['path']).read_bytes()
        assert legacy.sha(raw) == rec['sha256'] and len(raw) == rec['bytes']
        assert 'source_original_sha256' in rec
    private = summary['original_gui_screenshot']
    assert private['included'] is False and 'sha256' not in private and 'path' not in private
    assert 'source_original_sha256' in private
    assert summary['gui_total_frames'] == 10041 and summary['gui_union_verified_modes'] == list(range(5))
    assert not summary['gui_each_session_covers_all_modes']
    assert legacy.read('output/uart_demo/run_20261102_090956_utc_6d80ef15/result.json')['info_handshake_passed'] is False
    assert legacy.read('output/uart_demo/run_20261102_092320_utc_f9039813/result.json')['info_handshake_passed'] is True
    forbidden_original = 'output/uart_live/session_20261102_111935_29c421e6/gui_stopped_original.jpg'
    assert not (ROOT / forbidden_original).exists()
    for relative in legacy.read('manifest.json')['files']:
        path = ROOT / relative
        if path.suffix.lower() in {'.md','.txt','.json','.jsonl','.log','.py','.ps1','.tcl','.c','.h','.rpt','.xdc','.v','.sv','.s','.ld','.csv'}:
            text = path.read_text(encoding='utf-8-sig')
            # Possessive slash runs avoid a false match after backtracking
            # through JSON-escaped backslashes before an allowed [user] token.
            assert not re.search(r'C:[/\\]++Users[/\\]++(?!\[user\]|<local_user>)', text, flags=re.I), relative
    print(json.dumps({'all_passed': True, 'legacy_checks': original,
                     'nov2_fixed_pixels': 120216, 'nov2_real_camera_pixels': 120216,
                     'nov2_gui_summary_frames': [9291,750], 'nov2_gui_union_modes': sorted(union),
                     'nov2_each_session_all_modes': False, 'bounded_gui_frames': 10,
                     'gui_raw_samples_verified': len(selection['gui_samples']),
                     'private_original_gui_screenshot_excluded': True,
                     'anonymous_visible_message_count': llm['messages'],
                     'anonymous_visible_message_roles': llm_counts,
                     'historical_evidence_rechecked_offline': True,
                     'hardware_access_in_this_check': False}, indent=2))


if __name__ == '__main__':
    main()
