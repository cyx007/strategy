import backtrader as bt
import tushare as ts
import pandas as pd
import os
from datetime import datetime, timedelta
import numpy as np

# 设置Tushare Token
ts.set_token('0ff27db3b933751cc13e959f62e7147d441325b4fdc2a4fd1b0aacfe')
pro = ts.pro_api()

# ================== 数据获取与存储 ==================
def fetch_and_save_data(start_date, end_date):
    # 获取所有A股列表
    df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,name,list_date,market,is_st')

    # 通过股票名称来过滤ST股：名称中含有 "ST" 或 "*ST"
    df = df[~df['name'].str.contains("ST|*ST", na=False)]

    # 过滤科创板、北交所等不需要的市场股票
    df = df[~df['market'].isin(['科创板', '北交所'])]

    # 获取每只股票的历史数据并保存为CSV
    for ts_code in df['ts_code']:
        file_path = f"data/{ts_code}.csv"

        # 如果本地已存在数据，跳过下载
        if os.path.exists(file_path):
            print(f"已存在数据：{ts_code}")
            continue

        print(f"正在下载数据：{ts_code}")
        try:
            stock_data = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            stock_data['trade_date'] = pd.to_datetime(stock_data['trade_date'])
            stock_data.set_index('trade_date', inplace=True)
            stock_data.to_csv(file_path)
        except Exception as e:
            print(f"下载 {ts_code} 时出错: {e}")


# ================== 策略类 ==================
class LimitUpStrategy(bt.Strategy):
    params = (
        ('position_ratio', 0.3),  # 每只股票投入30%资金
        ('max_positions', 3),  # 最多持有3只股票
        ('profit_target', 0.03),  # 卖出利润目标3%
    )

    def __init__(self):
        self.positions_count = 0
        self.stock_status = {}
        for d in self.datas:
            self.stock_status[d._name] = {
                'limit_up_day': -3,
                'volume_decrease_days': 0,
                'price_decrease_days': 0,
                'entry_price': None
            }

    def log(self, txt, dt=None):
        # 记录策略的执行日志
        dt = dt or self.datetime.date(0)
        print('%s, %s' % (dt.isoformat(), txt))

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            # broker 提交/接受了，买/卖订单则什么都不做
            return
        # 检查一个订单是否完成
        # 注意: 当资金不足时，broker会拒绝订单
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f"买入 {order.executed.size} 股，价格：{order.executed.price},总价：{order.executed.value},代码：{order.data._name}")
            elif order.issell():
                self.log(f"卖出 {order.executed.size} 股，价格：{order.executed.price},总价：{order.executed.value},代码：{order.data._name}")

                # 记录当前交易数量
            self.bar_executed = len(self)

    def next(self):
        current_date = self.datetime.date(0).isoformat()

        # 卖出条件
        for i, d in enumerate(self.datas):
            position = self.getposition(d)
            if position.size > 0:
                self.log(f"触发卖出，name {d._name}")
                # 如果涨幅达到3%，则卖出
                if d.close[0] >= self.stock_status[d._name]['entry_price'] * (1 + self.params.profit_target):
                    self.sell(data=d, size=position.size)
                    self.positions_count -= 1
                # 如果未达到目标，在尾盘卖出
                elif self._is_last_bar():
                    self.sell(data=d, size=position.size)
                    self.positions_count -= 1

        # 如果持仓数量达到上限，跳过买入操作
        if self.positions_count >= self.params.max_positions:
            return

        for i, d in enumerate(self.datas):
            status = self.stock_status[d._name]

            if len(d.close) < 5:
                continue

            # 判断是否为涨停日
            is_limit_up = abs(d.close[-3] - d.close[-4] * 1.1) < 0.01  # 假设3天前涨停

            # 连续3日缩量回调判断
            cond1 = d.volume[-2] < d.volume[-3]  # 第1天缩量
            cond2 = d.volume[-1] < d.volume[-2]  # 第2天缩量
            cond3 = d.close[-2] < d.close[-3]  # 第1天价格下跌
            cond4 = d.close[-1] < d.close[-2]  # 第2天价格下跌
            cond5 = d.close[0] > d.close[-1]  # 第3天上涨

            if is_limit_up and cond1 and cond2 and cond3 and cond4 and cond5:
                self.log(f"触发买入，name {d._name}")
                # 计算可买数量
                available_cash = self.broker.get_cash()
                position_value = available_cash * self.params.position_ratio
                size = int(position_value / d.close[0] // 100 * 100)  # 按手数买入

                if size > 0 and self.positions_count < self.params.max_positions:
                    self.buy(data=d, size=size)
                    self.positions_count += 1
                    status['entry_price'] = d.close[0]

    def _is_last_bar(self):
        # 判断是否是当日最后一个bar（假设是日线数据）
        return True


# ================== 回测设置 ==================
def run_backtest(start_date, end_date):
    cerebro = bt.Cerebro()

    # 加载本地数据或拉取新数据
    stocks = os.listdir('data')
    valid_stocks = []  # 存储有效股票

    for stock_file in stocks:
        if stock_file.endswith('.csv'):
            ts_code = stock_file.replace('.csv', '')
            df = pd.read_csv(f"data/{stock_file}", parse_dates=True, index_col='trade_date')
            # 将数据列的名称修改为 backtrader 所需的格式
            df = df[['open', 'high', 'low', 'close', 'vol']]
            df.columns = ['open', 'high', 'low', 'close', 'volume']

            df.sort_index(inplace=True)  # 确保数据按时间排序
            data = bt.feeds.PandasData(dataname=df, name=ts_code)
            valid_stocks.append(ts_code)
            cerebro.adddata(data)

    # 如果本地数据不足，拉取新数据
    if not valid_stocks:
        print("本地无数据，正在拉取新数据...")
        fetch_and_save_data(start_date, end_date)

        # 加载新获取的数据
        for stock_file in os.listdir('data'):
            if stock_file.endswith('.csv'):
                ts_code = stock_file.replace('.csv', '')
                df = pd.read_csv(f"data/{stock_file}", parse_dates=True, index_col='trade_date')
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
    #cerebro.plot()

if __name__ == '__main__':
    # 设置回测的起始时间和结束时间
    start_date = '20240101'
    end_date = '20241231'

    # 运行回测
    run_backtest(start_date, end_date)
