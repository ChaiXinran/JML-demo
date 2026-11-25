"""Single registry used by CLI and future web integration."""

from profiles.array_v1 import DEFAULT_PROFILE as ARRAY_PROFILE
from profiles.counter_v1 import DEFAULT_PROFILE as COUNTER_PROFILE
from profiles.network_v1 import DEFAULT_PROFILE as NETWORK_PROFILE


PROFILES = {
    NETWORK_PROFILE.name: NETWORK_PROFILE,
    COUNTER_PROFILE.name: COUNTER_PROFILE,
    ARRAY_PROFILE.name: ARRAY_PROFILE,
}
