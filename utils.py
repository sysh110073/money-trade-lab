"""
utils.py — 共用工具函式
台股量化交易策略儀表板
"""
import datetime
import os
import config


def get_today() -> datetime.date:
    """取得今日日期。"""
    return datetime.date.today()


def get_recent_trading_date() -> datetime.date:
    """
    取得最近一個可能的交易日。
    若今天是週末，則往前推到週五。
    注意：無法處理國定假日，但資料 API 會自動回傳最近交易日資料。
    """
    today = get_today()
    weekday = today.weekday()  # 0=Mon ... 6=Sun
    if weekday == 5:  # 週六
        return today - datetime.timedelta(days=1)
    elif weekday == 6:  # 週日
        return today - datetime.timedelta(days=2)
    return today


def get_start_date(lookback_days: int = None) -> str:
    """
    取得回溯起始日期字串 (YYYY-MM-DD)。
    """
    if lookback_days is None:
        lookback_days = config.DEFAULT_LOOKBACK_DAYS
    start = get_today() - datetime.timedelta(days=lookback_days)
    return start.strftime("%Y-%m-%d")


def get_end_date() -> str:
    """取得今日日期字串 (YYYY-MM-DD)。"""
    return get_today().strftime("%Y-%m-%d")


def format_number(value, decimals: int = 0) -> str:
    """格式化數字，加上千分位分隔符號。"""
    if value is None:
        return "N/A"
    try:
        if decimals == 0:
            return f"{int(value):,}"
        return f"{float(value):,.{decimals}f}"
    except (ValueError, TypeError):
        return str(value)


def format_pct(value, decimals: int = 1) -> str:
    """格式化百分比。"""
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.{decimals}f}%"
    except (ValueError, TypeError):
        return str(value)


def get_font_path() -> str:
    """
    取得中文字體路徑。
    優先使用 config 設定，若不存在則嘗試其他常見路徑。
    """
    # 優先使用設定的路徑
    if os.path.exists(config.FONT_PATH):
        return config.FONT_PATH

    # Windows 常見中文字體路徑
    candidates = [
        "C:/Windows/Fonts/msjh.ttc",      # 微軟正黑體
        "C:/Windows/Fonts/msyh.ttc",       # 微軟雅黑
        "C:/Windows/Fonts/simsun.ttc",     # 新宋體
        "C:/Windows/Fonts/simhei.ttf",     # 黑體
        "C:/Windows/Fonts/kaiu.ttf",       # 標楷體
    ]
    for path in candidates:
        if os.path.exists(path):
            return path

    # 無法找到，返回空字串（WordCloud 會使用預設字體）
    return ""


def get_custom_dict_path() -> str:
    """取得 jieba 自定義詞庫路徑。"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dict_path = os.path.join(base_dir, "custom_dict.txt")
    if os.path.exists(dict_path):
        return dict_path
    return ""


def safe_divide(numerator, denominator, default=0.0):
    """安全除法，避免除以零。"""
    try:
        if denominator == 0 or denominator is None:
            return default
        return numerator / denominator
    except (TypeError, ZeroDivisionError):
        return default


def color_positive_negative(val) -> str:
    """
    用於 Pandas Styler，正數顯示紅色、負數顯示綠色（台股慣例）。
    """
    try:
        v = float(val)
        if v > 0:
            return "color: #FF4136"
        elif v < 0:
            return "color: #2ECC40"
        return ""
    except (ValueError, TypeError):
        return ""
