# Stablecoin Historical Research Dataset (2026-10-21)

Actual downloaded and compressed CSV data from DefiLlama. Original raw current catalog JSON is inside market_and_catalog_2026-10-21.zip. All file names, Git blob SHAs, scopes, and row counts are enumerated in manifest.json.

## Coverage

- **424 stablecoins**, **343,995** historic daily circulating-supply records (supply/)
- **231,764** historical USD price records with explicit upstream price keys (prices/)
- **21,066** market-wide daily supply records across peg types (inside market_and_catalog_2026-10-21.zip)
- **80,763** historical chain-by-peg-type daily records covering Ethereum, Tron, BSC, Solana, Base, Arbitrum, Optimism, Polygon, Avalanche, Sui, Aptos, TON (chains/)
- Latest listings and current per-chain distributions for **209 chains** (catalog ZIP)

The earliest supply records for some assets begin in November 2017, and the historical price feed begins December 30, 2020. Different assets have different inception dates, gaps, and availability windows. Collected October 21, 2026, with source's most recent daily observation October 20.

## Download

Run python download_all.py from this directory to retrieve the compressed files to your computer. The script requires only Python 3 and standard libraries. Or manually download individual .csv.gz files via GitHub and unzip the market/catalog ZIP. Each CSV.gz is separately readable without joining.

## Data semantics

- **circulating** is in the pegged asset's own units, not always USD. **circulating_usd** is USD valuation.
- Prices in prices/ are denominated in USD. The price_key is from the upstream API and stablecoin_id_if_unique is filled only for uniquely matched current catalog keys.
- Missing values are blank and not zero. Data are provider-derived and may contain revisions, incorrect pricing points, outliers and gaps.
- **bridged_to_usd** was not collected for some supply batches starting with index 215. Historical circulating values and circulating_usd are unaffected.
- This is not a full Ethereum token-transfer dump, issuer reserve audit, or all-chains x all-assets event archive.

## Source URLs

https://stablecoins.llama.fi/stablecoins?includePrices=true
https://stablecoins.llama.fi/stablecoincharts/all
https://stablecoins.llama.fi/stablecoinprices
https://stablecoins.llama.fi/stablecoinchains

## Additional huge archives not included

- BlockDB USDC/USDT/DAI transfer Parquet archive (Ethereum 2017-11 to 2025-10): https://huggingface.co/datasets/BlockDB/Stablecoin-Transfers-Ethereum-Cryptocurrency-Data . Provider reports 587,834,869 rows / 83.6 GB.
- Hourly Aave / Curve / Uniswap stablecoin dataset from 2022 onward: https://github.com/MSCA-DN-Digital-Finance/stablecoin-onchain-data . Zenodo https://doi.org/10.5281/zenodo.18348021

Blockscout historic contract reads could not be completed with the available account. Blockscout requires a PRO API key for subsequent requests.
