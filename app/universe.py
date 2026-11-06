"""The ~30-Instrument universe: our taxonomy (asset class, kind, sector) per ticker.

Names, exchange, currency and prices come from the market-data snapshot; the
classification below is ours, since the free data tier does not provide it.
"""

from dataclasses import dataclass

GICS_SECTORS = (
    "Communication Services",
    "Consumer Discretionary",
    "Consumer Staples",
    "Energy",
    "Financials",
    "Health Care",
    "Industrials",
    "Information Technology",
    "Materials",
    "Real Estate",
    "Utilities",
)


@dataclass(frozen=True)
class UniverseEntry:
    symbol: str
    asset_class: str  # equity | bond | cash
    kind: str  # equity | fund | cash
    sector: str | None  # GICS sector for single stocks and sector ETFs


def _e(symbol, sector):
    return UniverseEntry(symbol, "equity", "equity", sector)


def _sector_etf(symbol, sector):
    return UniverseEntry(symbol, "equity", "fund", sector)


UNIVERSE: tuple[UniverseEntry, ...] = (
    _e("GOOGL", "Communication Services"),
    _e("AMZN", "Consumer Discretionary"),
    _e("PG", "Consumer Staples"),
    _e("XOM", "Energy"),
    _e("JPM", "Financials"),
    _e("JNJ", "Health Care"),
    _e("CAT", "Industrials"),
    _e("AAPL", "Information Technology"),
    _e("MSFT", "Information Technology"),
    _e("NVDA", "Information Technology"),
    _e("LIN", "Materials"),
    _e("PLD", "Real Estate"),
    _e("NEE", "Utilities"),
    _sector_etf("XLC", "Communication Services"),
    _sector_etf("XLY", "Consumer Discretionary"),
    _sector_etf("XLP", "Consumer Staples"),
    _sector_etf("XLE", "Energy"),
    _sector_etf("XLF", "Financials"),
    _sector_etf("XLV", "Health Care"),
    _sector_etf("XLI", "Industrials"),
    _sector_etf("XLK", "Information Technology"),
    _sector_etf("XLB", "Materials"),
    _sector_etf("XLRE", "Real Estate"),
    _sector_etf("XLU", "Utilities"),
    UniverseEntry("SPY", "equity", "fund", None),
    UniverseEntry("AGG", "bond", "fund", None),
    UniverseEntry("TLT", "bond", "fund", None),
    UniverseEntry("LQD", "bond", "fund", None),
    UniverseEntry("SHY", "bond", "fund", None),
    UniverseEntry("SGOV", "cash", "cash", None),  # 0-3 month T-bill ETF as cash proxy
)

# Display names: the Twelve Data time-series endpoint returns no instrument name.
NAMES = {
    "GOOGL": "Alphabet Inc",
    "AMZN": "Amazon.com Inc",
    "PG": "Procter & Gamble Co",
    "XOM": "Exxon Mobil Corp",
    "JPM": "JPMorgan Chase & Co",
    "JNJ": "Johnson & Johnson",
    "CAT": "Caterpillar Inc",
    "AAPL": "Apple Inc",
    "MSFT": "Microsoft Corp",
    "NVDA": "NVIDIA Corp",
    "LIN": "Linde plc",
    "PLD": "Prologis Inc",
    "NEE": "NextEra Energy Inc",
    "XLC": "Communication Services Select Sector SPDR Fund",
    "XLY": "Consumer Discretionary Select Sector SPDR Fund",
    "XLP": "Consumer Staples Select Sector SPDR Fund",
    "XLE": "Energy Select Sector SPDR Fund",
    "XLF": "Financial Select Sector SPDR Fund",
    "XLV": "Health Care Select Sector SPDR Fund",
    "XLI": "Industrial Select Sector SPDR Fund",
    "XLK": "Technology Select Sector SPDR Fund",
    "XLB": "Materials Select Sector SPDR Fund",
    "XLRE": "Real Estate Select Sector SPDR Fund",
    "XLU": "Utilities Select Sector SPDR Fund",
    "SPY": "SPDR S&P 500 ETF Trust",
    "AGG": "iShares Core US Aggregate Bond ETF",
    "TLT": "iShares 20+ Year Treasury Bond ETF",
    "LQD": "iShares iBoxx $ Investment Grade Corporate Bond ETF",
    "SHY": "iShares 1-3 Year Treasury Bond ETF",
    "SGOV": "iShares 0-3 Month Treasury Bond ETF",
}
