"""Market-data adapter (ADR-0003): reads the committed snapshot; never touches the network."""
import json
from dataclasses import dataclass
from pathlib import Path

from app.universe import GICS_SECTORS, UNIVERSE  # noqa: F401  (GICS_SECTORS re-exported)


@dataclass(frozen=True)
class Instrument:
    symbol: str
    name: str
    asset_class: str
    kind: str
    sector: str | None
    currency: str
    price: float
    price_date: str


class MarketData:
    def __init__(self, as_of: str, source: str, instruments: dict[str, Instrument], look_through: dict[str, dict[str, float]]):
        self.as_of = as_of
        self.source = source
        self._instruments = instruments
        self._look_through = look_through

    @classmethod
    def load(cls, snapshot_path, look_through_path) -> "MarketData":
        snapshot_path = Path(snapshot_path)
        if not snapshot_path.exists():
            raise FileNotFoundError(
                f"market-data snapshot not found at {snapshot_path}; run `uv run python -m app.market_refresh`"
            )
        snap = json.loads(snapshot_path.read_text())
        look_through = json.loads(Path(look_through_path).read_text())["funds"]
        instruments = {}
        for entry in UNIVERSE:
            raw = snap["instruments"][entry.symbol]
            instruments[entry.symbol] = Instrument(
                symbol=entry.symbol, name=raw["name"], asset_class=entry.asset_class, kind=entry.kind,
                sector=entry.sector, currency=raw["currency"], price=float(raw["price"]), price_date=raw["price_date"],
            )
        return cls(snap["as_of"], snap.get("source", "unknown"), instruments, look_through)

    def instruments(self) -> list[Instrument]:
        return list(self._instruments.values())

    def instrument(self, symbol: str) -> Instrument:
        return self._instruments[symbol]

    def sector_weights(self, symbol: str) -> dict[str, float]:
        """Sector exposure of one unit of value: single stocks map to their sector, funds use look-through,
        cash and bond funds map to 'Cash' / 'Fixed Income'."""
        inst = self._instruments[symbol]
        if inst.kind == "equity":
            assert inst.sector is not None, f"equity {symbol} has no sector in the universe"
            return {inst.sector: 1.0}
        return dict(self._look_through[symbol])
