"""Use the validation engine shipped by the running Home Assistant version."""

from homeassistant.const import MAJOR_VERSION, MINOR_VERSION

# Support older HA versions without selecting a stray Probatio installation.
# check_typing.py selects this same branch for static analysis of each HA matrix.
HA_USES_PROBATIO = (MAJOR_VERSION, MINOR_VERSION) >= (2026, 9)

if HA_USES_PROBATIO:
    import probatio as vol
else:
    import voluptuous as vol

__all__ = ("vol",)
