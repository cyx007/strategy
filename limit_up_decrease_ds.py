import backtrader as bt
import tushare as ts
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os
import re


# 设置Tushare的Token
ts.set_token('0ff27db3b933751cc13e959f62e7147d441325b4fdc2a4fd1b0aacfe')
pro = ts.pro_api()
start_date = '20240101'
end_date = datetime.now().strftime('%Y%m%d')  # 当前时间
END_DATE=end_date
INIT_CASH = 1_000_000
MAX_WORKERS = 4  # 根据API限制调整并发数
STOCK_BASIC_FILE = 'stock_basic.csv'  # 本地存储文件


# ================== 数据工具函数 ==================
def calculate_up_limit(ts_code, pre_close):
    """精确计算涨停价"""
    if ts_code.startswith('688') or ts_code.startswith('300'):
        return round(pre_close * 1.2, 2)  # 科创板和创业板20%
    elif ts_code.startswith('8'):
        return round(pre_close * 1.3, 2)  # 北交所30%（虽然已过滤，保留逻辑）
    else:
        return round(pre_close * 1.1, 2)  # 主板10%

def get_trade_days():
    """获取交易日历"""
    schedule = TRADE_CALENDAR.schedule(start_date=START_DATE, end_date=END_DATE)
    return schedule.index.tz_localize(None).to_pydatetime().tolist()

def process_stock_data(ts_code):
    """多进程处理单只股票数据"""
    try:
        df = pro.daily(ts_code=ts_code, start_date=START_DATE, end_date=END_DATE)
        if df.empty:
            return None

        # 计算涨停价
        df['pre_close'] = df['close'].shift(1)
        df['up_limit'] = df.apply(lambda x: calculate_up_limit(x['ts_code'], x['pre_close']), axis=1)
        df['is_limit_up'] = np.isclose(df['close'], df['up_limit'], rtol=0.01)

        # 格式转换
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        df.set_index('trade_date', inplace=True)
        df.sort_index(inplace=True)
        return (ts_code, df)
    except Exception as e:
        print(f"Error processing {ts_code}: {str(e)}")
        return None

# ================== 本地数据存储与加载 ==================
def save_stock_basic_to_local(file_path=STOCK_BASIC_FILE):
    """获取股票基础数据并保存到本地文件"""
    df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,name,list_date,market,list_status')
    df.to_csv(file_path, index=False)
    print(f"股票基础数据已保存到 {file_path}")


def load_stock_basic_from_local(file_path=STOCK_BASIC_FILE):
    """从本地文件加载股票基础数据"""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"本地文件 {file_path} 不存在，请先调用 save_stock_basic_to_local 保存数据")
    return pd.read_csv(file_path)


def filter_st_stocks(df):
    """
    精确过滤名称中包含 ST 或 *ST 的股票（支持全角/半角符号）
    :param df: 包含股票基础数据的 DataFrame，必须包含 'name' 列
    :return: 过滤后的 DataFrame
    """
    # 预编译正则表达式（匹配以下形式）：
    # 1. 以 *ST、＊ST（全角星号）、ST 开头
    # 2. 中间含有 ST（如 公司ST摘帽）
    st_pattern = re.compile(
        r'^[\*＊]?ST|.*ST',
        flags=re.IGNORECASE  # 忽略大小写
    )

    # 检查匹配
    is_st = df['name'].apply(lambda x: bool(st_pattern.search(str(x))))

    # 返回非 ST 股票
    return df[~is_st]

def get_filtered_stocks(use_local=True, file_path=STOCK_BASIC_FILE):
    """获取并过滤股票列表"""
    if use_local:
        try:
            print("读取本地数据")
            df = load_stock_basic_from_local(file_path)
        except FileNotFoundError:
            print("本地数据不存在，从 Tushare 获取数据...")
            df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,name,list_date,market,list_status')
            df.to_csv(file_path, index=False)
    else:
        df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,name,list_date,market,is_st,list_status')

    # 过滤 ST 股票
    df = filter_st_stocks(df)

    # 其他过滤条件
    cutoff_date = pd.to_datetime(END_DATE) - pd.DateOffset(years=1)
    print("cutoff_data=",cutoff_date)
    df = df[
        (pd.to_datetime(df['list_date']) < cutoff_date) &  # 上市超过1年
        (~df['market'].isin(['科创板', '北交所'])) &  # 排除科创板和北交所
        (df['list_status'] == 'L')  # 仅上市状态
        ]

    return df['ts_code'].tolist()

# ================== 策略类 ==================
class LimitUpStrategy(bt.Strategy):
    params = (
        ('position_ratio', 0.3),
        ('max_positions', 3),
        ('profit_target', 0.03),
    )

    def __init__(self):
        self.orders = {}
        self.positions_count = 0
        # 为每个股票维护状态
        self.stock_status = {}
        for d in self.datas:
            self.stock_status[d._name] = {
                'limit_up_day': -3,
                'volume_decrease_days': 0,
                'price_decrease_days': 0,
                'entry_price': None
            }

    def next(self):
        current_date = self.datetime.date(0).isoformat()

        # 先处理卖出逻辑
        for i, d in enumerate(self.datas):
            position = self.getposition(d)
            if position.size > 0:
                # 止盈逻辑
                if (d.close[0] / self.stock_status[d._name]['entry_price']) >= 1.03:
                    self.sell(data=d, size=position.size)
                    self.positions_count -= 1
                # 尾盘卖出逻辑
                elif self._is_last_bar():
                    self.sell(data=d, size=position.size)
                    self.positions_count -= 1

        # 处理买入逻辑
        if self.positions_count >= self.params.max_positions:
            return

        for i, d in enumerate(self.datas):
            status = self.stock_status[d._name]

            # 涨停判断逻辑
            if len(d.close) < 4:
                continue

            # 涨停日判断（简化处理）
            is_limit_up = abs(d.close[-3] - d.pre_close[-3] * 1.1) < 0.01  # 假设3天前涨停

            # 连续三天缩量回调判断
            cond1 = d.volume[-2] < d.volume[-3]  # 第1天缩量
            cond2 = d.volume[-1] < d.volume[-2]  # 第2天缩量
            cond3 = d.close[-2] < d.close[-3]  # 第1天价格下跌
            cond4 = d.close[-1] < d.close[-2]  # 第2天价格下跌
            cond5 = d.close[0] > d.close[-1]  # 第3天上涨

            if is_limit_up and cond1 and cond2 and cond3 and cond4 and cond5:
                # 计算可买数量
                available_cash = self.broker.get_cash()
                position_value = available_cash * self.params.position_ratio
                size = int(position_value / d.close[0]) / 100 * 100  # 按手数买入

                if size > 0 and self.positions_count < self.params.max_positions:
                    self.buy(data=d, size=size)
                self.positions_count += 1
                status['entry_price'] = d.close[0]

    def _is_last_bar(self):
        # 判断是否是当日最后一个bar（假设是日线数据）
        return True

    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.isbuy():
                print(f"买入 {order.data._name} 价格：{order.executed.price}")
            elif order.issell():
                print(f"卖出 {order.data._name} 价格：{order.executed.price}")


# ================== 回测设置 ==================
if __name__ == '__main__':
    cerebro = bt.Cerebro()

    # 首次运行时保存数据到本地
    if not os.path.exists(STOCK_BASIC_FILE):
        save_stock_basic_to_local()

    # 添加筛选后的股票数据
    valid_stocks = get_filtered_stocks(use_local=True)[:30]  # 示例取前30只，实际需处理全部

    for ts_code in valid_stocks:
        df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        df.set_index('trade_date', inplace=True)
        df.sort_index(inplace=True)
        data = bt.feeds.PandasData(dataname=df, name=ts_code)
        cerebro.adddata(data)

    # 添加策略
    cerebro.addstrategy(LimitUpStrategy)

    # 设置初始资金
    cerebro.broker.set_cash(1000000)

    # 设置交易手续费
    cerebro.broker.setcommission(commission=0.001)

    # 运行回测
    results = cerebro.run()

    # 输出结果
    print(f'最终资产价值: {cerebro.broker.getvalue():.2f}')

    # 绘制结果
    cerebro.plot()