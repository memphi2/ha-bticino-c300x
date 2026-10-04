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
            "-o", str(binary),
        ],
        check=True, capture_output=True, text=True,
    )
    result = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
    documents = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(documents) == 5
    for index, document in enumerate(documents[:4]):
        caps = document["capabilities"]
        pcmu = bool(index % 2)
        maintenance = bool(index // 2)
        assert document["api_version"] == "1"
        assert document["device"] == {
            "id": "synthetic-id", "model": "C300X", "firmware": '1.7.19"test',
        }
        assert document["agent"]["self_update_supported"] is maintenance
        assert set(caps["maintenance"].values()) == {maintenance}
        assert caps["doorbell_video"] == {
            "supported": True, "stream_path": '/doorbell"video',
            "audio_stream_path": "/audio", "recorder_stream_path": "/recorder",
            "audio_codec": "PCMU/8000", "talkback_supported": True,
            "talkback_codec": "PCMU/8000" if pcmu else "speex/8000",
            "talkback_payload_type": 0 if pcmu else 97,
        }
        assert caps["locks"]["locks"] == [{"id": "front", "name": 'Front "door"\\entry'}]
        assert caps["activations"] == {"supported": True, "count": 3}
        assert caps["ringer"] == {
            "supported": True, "mute": True, "volume": True,
            "min_volume": 0, "max_volume": 10, "step": 1,
        }
        assert caps["system_metrics"] == {
            "supported": True, "cpu": True, "load": True, "memory": True,
            "temperature": True, "watch": True, "sample_interval_seconds": 30,
            "heartbeat_seconds": 600, "change_percent": 5,
        }
    for offset in (0, 2):
        speex = documents[offset]
        pcmu = documents[offset + 1]
        speex["capabilities"]["doorbell_video"].update(
            talkback_codec="PCMU/8000", talkback_payload_type=0,
        )
        assert speex == pcmu  # No unrelated capability changes with the codec.
    disabled = documents[4]["capabilities"]
    for feature in ("doorbell_video", "doorbell_call", "home_call", "activations", "memos", "system_metrics"):
        assert disabled[feature]["supported"] is False
    assert disabled["memos"]["watch"] is False
    assert disabled["system_metrics"]["watch"] is False
    assert disabled["answering_machine"]["messages"]["supported"] is False
    assert disabled["answering_machine"]["messages"]["watch"] is False


def test_capabilities_reads_running_video_codec_without_firmware_probe() -> None:
    root = Path(__file__).resolve().parents[1] / "native_agent" / "src"
    source = (root / "http.c").read_text()
    handler = source.split("static void api_capabilities(", 1)[1].split("static void api_state(", 1)[0]
    assert "c300x_video_status(runtime->video, &video_status);" in handler
    assert ".device_codec_pcmu = video_status.device_codec_pcmu" in handler
    assert "c300x_audio_codec_read_status" not in handler
    assert "c300x_audio_codec_device_is_pcmu" not in handler
    assert "c300x_capabilities_json(config, &context, body, C300X_LARGE_RESPONSE_SIZE)" in handler
