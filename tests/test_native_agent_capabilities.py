"""Execute the extracted capability serializer for both running codecs."""

import json
import subprocess
from pathlib import Path


def test_native_capabilities_contract(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1] / "native_agent"
    binary = tmp_path / "capabilities-test"
    subprocess.run(
        [
            "gcc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
            "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
            str(root / "test" / "capabilities_test.c"),
            str(root / "src" / "capabilities.c"),
            str(root / "src" / "json_util.c"),
            str(root / "src" / "json_parse.c"),
            "-o", str(binary),
        ],
        check=True, capture_output=True, text=True,
    )
    result = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
    documents = [json.loads(line) for line in result.stdout.splitlines()]
    c300 = subprocess.run([str(binary), "C300X"], check=True, capture_output=True, text=True)
    c300_documents = [json.loads(line) for line in c300.stdout.splitlines()]
    for index, document in enumerate(c300_documents[:4]):
        assert set(document["capabilities"]["maintenance"].values()) == {bool(index // 2)}
    assert len(documents) == 7
    # Only the C100X activation adds its member; the documents before it are unchanged.
    assert documents[6]["capabilities"].pop("c100x_display") == {"supported": True}
    assert documents[6] == documents[5]
    assert all("c100x_display" not in document["capabilities"] for document in documents[:6] + c300_documents[:6])
    for index, document in enumerate(documents[:4]):
        caps = document["capabilities"]
        pcmu = bool(index % 2)
        maintenance = bool(index // 2)
        assert document["api_version"] == "1"
        assert document["device"] == {
            # The model is the detected one, not the configured C300X.
            "id": "synthetic-id", "model": "C100X", "display_kind": "qt5_ondisk",
            "firmware": '1.7.19"test',
        }
        assert document["agent"]["self_update_supported"] is maintenance
        assert caps["memo_led"] is (not maintenance)
        assert document["agent"]["self_update_file_set_version"] == 7
        assert caps["https_callbacks"] is maintenance
        assert caps["maintenance"]["audio_codec_apply"] is False
        assert all(
            value is maintenance
            for key, value in caps["maintenance"].items()
            if key != "audio_codec_apply"
        )
        assert caps["doorbell_video"] == {
            "supported": True, "stream_path": '/doorbell"video',
            "audio_stream_path": "/audio", "recorder_stream_path": "/recorder",
            "audio_codec": "PCMU/8000", "talkback_supported": True,
            "talkback_codec": "PCMU/8000" if pcmu else "speex/8000",
            "talkback_payload_type": 0 if pcmu else 97,
        }
        assert caps["locks"]["locks"] == [{"id": "front", "name": 'Front "door"\\entry'}]
        assert caps["activations"] == {"supported": True, "count": 3}
        assert caps["announcements"] == {"supported": False}
        assert caps["ringer"] == {
            "supported": True, "mute": False, "volume": True,
            "min_volume": 0, "max_volume": 10, "step": 1,
        }
        assert caps["system_metrics"] == {
            "supported": True, "cpu": True, "load": True, "memory": True,
            "temperature": True, "watch": True, "sample_interval_seconds": 30,
            "heartbeat_seconds": 600, "change_percent": 5,
        }
        # A display without patchable files has no key beep, alerts or bridge.
        assert caps["touch_tone"] == {"supported": False, "requires_display_patch": True}
        assert caps["display_alerts"] is False
        assert caps["display_bridge"] == {"supported": False, "configurable": False, "configured": True}
    for offset in (0, 2):
        speex = documents[offset]
        pcmu = documents[offset + 1]
        speex["capabilities"]["doorbell_video"].update(
            talkback_codec="PCMU/8000", talkback_payload_type=0,
        )
        assert speex == pcmu  # No unrelated capability changes with the codec.
    disabled = documents[4]["capabilities"]
    assert disabled["announcements"] == {"supported": True}
    for feature in ("doorbell_video", "doorbell_call", "home_call", "activations", "memos", "system_metrics"):
        assert disabled[feature]["supported"] is False
    assert disabled["memos"]["watch"] is False
    assert disabled["system_metrics"]["watch"] is False
    assert disabled["answering_machine"]["messages"]["supported"] is False
    assert disabled["answering_machine"]["messages"]["watch"] is False
    patchable = documents[5]["capabilities"]
    assert patchable["touch_tone"] == {"supported": True, "requires_display_patch": True}
    assert patchable["display_alerts"] is True
    assert patchable["display_bridge"] == {"supported": True, "configurable": True, "configured": True}
    assert patchable["ringer"]["mute"] is True
    for feature in ("touch_tone", "display_alerts", "display_bridge", "ringer"):
        disabled[feature] = patchable[feature]
    assert disabled == patchable  # Nothing else follows the display.


def test_capabilities_reads_running_video_codec_without_firmware_probe() -> None:
    root = Path(__file__).resolve().parents[1] / "native_agent" / "src"
    source = (root / "http.c").read_text()
    handler = source.split("static void api_capabilities(", 1)[1].split("static void api_state(", 1)[0]
    assert "c300x_video_status(runtime->video, &video_status);" in handler
    assert ".device_codec_pcmu = video_status.device_codec_pcmu" in handler
    assert "c300x_audio_codec_read_status" not in handler
    assert "c300x_audio_codec_device_is_pcmu" not in handler
    assert "c300x_capabilities_json(config, &context, body, C300X_LARGE_RESPONSE_SIZE)" in handler
