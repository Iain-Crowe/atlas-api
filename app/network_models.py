"""Validated network measurements exchanged with the host Agent."""
from __future__ import annotations

from typing import Literal
import ipaddress
from pydantic import BaseModel, ConfigDict, Field, model_validator

SOURCES = ('host', 'minecraft', 'minecraft-craftbox', 'jellyfin', 'pihole', 'gluetun', 'qbittorrent',
           'radarr', 'sonarr', 'prowlarr', 'seerr', 'flaresolverr',
           'atlas-web', 'atlas-api', 'atlas-collector')


class NetworkReading(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', allow_inf_nan=False)
    source: str = Field(max_length=64)
    members: list[str] = Field(max_length=32)
    interfaces: list[str] = Field(max_length=32)
    state: Literal['ok', 'warming_up', 'down', 'stopped', 'unavailable', 'unsupported']
    observed_at: float = Field(ge=0)
    monotonic_at: float = Field(ge=0)
    generation: str | None = Field(max_length=512)
    rx_bytes: int | None = Field(ge=0, le=2**63-1)
    tx_bytes: int | None = Field(ge=0, le=2**63-1)
    rx_mbps: float | None = Field(ge=0)
    tx_mbps: float | None = Field(ge=0)

    @model_validator(mode='after')
    def validate_source(self) -> NetworkReading:
        if self.source not in SOURCES or any(member not in SOURCES[1:] for member in self.members):
            raise ValueError('Unknown network source')
        if self.state == 'ok' and any(value is None for value in
                (self.generation, self.rx_bytes, self.tx_bytes, self.rx_mbps, self.tx_mbps)):
            raise ValueError('Incomplete network measurement')
        return self



class LinkQuality(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', allow_inf_nan=False)
    interface: str = Field(max_length=15, pattern=r'^[A-Za-z0-9_.-]*$')
    router: str = Field(max_length=15)
    link_type: Literal['ethernet', 'wifi', 'unknown'] = 'unknown'
    link_state: Literal['up', 'down', 'unavailable'] = 'unavailable'
    link_speed_mbps: float | None = Field(default=None, gt=0, le=1_000_000)
    duplex: Literal['full', 'half'] | None = None
    observed_at: float = Field(ge=0)
    ping_state: Literal['ok', 'no_reply', 'unavailable']
    wifi_state: Literal['connected', 'disconnected', 'unavailable', 'not_applicable']
    packets_sent: int | None = Field(ge=1, le=5)
    packets_received: int | None = Field(ge=0, le=5)
    latency_ms: float | None = Field(ge=0)
    loss_percent: float | None = Field(ge=0, le=100)
    signal_dbm: float | None = Field(ge=-150, le=0)
    rx_link_mbps: float | None = Field(ge=0)
    tx_link_mbps: float | None = Field(ge=0)

    @model_validator(mode='after')
    def counts_match(self) -> LinkQuality:
        if self.router:
            ipaddress.IPv4Address(self.router)
        if self.ping_state != 'unavailable':
            if self.packets_sent is None or self.packets_received is None or self.loss_percent is None:
                raise ValueError('Missing ping counts')
            if self.packets_received > self.packets_sent:
                raise ValueError('Invalid ping counts')
            expected = (self.packets_sent-self.packets_received)*100.0/self.packets_sent
            if abs(expected-self.loss_percent) > .001:
                raise ValueError('Loss does not match probe counts')
            if self.ping_state == 'ok' and (self.packets_received == 0 or self.latency_ms is None):
                raise ValueError('Missing ping replies')
            if self.ping_state == 'no_reply' and (self.packets_received != 0 or self.latency_ms is not None):
                raise ValueError('Unexpected ping replies')
        return self


class NetworkSnapshot(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', allow_inf_nan=False)
    ok: Literal[True]
    sample_seconds: float = Field(gt=0, le=60)
    readings: list[NetworkReading] = Field(max_length=32)
    quality: LinkQuality | None = None

    @model_validator(mode='after')
    def unique_sources(self) -> NetworkSnapshot:
        if len({r.source for r in self.readings}) != len(self.readings):
            raise ValueError('Duplicate network source')
        return self
