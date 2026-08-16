"""`/api/wired*` request/response shapes (ADR-0014).

Every constraint here is an anchored allow-list rather than a deny-list, the
same discipline `schemas/hotspot.py` and `schemas/serial.py` follow: the values
in this module become elements of an `nmcli` argv, and the only safe question to
ask of them is "is this one of the things I expect", never "does this look
dangerous".

Notably shorter than the hotspot's equivalent, and the whole difference is the
absence of a secret. There is no `SecretStr` here, no write-only field and no
"omit to keep the stored value" mechanism, because a wired share has no
passphrase — the cable is the credential.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.backend.schemas.hotspot import INTERFACE_PATTERN, validate_gateway_cidr


class WiredShareConfigRequest(BaseModel):
    """`PUT /api/wired` body — a full replace, not a merge.

    Deliberately not a PATCH, for the same reason the hotspot's is not: a
    partial body would let a request that says nothing about `enabled` inherit a
    previous value, and `enabled` here decides whether the Pi's uplink port is
    about to stop being an uplink.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=False, description="Whether wired sharing should be running after this call"
    )
    interface: str | None = Field(
        default=None,
        pattern=INTERFACE_PATTERN,
        description=(
            "Ethernet port to share; omit to choose an unused one automatically. On a "
            "single-port Pi there is no unused one, so this must name the port explicitly"
        ),
    )
    gateway_cidr: str | None = Field(
        default=None,
        description=(
            "The Pi's address on the shared network; omit to use the configured default. "
            "Must not overlap the hotspot's range"
        ),
    )
    confirm_uplink_loss: bool = Field(
        default=False,
        description=(
            "Acknowledges that the chosen port currently carries a connection which "
            "sharing it will drop"
        ),
    )

    @field_validator("gateway_cidr")
    @classmethod
    def _check_gateway_cidr(cls, gateway_cidr: str | None) -> str | None:
        if gateway_cidr is None:
            return None
        return validate_gateway_cidr(gateway_cidr)


class WiredShareActivationRequest(BaseModel):
    """Body shared by `POST /api/wired/enable` and `/disable`.

    These exist as their own routes so the UI's on/off switch never resends the
    whole configuration.
    """

    model_config = ConfigDict(extra="forbid")

    confirm_uplink_loss: bool = Field(
        default=False,
        description="Acknowledges that this call will drop a connection currently in use",
    )


WiredShareWarning = Literal[
    "console_password_missing",
    "advertised_host_overrides_gateway",
    "shares_uplink_port",
    "no_carrier",
    "nm_unavailable",
]
"""Non-fatal conditions worth showing the operator. Warnings never block a read.

`no_carrier` is the wired-only one and the most useful in practice: nothing is
plugged into the port, which is by far the commonest reason a share that came up
correctly has no clients on it.
"""


class WiredShareErrorSummary(BaseModel):
    """The last control failure, kept so the UI can explain a share that is not up."""

    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    ts: int = Field(description="Unix ms")
    stderr_tail: str | None = Field(
        default=None,
        description=(
            "Tail of the failing command's output. The only thing that says why "
            "NetworkManager refused"
        ),
    )


class WiredShareStateResponse(BaseModel):
    """`GET /api/wired` and every mutator's success body.

    Never 503s: a host that cannot do any of this answers 200 with
    `available: false`, matching how `GET /api/hotspot` already degrades. A
    client can therefore always render *something*.
    """

    model_config = ConfigDict(frozen=True)

    available: bool = Field(description="Whether wired-sharing control works on this host")
    control_enabled: bool = Field(
        description=(
            "Whether host-network control is switched on. The same switch the hotspot "
            "uses — it grants the one capability both features need"
        )
    )
    console_password_set: bool = Field(description="Whether a console password has been set")
    configured: bool = Field(description="Whether a wired-sharing profile exists")
    enabled: bool = Field(description="Whether the profile is set to come up on boot")
    active: bool = Field(description="Whether wired sharing is running right now")
    interface: str | None = None
    gateway_address: str | None = Field(
        default=None,
        description="The address a cabled machine should point Sentinel at, e.g. 10.10.10.1",
    )
    gateway_cidr: str | None = None
    carrier_up: bool | None = Field(
        default=None,
        description=(
            "Whether a cable is plugged into the shared port. Null means the host did "
            "not report it — which is not the same as 'unplugged'"
        ),
    )
    uplink_interface_is_share_interface: bool = Field(
        default=False,
        description="True when sharing this port would drop (or has dropped) the Pi's own link",
    )
    pending_confirmation: bool = Field(
        default=False,
        description="A change is awaiting confirmation and will roll back without it",
    )
    confirm_deadline_ms: int | None = Field(
        default=None, description="Unix ms by which POST /api/wired/confirm must arrive"
    )
    last_error: WiredShareErrorSummary | None = None
    warnings: tuple[WiredShareWarning, ...] = ()
    generated_at: int = Field(description="Unix ms")


class WiredInterfaceItem(BaseModel):
    """One selectable Ethernet port in `GET /api/wired/interfaces`."""

    model_config = ConfigDict(frozen=True)

    name: str
    mac_address: str | None = None
    state: str
    ipv4_addresses: tuple[str, ...] = ()
    carries_default_route: bool = False
    carrier_up: bool | None = Field(
        default=None, description="Whether a cable is plugged in; null when unreported"
    )
    in_use_by: str | None = Field(
        default=None,
        description=(
            "Another connection currently active on this port, if any. Null when the "
            "port is idle, or when the only thing using it is this Sentry's own share."
        ),
    )


class WiredInterfacesResponse(BaseModel):
    """`GET /api/wired/interfaces` body. Empty when nothing can be enumerated."""

    model_config = ConfigDict(frozen=True)

    interfaces: tuple[WiredInterfaceItem, ...] = ()
    generated_at: int = Field(description="Unix ms")


class WiredClientItem(BaseModel):
    """One DHCP lease issued by the wired share."""

    model_config = ConfigDict(frozen=True)

    mac_address: str
    ip_address: str
    hostname: str | None = None
    lease_expires_at_ms: int = Field(description="Unix ms")
    expired: bool = Field(description="Whether the lease has already lapsed")


class WiredClientsResponse(BaseModel):
    """`GET /api/wired/clients` body.

    `clients` is `null`, never `[]`, when no lease file could be read — "we
    cannot tell" and "nothing is plugged in" are different answers and the UI
    renders them differently.
    """

    model_config = ConfigDict(frozen=True)

    clients: tuple[WiredClientItem, ...] | None = None
    source: Literal["dnsmasq-leases"] = "dnsmasq-leases"
    generated_at: int = Field(description="Unix ms")
