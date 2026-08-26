"""Cost estimation.

Seedance bills on the video it produces, not on what you send it: the prompt,
the first frame and reference images are free, and so is audio. What you pay for
is output tokens, and ByteDance counts them as

    (input video seconds + output seconds) x width x height x fps / 1024

Resellers hide that behind a dollars-per-second rate, so this module supports
both bases and refuses to price a combination it has no published number for.
Guessing a rate would move the surprise from here to the invoice.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from seedance.models import CostEstimate, JobSpec, Resolution

RATES_PATH = Path(__file__).with_name("rates.toml")

TOKEN_DIVISOR = 1024


class PricingError(RuntimeError):
    """Base class for anything that stops a job being costed."""


class UnknownProviderError(PricingError):
    def __init__(self, provider: str, known: list[str]) -> None:
        super().__init__(
            f"unknown provider {provider!r}; rates.toml knows: {', '.join(sorted(known))}"
        )


class UnknownRateError(PricingError):
    def __init__(self, provider: str, resolution: str, source: str) -> None:
        super().__init__(
            f"no published rate for {resolution} on {provider!r}. "
            f"Read the live price at {source} and add it to rates.toml — "
            f"this tool will not guess a rate."
        )


@dataclass(frozen=True, slots=True)
class Frame:
    width: int
    height: int

    @property
    def pixels(self) -> int:
        return self.width * self.height


@dataclass(frozen=True, slots=True)
class ProviderRates:
    """One provider's published prices, plus where and when they were read."""

    name: str
    label: str
    billing: str
    checked_at: str
    source: str
    notes: str = ""
    model_id: str | None = None
    currency: str = "USD"
    has_adapter: bool = True
    usd_per_second: dict[str, float] | None = None
    usd_per_million_tokens: float | None = None
    usd_per_million_tokens_with_video: float | None = None
    usd_per_million_tokens_by_resolution: dict[str, float] | None = None
    with_video_multiplier: float = 1.0

    def token_rate(self, resolution: Resolution, *, with_video: bool) -> float:
        """Dollars per million tokens for this resolution and input type."""
        by_resolution = self.usd_per_million_tokens_by_resolution or {}
        if not with_video and resolution.value in by_resolution:
            return by_resolution[resolution.value]
        if with_video and self.usd_per_million_tokens_with_video is not None:
            return self.usd_per_million_tokens_with_video
        if self.usd_per_million_tokens is None:
            raise UnknownRateError(self.name, resolution.value, self.source)
        return self.usd_per_million_tokens


@dataclass(frozen=True, slots=True)
class RateTable:
    resolutions: dict[str, Frame]
    providers: dict[str, ProviderRates]

    def frame(self, resolution: Resolution) -> Frame:
        try:
            return self.resolutions[resolution.value]
        except KeyError as exc:  # pragma: no cover - guarded by the Resolution enum
            raise PricingError(f"rates.toml has no frame size for {resolution}") from exc

    def provider(self, name: str) -> ProviderRates:
        try:
            return self.providers[name]
        except KeyError as exc:
            raise UnknownProviderError(name, list(self.providers)) from exc

    def tokens(self, spec: JobSpec) -> int:
        """ByteDance's own token count for this job."""
        frame = self.frame(spec.resolution)
        seconds = spec.duration_s + spec.reference_video_s
        exact = seconds * frame.pixels * spec.fps / TOKEN_DIVISOR
        return round(exact)

    def estimate(self, provider: str, spec: JobSpec) -> CostEstimate:
        """What this job should cost on this provider, at list price."""
        rates = self.provider(provider)

        if rates.billing == "token":
            tokens = self.tokens(spec)
            rate = rates.token_rate(spec.resolution, with_video=spec.has_video_input)
            usd = tokens * rate / 1_000_000
            return CostEstimate(
                usd=usd,
                basis="token",
                tokens=tokens,
                detail=f"{tokens:,} tokens x ${rate:.2f}/M",
            )

        per_second = rates.usd_per_second or {}
        if spec.resolution.value not in per_second:
            raise UnknownRateError(provider, spec.resolution.value, rates.source)
        rate = per_second[spec.resolution.value]
        multiplier = rates.with_video_multiplier if spec.has_video_input else 1.0
        usd = rate * spec.duration_s * multiplier
        detail = f"{spec.duration_s}s x ${rate:.4f}/s"
        if multiplier != 1.0:
            detail += f" x {multiplier} (video input)"
        return CostEstimate(usd=usd, basis="per_second", detail=detail)

    def compare(
        self, spec: JobSpec, *, adapters_only: bool = False
    ) -> list[tuple[ProviderRates, CostEstimate | None, str | None]]:
        """Price one job across every provider in the table.

        Providers with no published rate for this resolution come back with the
        reason instead of a number, so a gap in the table reads as a gap rather
        than as an absence of cheap options.
        """
        rows: list[tuple[ProviderRates, CostEstimate | None, str | None]] = []
        for name, rates in self.providers.items():
            if name == "fake" or (adapters_only and not rates.has_adapter):
                continue
            if rates.currency != "USD":
                rows.append((rates, None, f"priced in {rates.currency}"))
                continue
            try:
                rows.append((rates, self.estimate(name, spec), None))
            except PricingError as exc:
                rows.append((rates, None, str(exc).split(".")[0]))
        rows.sort(key=lambda row: (row[1] is None, row[1].usd if row[1] else 0.0))
        return rows


def _provider_from_toml(name: str, raw: dict[str, Any]) -> ProviderRates:
    return ProviderRates(
        name=name,
        label=raw.get("label", name),
        billing=raw.get("billing", "per_second"),
        checked_at=raw.get("checked_at", "unknown"),
        source=raw.get("source", "unknown"),
        notes=raw.get("notes", ""),
        model_id=raw.get("model_id"),
        currency=raw.get("currency", "USD"),
        has_adapter=raw.get("adapter", True),
        usd_per_second=raw.get("usd_per_second"),
        usd_per_million_tokens=raw.get("usd_per_million_tokens"),
        usd_per_million_tokens_with_video=raw.get("usd_per_million_tokens_with_video"),
        usd_per_million_tokens_by_resolution=raw.get("usd_per_million_tokens_by_resolution"),
        with_video_multiplier=raw.get("with_video_multiplier", 1.0),
    )


def load_rates(path: Path | None = None) -> RateTable:
    """Read the price table from disk."""
    raw = tomllib.loads((path or RATES_PATH).read_text(encoding="utf-8"))
    resolutions = {
        name: Frame(width=body["width"], height=body["height"])
        for name, body in raw.get("resolutions", {}).items()
    }
    providers = {
        name: _provider_from_toml(name, body) for name, body in raw.get("providers", {}).items()
    }
    return RateTable(resolutions=resolutions, providers=providers)
