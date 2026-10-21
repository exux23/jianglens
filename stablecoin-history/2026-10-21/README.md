# Historical stablecoin database (collected October 21, 2026)

Daily time series from DefiLlama for 424 currently listed stablecoins, totaling **343,995 observations**, including series for inactive/depegged assets that remain in the current provider catalog. The earliest provider daily record can predate the 2020s. Source: https://stablecoins.llama.fi/stablecoincharts/all?stablecoin=1

Data files in supply/ are gzip-compressed UTF-8 CSV files. Download and decompress each file or use the accompanying joiner script. All 12 batches were collected without endpoint errors.

Fields: date_utc, date_unix, stablecoin_id, symbol, name, peg_type, circulating, circulating_usd, unreleased, minted_usd, bridged_to_usd.

Circulating represents the number of units in the stablecoin's peg currency. USD totals are the source's estimated dollar valuation. Some types are pegged to currencies other than USD. Missing fields are blank, not zero. The historical provider can revise records retrospectively.

**Collection caveat:** The optional bridged_to_usd field was inadvertently not collected for portions of batches beginning at catalog index 215. Do not treat blank bridge data as zeros. Supply and circulation USD values are unaffected.

The manifest.json file records row counts and the compressed file list. Data is supplied as collected without reserve/issuer audit. DefiLlama usage rules apply.
