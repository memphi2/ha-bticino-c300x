"""Execute only original caps-building instructions, not a media pipeline.

Optional private firmware + Unicorn check. All GStreamer calls are intercepted;
this proves argument flow, not encoder negotiation or hardware operation.
"""

import hashlib
import os
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("width,height", [(400, 288), (320, 240), (480, 288), (640, 384), (720, 432)])
def test_original_fw306_passes_low_dimensions_to_separate_caps(width, height):
    unicorn = pytest.importorskip("unicorn")
    from unicorn import arm_const as arm

    rootfs = Path(os.environ.get(
        "C300X_QT5_FIRMWARE", ROOT.parent / "c300x-fwpatch/work/rootfs-3.0.6"))
    binary = rootfs / "home/bticino/bin/bt_av_media"
    if not binary.is_file():
        pytest.skip("private original firmware not supplied")
    data = binary.read_bytes()
    assert hashlib.sha256(data).hexdigest() == "39816d1e8d0cd40a39d389d683d541d71e71c216c688dac63e9a111c02081e4b"
    machine = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_THUMB)
    machine.mem_map(0, 0x60000)
    machine.mem_write(0, data)
    stack, instance, fraction_type = 0x41000, 0x50000, 0x51000
    def word(value):
        return struct.pack("<I", value)

    machine.reg_write(arm.UC_ARM_REG_SP, stack)
    machine.reg_write(arm.UC_ARM_REG_R4, instance)
    machine.reg_write(arm.UC_ARM_REG_R10, fraction_type)
    machine.mem_write(fraction_type, word(0xC4))
    machine.mem_write(instance + 0x24, word(800) + word(480))
    # dc62..dc70 copy entry-stack +48/+52 to local +0x64/+0x68.
    # 191d2..191f2 copy the parsed width/height at object +0x4c/+0x50
    # into those entry-stack slots. No crop getter supplies these values.
    machine.mem_write(stack + 0x60, word(10) + word(width) + word(height))
    caps = []

    def string(address):
        return bytes(machine.mem_read(address, 128)).split(b"\0", 1)[0].decode()

    def intercept(uc, address, _size, _data):
        if address == 0x3C90:  # gst_caps_new_simple
            values = [uc.reg_read(register) for register in
                      (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1,
                       arm.UC_ARM_REG_R2, arm.UC_ARM_REG_R3)]
            values += list(struct.unpack("<12I", uc.mem_read(stack, 48)))
            assert string(values[0]) == "video/x-raw"
            fields, index = {}, 1
            while values[index]:
                name, kind = string(values[index]), values[index + 1]
                count = 2 if kind == 0xC4 else 1
                field = values[index + 2:index + 2 + count]
                fields[name] = string(field[0]) if kind == 64 else field
                index += 2 + count
            caps.append(fields)
            if len(caps) == 2:
                uc.emu_stop()
                return
            uc.reg_write(arm.UC_ARM_REG_R0, 0x52000)
        elif address == 0x3C30:  # gst_element_factory_make
            uc.reg_write(arm.UC_ARM_REG_R0, 0x53000)
        elif address not in (0x376C, 0x414C, 0x386C):
            return
        uc.reg_write(arm.UC_ARM_REG_PC, uc.reg_read(arm.UC_ARM_REG_LR))

    machine.hook_add(unicorn.UC_HOOK_CODE, intercept)
    machine.emu_start(0xEC66 | 1, 0xED2C, count=1000)
    assert len(caps) == 2
    assert (caps[0]["width"], caps[0]["height"]) == ([800], [480])
    assert (caps[1]["width"], caps[1]["height"]) == ([width], [height])
    assert caps[1]["format"] == "I420"

    plugin = (rootfs / "usr/lib/gstreamer-1.0/libgstvpu.so").read_bytes()
    assert hashlib.sha256(plugin).hexdigest() == "56b5acf666de668f3babc32af0f6fbce8731d5586aab58e2eb0abdffdce53692"
    assert b"width = (int) [ 64, 1920, 8 ], height = (int) [ 64, 1088, 8 ]" in plugin
    assert 64 <= width <= 720 and 64 <= height <= 576 and width % 16 == height % 16 == 0
