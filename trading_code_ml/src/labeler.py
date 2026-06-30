from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class Labeler:
    settings: dict[str, Any]

    def add_labels(self, df: pd.DataFrame) -> pd.DataFrame:
        data = df.copy().sort_values("date").reset_index(drop=True)
        model_cfg = self.settings["model"]
        forward_days = int(model_cfg["label_forward_days"])
        up_threshold = float(model_cfg["label_threshold_up"])
        down_threshold = float(model_cfg["label_threshold_down"])

        future_max_high = data["high"].shift(-1).rolling(window=forward_days, min_periods=forward_days).max()
        future_max_high = future_max_high.shift(-(forward_days - 1))
        data["future_return"] = future_max_high / data["close"] - 1
        data["label"] = np.select(
            [data["future_return"] >= up_threshold, data["future_return"] <= down_threshold],
            [1, -1],
            default=0,
        )
        data["target_binary"] = (data["label"] == 1).astype(int)
        data["target_3class"] = data["label"]
        return data

    def class_distribution(self, df: pd.DataFrame) -> pd.Series:
        return df["label"].value_counts(dropna=False).sort_index()

