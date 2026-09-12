"""Single registry used by CLI and future web integration."""

from profiles.counter_v1 import DEFAULT_PROFILE as COUNTER_PROFILE
from profiles.network_v1 import DEFAULT_PROFILE as NETWORK_PROFILE


PROFILES = {
    NETWORK_PROFILE.name: NETWORK_PROFILE,
    COUNTER_PROFILE.name: COUNTER_PROFILE,
}
