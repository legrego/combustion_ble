"""Decide which connections a host should hold for cooking predictions, without any I/O.

The host owns every connection: it resolves addresses through its own adapters, connects, retries,
and cleans up. :func:`plan_connections` only applies Combustion's rules for which devices are worth
connecting to, so every host makes the same choices. Call it whenever the host is about to act,
for example from the same periodic tick that calls :meth:`MeatNet.expire`.

The rules follow the Combustion Android SDK: one connection to a MeatNet repeater relays
predictions for every probe on its network, so prefer it, and connect directly only to probes the
repeater is not reporting.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from combustion_ble.meatnet import MeatNet, Node
from combustion_ble.node_session import NodeSession


@dataclass(frozen=True, slots=True)
class ConnectionPlan:
    """The connections a host should hold, given what MeatNet has heard."""

    repeaters: tuple[str, ...]
    """Addresses of repeaters to try connecting to, best first.

    Empty while a repeater session is running. Try them in order and stop at the first one the
    host can reach through a connection-capable adapter.
    """

    direct: frozenset[int]
    """Serial numbers of probes that should have a direct connection.

    Probes heard directly that no running repeater session is reporting.
    """

    release: frozenset[int]
    """Serial numbers of probes whose direct connection the repeater session makes redundant.

    Close direct connections to these probes; their predictions continue through the repeater.
    """


def plan_connections(
    meatnet: MeatNet,
    *,
    repeater: NodeSession | None = None,
    failed: Collection[str] = (),
) -> ConnectionPlan:
    """Plan prediction connections from the current MeatNet state.

    :param repeater: The host's running repeater session, if any.
    :param failed: Repeater addresses whose most recent connection attempt failed, for example
        because their connection slots were full. They are tried after every other repeater.
    """
    reported = frozenset(
        serial_number
        for serial_number in meatnet.probes
        if repeater is not None and repeater._is_reporting(serial_number)
    )
    if repeater is None:
        candidates = sorted(
            (node for node in meatnet.nodes.values() if node.available),
            key=lambda node: _repeater_rank(node, failed),
            reverse=True,
        )
        repeaters = tuple(node.address for node in candidates)
    else:
        repeaters = ()
    direct = frozenset(
        probe.serial_number
        for probe in meatnet.probes.values()
        if probe.available and probe.address is not None
    )
    return ConnectionPlan(repeaters=repeaters, direct=direct - reported, release=reported)


def _repeater_rank(node: Node, failed: Collection[str]) -> tuple[bool, bool, int]:
    """Prefer repeaters that haven't just failed, then ones relaying probes, then signal."""
    return (
        node.address not in failed,
        bool(node.relayed_probes),
        node.rssi if node.rssi is not None else -999,
    )
