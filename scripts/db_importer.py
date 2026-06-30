import sqlite3
import pandas as pd
from pandas.errors import EmptyDataError
import json
import argparse
from pathlib import Path
from datetime import datetime
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "market_data.db"
DEFAULT_FEATURES_PATH = ROOT / "data" / "processed" / "all_features.csv"

def ensure_column(conn, table_name, column_name, definition):
    cursor = conn.cursor()
    columns = {row[1] for row in cursor.execute(f"PRAGMA table_info({table_name})")}
    if column_name not in columns:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def init_db(conn):
    cursor = conn.cursor()
    
    # 1. stock_daily_prices
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stock_daily_prices (
            symbol TEXT,
            date DATE,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            turnover INTEGER,
            change REAL,
            PRIMARY KEY (symbol, date)
        )
    ''')
    
    # 2. stock_daily_features
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stock_daily_features (
            symbol TEXT,
            date DATE,
            sma_5 REAL,
            sma_20 REAL,
            sma_60 REAL,
            macd REAL,
            macd_signal REAL,
            rsi_14 REAL,
            atr_14 REAL,
            adx_14 REAL,
            bollinger_upper_20 REAL,
            bollinger_lower_20 REAL,
            bollinger_percent_b REAL,
            close_return_1 REAL,
            close_return_5 REAL,
            close_return_10 REAL,
            rolling_volatility_20 REAL,
            position_in_52w_range REAL,
            future_return REAL,
            label INTEGER,
            target_binary INTEGER,
            target_3class INTEGER,
            PRIMARY KEY (symbol, date)
        )
    ''')
    
    # 3. institutional_flow
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS institutional_flow (
            symbol TEXT,
            date DATE,
            foreign_net REAL,
            trust_net REAL,
            total_net REAL,
            foreign_net_5d_sum REAL,
            trust_net_5d_sum REAL,
            PRIMARY KEY (symbol, date)
        )
    ''')
    
    # 4. backtest_runs
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS backtest_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_name TEXT,
            run_uid TEXT,
            config_hash TEXT,
            sim_start_date DATE,
            sim_end_date DATE,
            strategy_type TEXT,
            capital REAL,
            position_sizing TEXT,
            max_risk_per_trade REAL,
            portfolio_max_positions INTEGER,
            portfolio_max_position_pct REAL,
            atr_stop_multiplier REAL,
            trailing_stop_trigger REAL,
            trailing_stop_atr REAL,
            total_return REAL,
            cagr REAL,
            sharpe REAL,
            max_drawdown REAL,
            win_rate REAL,
            profit_factor REAL,
            trades INTEGER,
            mean_capital_utilization REAL,
            benchmark_total_return REAL,
            benchmark_cagr REAL,
            benchmark_sharpe REAL,
            csv_trades_path TEXT,
            csv_equity_path TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    ensure_column(conn, 'backtest_runs', 'run_uid', 'TEXT')
    ensure_column(conn, 'backtest_runs', 'config_hash', 'TEXT')
    
    # 5. trade_log
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trade_log (
            trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER,
            symbol TEXT,
            entry_date DATE,
            exit_date DATE,
            shares INTEGER,
            entry_price REAL,
            exit_price REAL,
            gross_pnl REAL,
            net_pnl REAL,
            exit_reason TEXT,
            holding_days INTEGER,
            signal_tier TEXT,
            strategy_score REAL,
            selected_strategy_count INTEGER,
            selected_strategy_ids TEXT,
            win INTEGER,
            FOREIGN KEY(run_id) REFERENCES backtest_runs(run_id)
        )
    ''')
    
    # 6. equity_curve
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS equity_curve (
            run_id INTEGER,
            date DATE,
            equity REAL,
            cash REAL,
            invested_notional REAL,
            capital_utilization REAL,
            open_positions INTEGER,
            drawdown REAL,
            PRIMARY KEY (run_id, date),
            FOREIGN KEY(run_id) REFERENCES backtest_runs(run_id)
        )
    ''')
    
    # 7. open_positions
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS open_positions (
            run_id INTEGER,
            as_of_date DATE,
            symbol TEXT,
            entry_date DATE,
            entry_price REAL,
            shares INTEGER,
            stop_loss REAL,
            take_profit REAL,
            trailing_stop REAL,
            peak_price REAL,
            holding_days INTEGER,
            signal_tier TEXT,
            strategy_score REAL,
            selected_strategy_ids TEXT,
            industry TEXT,
            current_price REAL,
            market_value REAL,
            unrealized_pnl REAL,
            unrealized_return REAL,
            portfolio_weight REAL,
            PRIMARY KEY (run_id, as_of_date, symbol),
            FOREIGN KEY(run_id) REFERENCES backtest_runs(run_id)
        )
    ''')

    # 8. buy_log
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS buy_log (
            run_id INTEGER,
            date DATE,
            symbol TEXT,
            shares INTEGER,
            entry_price REAL,
            notional REAL,
            cost REAL,
            cash_after REAL,
            strategy_score REAL,
            rank_signal_score REAL,
            candidate_rank INTEGER,
            candidate_count INTEGER,
            sizing_multiplier REAL,
            buy_reason TEXT,
            replacement_from TEXT,
            market_regime TEXT,
            signal_tier TEXT,
            PRIMARY KEY (run_id, date, symbol, buy_reason),
            FOREIGN KEY(run_id) REFERENCES backtest_runs(run_id)
        )
    ''')
    conn.commit()


def upsert_df(df, table_name, conn, primary_keys):
    if df.empty:
        return
    
    # Ensure all nan values are converted to None for sqlite compatibility
    df = df.replace({np.nan: None})
    
    columns = list(df.columns)
    placeholders = ", ".join(["?"] * len(columns))
    cols_str = ", ".join(columns)
    updates_str = ", ".join([f"{col}=excluded.{col}" for col in columns if col not in primary_keys])
    
    sql = f"""
        INSERT INTO {table_name} ({cols_str})
        VALUES ({placeholders})
        ON CONFLICT({", ".join(primary_keys)})
        DO UPDATE SET {updates_str}
    """
    if not updates_str:
        sql = f"""
            INSERT OR IGNORE INTO {table_name} ({cols_str})
            VALUES ({placeholders})
        """
        
    cursor = conn.cursor()
    # Execute in chunks to avoid sqlite limits
    chunk_size = 10000
    records = df.values.tolist()
    for i in range(0, len(records), chunk_size):
        cursor.executemany(sql, records[i:i+chunk_size])
    conn.commit()


def import_features(csv_path: Path):
    if not csv_path.exists():
        print(f"Feature file not found: {csv_path}")
        return
        
    print(f"Loading {csv_path}...")
    df = pd.read_csv(csv_path)
    df['symbol'] = df['symbol'].astype(str)
    
    prices_cols = ['symbol', 'date', 'open', 'high', 'low', 'close', 'volume', 'turnover', 'change']
    features_cols = ['symbol', 'date', 'sma_5', 'sma_20', 'sma_60', 'macd', 'macd_signal', 'rsi_14', 'atr_14', 'adx_14', 
                     'bollinger_upper_20', 'bollinger_lower_20', 'bollinger_percent_b', 'close_return_1', 'close_return_5', 
                     'close_return_10', 'rolling_volatility_20', 'position_in_52w_range', 'future_return', 'label', 
                     'target_binary', 'target_3class']
    flow_cols = ['symbol', 'date', 'foreign_net', 'trust_net', 'total_net', 'foreign_net_5d_sum', 'trust_net_5d_sum']
    
    df_prices = df[[c for c in prices_cols if c in df.columns]]
    df_features = df[[c for c in features_cols if c in df.columns]]
    df_flow = df[[c for c in flow_cols if c in df.columns]]
    
    with sqlite3.connect(DB_PATH) as conn:
        print("Upserting into stock_daily_prices...")
        upsert_df(df_prices, 'stock_daily_prices', conn, ['symbol', 'date'])
        
        print("Upserting into stock_daily_features...")
        upsert_df(df_features, 'stock_daily_features', conn, ['symbol', 'date'])
        
        print("Upserting into institutional_flow...")
        upsert_df(df_flow, 'institutional_flow', conn, ['symbol', 'date'])
        
    print("Features import complete.")


def import_backtest_run(
    run_name: str,
    summary_json: Path,
    trades_csv: Path,
    equity_csv: Path,
    positions_csv: Path,
    buys_csv: Path | None = None,
    run_uid: str = "",
    config_hash: str = "",
):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        if run_uid:
            cursor.execute("SELECT run_id FROM backtest_runs WHERE run_name = ? AND run_uid = ?", (run_name, run_uid))
        else:
            cursor.execute("SELECT run_id FROM backtest_runs WHERE run_name = ?", (run_name,))
        existing = cursor.fetchone()
        if existing:
            print(f"Run {run_name} already exists with run_id {existing[0]}. Updating records.")
            run_id = existing[0]
            # Delete old children
            cursor.execute("DELETE FROM trade_log WHERE run_id = ?", (run_id,))
            cursor.execute("DELETE FROM equity_curve WHERE run_id = ?", (run_id,))
            cursor.execute("DELETE FROM open_positions WHERE run_id = ?", (run_id,))
            cursor.execute("DELETE FROM buy_log WHERE run_id = ?", (run_id,))
        else:
            run_id = None

        if summary_json and summary_json.exists():
            with open(summary_json, 'r', encoding='utf-8') as f:
                summary = json.load(f)
                
            perf = summary.get('performance', {})
            bm = summary.get('benchmark', {})
            settings = summary.get('settings', {})
            
            run_data = {
                'run_name': run_name,
                'run_uid': run_uid or None,
                'config_hash': config_hash or None,
                'sim_start_date': bm.get('start', '').split('T')[0] if bm.get('start') else None,
                'sim_end_date': bm.get('end', '').split('T')[0] if bm.get('end') else None,
                'strategy_type': summary.get('strategy_name', 'rank_portfolio'),
                'capital': settings.get('capital'),
                'position_sizing': settings.get('position_sizing'),
                'max_risk_per_trade': settings.get('max_risk_per_trade'),
                'portfolio_max_positions': settings.get('portfolio_max_positions'),
                'portfolio_max_position_pct': settings.get('portfolio_max_position_pct'),
                'atr_stop_multiplier': settings.get('atr_stop_multiplier'),
                'trailing_stop_trigger': settings.get('trailing_stop_trigger'),
                'trailing_stop_atr': settings.get('trailing_stop_atr'),
                'total_return': perf.get('total_return'),
                'cagr': perf.get('cagr'),
                'sharpe': perf.get('sharpe'),
                'max_drawdown': perf.get('max_drawdown'),
                'win_rate': perf.get('win_rate'),
                'profit_factor': perf.get('profit_factor'),
                'trades': perf.get('trades'),
                'mean_capital_utilization': perf.get('mean_capital_utilization'),
                'benchmark_total_return': bm.get('total_return'),
                'benchmark_cagr': bm.get('cagr'),
                'benchmark_sharpe': bm.get('sharpe'),
                'csv_trades_path': str(trades_csv.resolve()) if trades_csv else None,
                'csv_equity_path': str(equity_csv.resolve()) if equity_csv else None
            }
            
            df_run = pd.DataFrame([run_data])
            df_run = df_run.replace({np.nan: None})
            
            if run_id is None:
                cols_str = ", ".join(df_run.columns)
                placeholders = ", ".join(["?"] * len(df_run.columns))
                cursor.execute(f"INSERT INTO backtest_runs ({cols_str}) VALUES ({placeholders})", df_run.values.tolist()[0])
                run_id = cursor.lastrowid
            else:
                updates_str = ", ".join([f"{col}=?" for col in df_run.columns])
                vals = df_run.values.tolist()[0]
                vals.append(run_id)
                cursor.execute(f"UPDATE backtest_runs SET {updates_str} WHERE run_id=?", vals)
        else:
            if run_id is None:
                cursor.execute("INSERT INTO backtest_runs (run_name) VALUES (?)", (run_name,))
                run_id = cursor.lastrowid
        
        # Insert trades
        if trades_csv and trades_csv.exists():
            try:
                df_trades = pd.read_csv(trades_csv)
            except EmptyDataError:
                df_trades = pd.DataFrame()
            if not df_trades.empty:
                df_trades['run_id'] = run_id
                df_trades['symbol'] = df_trades['symbol'].astype(str)
                df_trades['win'] = df_trades['win'].astype(int) if 'win' in df_trades.columns else None
                # drop unnecessary cols if they exist
                trade_cols = [c for c in df_trades.columns if c in ['run_id', 'symbol', 'entry_date', 'exit_date', 'shares', 'entry_price', 'exit_price', 'gross_pnl', 'net_pnl', 'exit_reason', 'holding_days', 'signal_tier', 'strategy_score', 'selected_strategy_count', 'selected_strategy_ids', 'win']]
                df_trades[trade_cols].to_sql('trade_log', conn, if_exists='append', index=False)
                
        # Insert equity
        if equity_csv and equity_csv.exists():
            df_equity = pd.read_csv(equity_csv)
            if not df_equity.empty:
                df_equity['run_id'] = run_id
                cols = [c for c in df_equity.columns if c in ['run_id', 'date', 'equity', 'cash', 'invested_notional', 'capital_utilization', 'open_positions', 'drawdown']]
                df_equity[cols].to_sql('equity_curve', conn, if_exists='append', index=False)

        # Insert buys
        if buys_csv and buys_csv.exists():
            try:
                df_buys = pd.read_csv(buys_csv)
            except EmptyDataError:
                df_buys = pd.DataFrame()
            if not df_buys.empty:
                df_buys['run_id'] = run_id
                df_buys['symbol'] = df_buys['symbol'].astype(str)
                buy_cols = [c for c in df_buys.columns if c in ['run_id', 'date', 'symbol', 'shares', 'entry_price', 'notional', 'cost', 'cash_after', 'strategy_score', 'rank_signal_score', 'candidate_rank', 'candidate_count', 'sizing_multiplier', 'buy_reason', 'replacement_from', 'market_regime', 'signal_tier']]
                df_buys[buy_cols].to_sql('buy_log', conn, if_exists='append', index=False)
                
        # Insert positions
        if positions_csv and positions_csv.exists():
            df_pos = pd.read_csv(positions_csv)
            if not df_pos.empty:
                df_pos['run_id'] = run_id
                df_pos['symbol'] = df_pos['symbol'].astype(str)
                # Keep matching columns
                pos_cols = [c for c in df_pos.columns if c in ['run_id', 'as_of_date', 'symbol', 'entry_date', 'entry_price', 'shares', 'stop_loss', 'take_profit', 'trailing_stop', 'peak_price', 'holding_days', 'signal_tier', 'strategy_score', 'selected_strategy_ids', 'industry', 'current_price', 'market_value', 'unrealized_pnl', 'unrealized_return', 'portfolio_weight']]
                df_pos[pos_cols].to_sql('open_positions', conn, if_exists='append', index=False)

        conn.commit()
    print(f"Imported backtest {run_name} successfully into run_id {run_id}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--init-db', action='store_true', help='Initialize database tables')
    parser.add_argument('--import-features', type=Path, help='Import features CSV')
    parser.add_argument('--import-backtest', type=str, help='Run name for backtest import')
    parser.add_argument('--summary', type=Path, help='Summary JSON path')
    parser.add_argument('--trades', type=Path, help='Trades CSV path')
    parser.add_argument('--equity', type=Path, help='Equity CSV path')
    parser.add_argument('--positions', type=Path, help='Positions CSV path')
    parser.add_argument('--buys', type=Path, help='Buys CSV path')
    parser.add_argument('--run-uid', default='', help='Production run id from run_manifest.json')
    parser.add_argument('--config-hash', default='', help='Production config hash from run_manifest.json')
    
    args = parser.parse_args()
    
    with sqlite3.connect(DB_PATH) as conn:
        init_db(conn)
        
    if args.import_features:
        import_features(args.import_features)
        
    if args.import_backtest:
        import_backtest_run(
            args.import_backtest,
            args.summary,
            args.trades,
            args.equity,
            args.positions,
            args.buys,
            args.run_uid,
            args.config_hash,
        )
