"""Strip adapted Qt5 sources before identity hashes, never the source anchors."""

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest
from test_c100x_display_transaction import (
    assert_original,
    installed,
    rehash_source,
    run,
)
from test_c100x_display_transaction import tree as tree  # noqa: F401
from test_c100x_qml_adapter import ROOT, builder, strip_device_source


def test_all_generated_code_is_stripped_before_hashing_without_source_changes(tmp_path):
    source = ROOT / "device_qml"
    before = {path: path.read_bytes() for path in source.rglob("*") if path.is_file()}
    expected = {name: builder.adapt_page(name, (source / name).read_text()).encode()
                for name in builder.PAGES}
    for path in (source / "c100x").glob("*.qml"):
        expected[path.name] = path.read_bytes()
    for directory, prefix in ((source / "js", "js"), (source / "c100x/js", "js"),
                              (source / "c100x/hooks", "hooks")):
        for path in directory.rglob("*"):
            if path.is_file():
                expected[f"{prefix}/{path.relative_to(directory)}"] = path.read_bytes()
    builder.build(tmp_path)
    manifest = dict(line.split("  ", 1)[::-1]
                    for line in (tmp_path / "SHA256SUMS").read_text().splitlines())
    assert set(manifest) == set(expected)
    assert {path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*")
            if path.is_file()} == set(expected) | {"SHA256SUMS"}
    saved = 0
    for name, raw in expected.items():
        delivered = (tmp_path / name).read_bytes()
        if Path(name).suffix in {".qml", ".js"}:
            assert delivered == strip_device_source(raw.decode(), name=name).encode()
            assert delivered.decode().splitlines() == [line.strip() for line in raw.decode().splitlines()
                if line.strip() and not line.strip().startswith("//")]
            saved += len(raw) - len(delivered)
        else:
            assert delivered == raw  # Hook recipes retain their original bytes.
        assert manifest[name] == hashlib.sha256(delivered).hexdigest()
    assert saved > 0
    assert all(path.read_bytes() == content for path, content in before.items())


@pytest.mark.parametrize("relative", ["Alarm.qml", "c100x/C100XPage.qml", "c100x/js/c100x_ringer.js"])
@pytest.mark.parametrize("unsupported", ["/* unsafe block */\n", '"continued\\\nstring"\n', '"bad\x0bcharacter"\n'])
def test_unstrippable_input_never_publishes_manifest(tmp_path, relative, unsupported):
    source, output = tmp_path / "source", tmp_path / "output"
    shutil.copytree(ROOT / "device_qml", source)
    path = source / relative
    content = path.read_text() + unsupported
    path.write_text(content)
    with pytest.raises(ValueError, match="not supported"):
        builder.build(output, source)
    assert not (output / "SHA256SUMS").exists()
    assert path.read_text() == content


def test_stripped_c100x_ringer_preserves_preemption_protocol(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node required for the executable protocol harness")
    builder.build(tmp_path)
    result = subprocess.run([node, str(ROOT / "tests/fixtures/c100x_ringer_probe.js"),
                             str(tmp_path / "js/c100x_ringer.js")],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("action", ["apply", "restore"])
def test_unstripped_generation_can_upgrade_or_restore_with_stripped_package(tree, monkeypatch, action):
    source = tree[0] / "source"
    shutil.rmtree(source)
    # Recreate the pre-strip output while keeping the reviewed hook recipe.
    with monkeypatch.context() as patch:
        patch.setattr(builder, "strip_device_file", lambda *_: None)
        builder.build(source)
    before_manifest = (source / "SHA256SUMS").read_bytes()
    run(tree, "apply")
    old_release = installed(tree)
    old_page = (old_release / "C100XBridge.qml").read_bytes()
    shutil.rmtree(source)
    builder.build(source)
    assert (source / "SHA256SUMS").read_bytes() != before_manifest
    manifest = (source / "SHA256SUMS").read_bytes()
    rehash_source(source)
    assert (source / "SHA256SUMS").read_bytes() == manifest
    run(tree, action)
    if action == "apply":
        new_release = tree[1] / (".c100x-" + hashlib.sha256(manifest).hexdigest())
        assert (new_release / "C100XBridge.qml").read_bytes() == (source / "C100XBridge.qml").read_bytes()
        assert (old_release / "C100XBridge.qml").read_bytes() == old_page
        run(tree, "restore")
    assert_original(tree)
