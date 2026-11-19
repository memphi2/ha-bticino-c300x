"""Compile the shared value/signature observer without device I/O."""

import subprocess
from pathlib import Path


def test_confirmed_state_classification_preserves_values_across_outages(tmp_path):
    source = tmp_path / "observer.c"
    source.write_text('''
#include <assert.h>
#include "setting_state.h"
int main(void) {
    struct c300x_setting_state state = {0};
    assert(c300x_setting_observe(&state, 0, UINT64_MAX) == C300X_SETTING_SAME);
    assert(!state.known);
    assert(c300x_setting_observe(&state, 1, 0) == C300X_SETTING_INITIAL);
    assert(c300x_setting_observe(&state, 1, 0) == C300X_SETTING_SAME);
    assert(c300x_setting_observe(&state, 0, UINT64_MAX) == C300X_SETTING_AVAILABILITY);
    assert(state.known && state.last_valid == 0 && !state.available);
    assert(c300x_setting_observe(&state, 1, 0) == C300X_SETTING_AVAILABILITY);
    assert(c300x_setting_observe(&state, 1, UINT64_MAX) == C300X_SETTING_CHANGED);
    assert(c300x_setting_observe(&state, 1, UINT64_MAX) == C300X_SETTING_SAME);
    assert(c300x_setting_observe(&state, 0, 0) == C300X_SETTING_AVAILABILITY);
    assert(state.last_valid == UINT64_MAX);
    assert(c300x_setting_observe(&state, 1, UINT64_C(1) << 40) == C300X_SETTING_CHANGED);
    assert(c300x_setting_observe(&state, 1, UINT64_C(1) << 40) == C300X_SETTING_SAME);
    return 0;
}
''')
    binary = tmp_path / "observer"
    root = Path(__file__).resolve().parents[1]
    subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-I", str(root / "native_agent/src"), str(source), "-o", str(binary)],
                   check=True, capture_output=True, text=True)
    subprocess.run([str(binary)], check=True)
