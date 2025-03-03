
import backtrader as bt
import math
# 数据接口
import tushare as ts
import numpy as np
import pandas as pd
import time

# 基础模块
from datetime import datetime,timedelta

# 设置Tushare Token
ts.set_token('0ff27db3b933751cc13e959f62e7147d441325b4fdc2a4fd1b0aacfe')
pro = ts.pro_api()

class TurtleStrategy(bt.Strategy):
    params = (
        ('entry_period', 20),  # 入场通道周期
        ('exit_period', 10),  # 离场通道周期
        ('atr_period', 20),  # 波动率计算周期
        ('risk_percent', 0.02),  # 单笔风险比例
        ('unit_limit', 4),  # 最大加仓单元数
    )
    def log(self, txt, dt=None):
        # 记录策略的执行日志
        dt = dt or self.datetime.date(0)
        print('%s, %s' % (dt.isoformat(), txt))

    def __init__(self):
        # 核心指标计算
        self.high_channel = bt.indicators.Highest(self.data.high, period=self.p.entry_period)
        self.low_channel = bt.indicators.Lowest(self.data.low, period=self.p.exit_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)

        self.order = None
        self.unit = 0  # 当前持仓单元数

    def calculate_position_size(self):
        # 根据ATR和账户资金计算头寸规模
        risk_amount = self.broker.getvalue() * self.params.risk_percent
        size = risk_amount / self.atr[0]
        return int(size)
    def next(self):
        if self.order:  # 有未完成订单则返回
            return

        if self.data.close[0] > self.high_channel[-1]:
            self.log(f'close:{self.data.close[0]} high:{self.high_channel[-1]}')

        # 突破入场信号
        if self.data.close[0] > self.high_channel[-1] and self.unit < self.p.unit_limit:
            size = self.calculate_position_size()
            self.buy(size=size)
            self.unit += 1
            self.log(f'第{self.unit}次加仓 | 价格：{self.data.close[0]:.2f}')

        # 跌破离场信号
        elif self.data.close[0] < self.low_channel[-1] and self.position:
            self.close()
            self.unit = 0
            self.log(f'清仓离场 | 价格：{self.data.close[0]:.2f} ')

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

def get_data(stock_code, start_date, end_date):
    # 获取历史日线数据
    print(stock_code,start_date,end_date)
    df = pro.daily(ts_code=stock_code, start_date=start_date, end_date=end_date)

    # Tushare 返回的数据格式处理
    df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
    df.set_index('trade_date', inplace=True)

    # 将数据列的名称修改为 backtrader 所需的格式
    df = df[['open', 'high', 'low', 'close', 'vol']]
    df.columns = ['open', 'high', 'low', 'close', 'volume']

    df=df.sort_index()
    # 返回数据，转换为backtrader数据格式
    file_path = stock_code+".csv"
    df.to_csv(file_path,index=True)
    return bt.feeds.PandasData(dataname=df)

# 策略执行示例
if __name__ == '__main__':
    cerebro = bt.Cerebro()

    start_date = datetime.now()-timedelta(days=180)
    start_date = start_date.strftime('%Y%m%d')
    end_date = datetime.now().strftime('%Y%m%d')

    # Create stock Data Feed
    stock_index = '300718.SZ'

    data = get_data(stock_index,start_date,end_date)
    cerebro.adddata(data)
    cerebro.addstrategy(TurtleStrategy)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0002)  # 加密货币低佣金

    print('初始净值: $%.2f' % cerebro.broker.getvalue())
    cerebro.run()
    print('最终净值: $%.2f' % cerebro.broker.getvalue())
    cerebro.plot(style='candlestick',bardown = 'green', barup = 'red')