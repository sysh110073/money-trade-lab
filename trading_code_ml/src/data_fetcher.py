from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from .config import ensure_directories

load_dotenv()

try:
    from fubon_neo.sdk import FubonSDK  # type: ignore
except Exception:  # pragma: no cover
    FubonSDK = None


@dataclass
class FetchResult:
    symbol: str
    dataframe: pd.DataFrame


@dataclass
class MarketDataResult:
    endpoint: str
    identifier: str
    dataframe: pd.DataFrame
    path: Path | None = None


class DataFetcher:
    def __init__(self, settings: dict[str, Any], raw_dir: str | Path = "data/raw") -> None:
        self.settings = settings
        self.raw_dir = Path(raw_dir)
        self.marketdata_dir = self.raw_dir / "marketdata"
        ensure_directories(settings)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.marketdata_dir.mkdir(parents=True, exist_ok=True)
        self._sdk = None

    @staticmethod
    def _clean_env(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if "#" in cleaned:
            cleaned = cleaned.split("#", 1)[0].rstrip()
        return cleaned or None

    def _get_login_mode(self) -> str:
        import os

        mode = self._clean_env(os.getenv("FUBON_LOGIN_MODE")) or "password"
        return mode.lower()

    def connect(self) -> None:
        if FubonSDK is None:
            return
        if self._sdk is not None:
            return

        import os

        sdk = FubonSDK()
        login_mode = self._get_login_mode()
        user_id = self._clean_env(os.getenv("FUBON_USER_ID"))
        password = self._clean_env(os.getenv("FUBON_PASSWORD"))
        cert_path = self._clean_env(os.getenv("FUBON_CERT_PATH"))
        cert_password = self._clean_env(os.getenv("FUBON_CERT_PASSWORD"))
        api_key = self._clean_env(os.getenv("FUBON_API_KEY"))

        if login_mode == "api_key" or (login_mode != "password" and api_key):
            if not user_id or not api_key or not cert_path:
                raise ValueError("FUBON_USER_ID / FUBON_API_KEY / FUBON_CERT_PATH is missing in .env")
            try:
                accounts = sdk.apikey_login(user_id, api_key, cert_path, cert_password)
            except Exception as exc:  # pragma: no cover - SDK/network dependent
                raise ValueError(
                    "Fubon API key login failed. Please verify FUBON_USER_ID, FUBON_API_KEY, "
                    "FUBON_CERT_PATH, and FUBON_CERT_PASSWORD."
                ) from exc
        else:
            if not user_id or not password or not cert_path:
                raise ValueError("FUBON_USER_ID / FUBON_PASSWORD / FUBON_CERT_PATH is missing in .env")
            try:
                accounts = sdk.login(user_id, password, cert_path, cert_password)
            except Exception as exc:  # pragma: no cover - SDK/network dependent
                raise ValueError(
                    "Fubon password login failed. Please verify FUBON_USER_ID, FUBON_PASSWORD, "
                    "FUBON_CERT_PATH, and FUBON_CERT_PASSWORD."
                ) from exc

        if not getattr(accounts, "data", None):
            raise ValueError("Fubon login returned no accounts. Please check your credentials and certificate.")

        sdk.init_realtime()
        self._sdk = sdk

    def _normalize_rows(self, data: Any) -> pd.DataFrame:
        if isinstance(data, pd.DataFrame):
            df = data.copy()
        elif isinstance(data, dict):
            if "data" in data and isinstance(data["data"], list):
                df = pd.DataFrame(data["data"])
            else:
                df = pd.DataFrame(data)
        else:
            if hasattr(data, "data") and isinstance(getattr(data, "data"), list):
                df = pd.DataFrame(getattr(data, "data"))
            else:
                df = pd.DataFrame(list(data))

        rename_map = {
            "datetime": "date",
            "trade_date": "date",
            "timestamp": "date",
            "vol": "volume",
        }
        df = df.rename(columns=rename_map)
        expected_cols = ["date", "open", "high", "low", "close", "volume", "turnover", "change"]
        for col in expected_cols:
            if col not in df.columns:
                df[col] = np.nan
        df = df[expected_cols]
        df["date"] = pd.to_datetime(df["date"])
        numeric_cols = [c for c in expected_cols if c != "date"]
        df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
        df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)
        return df

    def _response_payload(self, response: Any) -> Any:
        if response is None:
            return None
        if isinstance(response, pd.DataFrame):
            return response
        if isinstance(response, (list, dict, str, bytes, bytearray)):
            if isinstance(response, (bytes, bytearray)):
                try:
                    return json.loads(response.decode("utf-8"))
                except Exception:
                    return response.decode("utf-8", errors="ignore")
            if isinstance(response, str):
                try:
                    return json.loads(response)
                except Exception:
                    return response
            return response

        for attr in ("data", "Data"):
            if hasattr(response, attr):
                value = getattr(response, attr)
                if value is not None:
                    return value

        for attr in ("content", "Content"):
            if hasattr(response, attr):
                value = getattr(response, attr)
                if value is None:
                    continue
                if isinstance(value, (bytes, bytearray)):
                    try:
                        return json.loads(value.decode("utf-8"))
                    except Exception:
                        return value.decode("utf-8", errors="ignore")
                if isinstance(value, str):
                    try:
                        return json.loads(value)
                    except Exception:
                        return value
                if hasattr(value, "ReadAsStringAsync"):
                    try:
                        text = value.ReadAsStringAsync().Result
                        if isinstance(text, str):
                            try:
                                return json.loads(text)
                            except Exception:
                                return text
                        return text
                    except Exception:
                        pass
                return value

        return response

    def _response_to_dataframe(self, response: Any) -> pd.DataFrame:
        payload = self._response_payload(response)
        if payload is None:
            return pd.DataFrame()
        if isinstance(payload, pd.DataFrame):
            return payload.copy()
        if isinstance(payload, list):
            return pd.DataFrame(payload)
        if isinstance(payload, dict):
            if isinstance(payload.get("data"), list):
                df = pd.DataFrame(payload["data"])
                meta = {k: v for k, v in payload.items() if k != "data" and not isinstance(v, (dict, list))}
                for key, value in meta.items():
                    df[key] = value
                return df
            if "data" in payload and isinstance(payload["data"], dict):
                merged = {k: v for k, v in payload.items() if k != "data" and not isinstance(v, (dict, list))}
                merged.update(payload["data"])
                return pd.DataFrame([merged])
            return pd.DataFrame([payload])
        return pd.DataFrame([{"value": payload}])

    def _call_stock_api(self, func: Any, **params: Any) -> pd.DataFrame:
        self.connect()
        if self._sdk is None:
            raise RuntimeError("fubon_neo SDK is not available in this environment.")
        response = func(**params)
        return self._response_to_dataframe(response)

    def _save_marketdata_csv(self, endpoint: str, identifier: str, df: pd.DataFrame) -> Path:
        safe_endpoint = endpoint.replace("/", "_")
        safe_identifier = identifier.replace("/", "_").replace(":", "_")
        folder = self.marketdata_dir / safe_endpoint
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{safe_identifier}.csv"
        df.to_csv(path, index=False)
        return path

    def _date_chunks(self, start_date: str, end_date: str) -> list[tuple[str, str]]:
        start = pd.Timestamp(start_date).normalize()
        end = pd.Timestamp(end_date).normalize()
        chunk_days = int(self.settings["data"].get("query_interval_days", 360))
        chunk_days = min(chunk_days, 360)
        if chunk_days < 1:
            chunk_days = 360

        chunks: list[tuple[str, str]] = []
        cursor = start
        while cursor <= end:
            chunk_end = min(cursor + pd.Timedelta(days=chunk_days - 1), end)
            chunks.append((cursor.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")))
            cursor = chunk_end + pd.Timedelta(days=1)
        return chunks

    def _fetch_from_fubon(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        self.connect()
        if self._sdk is None:
            raise RuntimeError("fubon_neo SDK is not available in this environment.")
        reststock = self._sdk.marketdata.rest_client.stock
        frames: list[pd.DataFrame] = []
        for chunk_start, chunk_end in self._date_chunks(start_date, end_date):
            chunk_success = False
            while not chunk_success:
                try:
                    df = self._response_to_dataframe(
                        reststock.historical.candles(
                            **{
                                "symbol": symbol,
                                "from": chunk_start,
                                "to": chunk_end,
                                "timeframe": "D",
                                "adjusted": "true",
                                "fields": "open,high,low,close,volume,turnover,change",
                                "sort": "asc",
                            }
                        )
                    )
                    frames.append(self._normalize_rows(df))
                    chunk_success = True
                except Exception as e:
                    if hasattr(e, "status_code") and getattr(e, "status_code") == 429:
                        print(f"[{symbol}] 429 Rate Limit Exceeded. Sleeping for 61 seconds...")
                        time.sleep(61)
                        continue
                    elif "429" in str(e) or "Rate limit" in str(e):
                        print(f"[{symbol}] 429 Rate Limit Exceeded. Sleeping for 61 seconds...")
                        time.sleep(61)
                        continue
                    elif hasattr(e, "status_code") and getattr(e, "status_code") == 404:
                        print(f"[{symbol}] 404 Not Found for chunk {chunk_start} to {chunk_end}. Skipping...")
                        chunk_success = True
                    elif "404" in str(e) or "Not Found" in str(e):
                        print(f"[{symbol}] 404 Not Found for chunk {chunk_start} to {chunk_end}. Skipping...")
                        chunk_success = True
                    else:
                        raise

        if not frames:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "turnover", "change"])

        df = pd.concat(frames, ignore_index=True)
        df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)
        return df

    def _load_local_raw(self, symbol: str) -> Optional[pd.DataFrame]:
        path = self.raw_dir / f"{symbol}_daily.csv"
        if not path.exists():
            return None
        df = pd.read_csv(path)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df

    def fetch_daily_candles(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        source = self.settings["data"].get("source", "fubon_neo")
        if source == "csv":
            local = self._load_local_raw(symbol)
            if local is None:
                raise FileNotFoundError(f"Local raw file not found: {self.raw_dir / f'{symbol}_daily.csv'}")
            return local

        return self._fetch_from_fubon(symbol, start_date, end_date)

    def fetch_historical_stats(self, symbol: str) -> pd.DataFrame:
        return self._call_stock_api(lambda **params: self._sdk.marketdata.rest_client.stock.historical.stats(**params), symbol=symbol)

    def fetch_intraday_quote(self, symbol: str) -> pd.DataFrame:
        return self._call_stock_api(lambda **params: self._sdk.marketdata.rest_client.stock.intraday.quote(**params), symbol=symbol)

    def fetch_intraday_candles(self, symbol: str, timeframe: str = "1") -> pd.DataFrame:
        params: dict[str, Any] = {"symbol": symbol}
        if timeframe:
            params["timeframe"] = timeframe
        return self._call_stock_api(lambda **kwargs: self._sdk.marketdata.rest_client.stock.intraday.candles(**kwargs), **params)

    def fetch_intraday_ticker(self, symbol: str) -> pd.DataFrame:
        return self._call_stock_api(lambda **params: self._sdk.marketdata.rest_client.stock.intraday.ticker(**params), symbol=symbol)

    def fetch_intraday_trades(self, symbol: str, trade_type: str | None = None) -> pd.DataFrame:
        params: dict[str, Any] = {"symbol": symbol}
        if trade_type:
            params["type"] = trade_type
        return self._call_stock_api(lambda **kwargs: self._sdk.marketdata.rest_client.stock.intraday.trades(**kwargs), **params)

    def fetch_intraday_volumes(self, symbol: str, trade_type: str | None = None) -> pd.DataFrame:
        params: dict[str, Any] = {"symbol": symbol}
        if trade_type:
            params["type"] = trade_type
        return self._call_stock_api(lambda **kwargs: self._sdk.marketdata.rest_client.stock.intraday.volumes(**kwargs), **params)

    def fetch_snapshot_quotes(self, market: str = "TSE") -> pd.DataFrame:
        return self._call_stock_api(lambda **params: self._sdk.marketdata.rest_client.stock.snapshot.quotes(**params), market=market)

    def fetch_snapshot_movers(
        self,
        market: str = "TSE",
        direction: str = "up",
        change: str = "percent",
    ) -> pd.DataFrame:
        return self._call_stock_api(
            lambda **params: self._sdk.marketdata.rest_client.stock.snapshot.movers(**params),
            market=market,
            direction=direction,
            change=change,
        )

    def fetch_snapshot_actives(self, market: str = "TSE", trade: str = "value") -> pd.DataFrame:
        return self._call_stock_api(lambda **params: self._sdk.marketdata.rest_client.stock.snapshot.actives(**params), market=market, trade=trade)

    def fetch_corporate_actions_dividends(self, start_date: str, end_date: str) -> pd.DataFrame:
        return self._call_stock_api(
            lambda **params: self._sdk.marketdata.rest_client.stock.corporate_actions.dividends(**params),
            start_date=start_date,
            end_date=end_date,
        )

    def fetch_corporate_actions_capital_changes(self, start_date: str, end_date: str) -> pd.DataFrame:
        return self._call_stock_api(
            lambda **params: self._sdk.marketdata.rest_client.stock.corporate_actions.capital_changes(**params),
            start_date=start_date,
            end_date=end_date,
        )

    def save_marketdata(self, endpoint: str, identifier: str, df: pd.DataFrame) -> Path:
        return self._save_marketdata_csv(endpoint, identifier, df)

    def download_marketdata(self, endpoint: str, identifier: str, fetcher: Any, *args: Any, **kwargs: Any) -> MarketDataResult:
        df = fetcher(*args, **kwargs)
        path = self._save_marketdata_csv(endpoint, identifier, df)
        return MarketDataResult(endpoint=endpoint, identifier=identifier, dataframe=df, path=path)

    def save_raw(self, symbol: str, df: pd.DataFrame) -> Path:
        path = self.raw_dir / f"{symbol}_daily.csv"
        df.to_csv(path, index=False)
        return path

    def download_stock(self, symbol: str) -> FetchResult:
        data_cfg = self.settings["data"]
        last_error: Exception | None = None
        
        path = self.raw_dir / f"{symbol}_daily.csv"
        if path.exists():
            print(f"[{symbol}] Data already exists. Skipping fetch.")
            return FetchResult(symbol=symbol, dataframe=self.load_raw_csv(symbol))
            
        for attempt in range(1, int(data_cfg["retry_max"]) + 1):
            try:
                print(f"[{symbol}] Fetching data from Fubon API...")
                df = self.fetch_daily_candles(symbol, data_cfg["start_date"], data_cfg["end_date"])
                self.save_raw(symbol, df)
                return FetchResult(symbol=symbol, dataframe=df)
            except Exception as exc:  # pragma: no cover - network / SDK dependent
                last_error = exc
                if attempt < int(data_cfg["retry_max"]):
                    time.sleep(float(data_cfg["retry_delay_sec"]))
        raise RuntimeError(f"Failed to download {symbol}") from last_error

    def download_many(self, symbols: Iterable[str]) -> list[FetchResult]:
        results: list[FetchResult] = []
        for symbol in symbols:
            results.append(self.download_stock(symbol))
        return results

    def load_raw_csv(self, symbol: str) -> pd.DataFrame:
        path = self.raw_dir / f"{symbol}_daily.csv"
        if not path.exists():
            raise FileNotFoundError(path)
        df = pd.read_csv(path)
        df["date"] = pd.to_datetime(df["date"])
        return df
