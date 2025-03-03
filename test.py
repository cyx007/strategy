import tushare as ts
import backtrader as bt
import pandas as pd
from datetime import datetime
import matplotlib.pyplot as plt

# 设置Tushare的Token
ts.set_token('0ff27db3b933751cc13e959f62e7147d441325b4fdc2a4fd1b0aacfe')
pro = ts.pro_api()


# 获取股票历史数据的函数
def get_data(stock_code, start_date, end_date):
    # 获取历史日线数据
    #print(stock_code,start_date,end_date)
    df = pro.daily(ts_code=stock_code, start_date=start_date, end_date=end_date)

    # Tushare 返回的数据格式处理
    df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
    df.set_index('trade_date', inplace=True)

    # 将数据列的名称修改为 backtrader 所需的格式
    df = df[['open', 'high', 'low', 'close', 'vol']]
    df.columns = ['open', 'high', 'low', 'close', 'volume']

    df=df.sort_index()
    # 返回数据，转换为backtrader数据格式
    #print(df)
    return bt.feeds.PandasData(dataname=df)

# 获取3只小盘股的历史数据
stock_codes = ['300001.SZ']
start_date = '20240101'
end_date = datetime.now().strftime('%Y%m%d')  # 当前时间

# 创建策略：双均线策略
class DoubleSMA(bt.Strategy):
    params = (
        ('sma_short', 5),  # 短期SMA
        ('sma_long', 20),  # 长期SMA
    )
    def log(self, txt, dt=None):
        # 记录策略的执行日志
        dt = dt or self.datas[0].datetime.date(0)
        print('%s, %s' % (dt.isoformat(), txt))

    def __init__(self):
        self.sma_short = bt.indicators.SimpleMovingAverage(self.data.close, period=self.params.sma_short)
        self.sma_long = bt.indicators.SimpleMovingAverage(self.data.close, period=self.params.sma_long)

    def next(self):
        #help(self.sma_short)
        if self.sma_short > self.sma_long and not self.position:
            self.buy()  # 买入
        elif self.sma_short < self.sma_long and self.position:
            self.sell()  # 卖出

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            # broker 提交/接受了，买/卖订单则什么都不做
            return
        # 检查一个订单是否完成
        # 注意: 当资金不足时，broker会拒绝订单
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f"买入 {order.executed.size} 股，价格：{order.executed.price},总价：{order.executed.value}")
            elif order.issell():
                self.log(f"卖出 {order.executed.size} 股，价格：{order.executed.price},总价：{order.executed.value}")

                # 记录当前交易数量
            self.bar_executed = len(self)

class TestStrategy(bt.Strategy):
    def log(self, txt, dt=None):
        # 记录策略的执行日志
        dt = dt or self.datas[0].datetime.date(0)
        print('%s, %s' % (dt.isoformat(), txt))

    def __init__(self):
        # 保存收盘价的引用
        self.dataclose = self.datas[0].close
        # 跟踪挂单
        self.order = None

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            # broker 提交/接受了，买/卖订单则什么都不做
            return
        # 检查一个订单是否完成
        # 注意: 当资金不足时，broker会拒绝订单
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f"买入 {order.executed.size} 股，价格：{order.executed.price}")
            elif order.issell():
                self.log(f"卖出 {order.executed.size} 股，价格：{order.executed.price}")

                # 记录当前交易数量
            self.bar_executed = len(self)

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log('订单取消/保证金不足/拒绝')

            # 其他状态记录为：无挂起订单
        self.order = None

    # 交易状态通知，一买一卖算交易
    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log('交易利润, 毛利润 %.2f, 净利润 %.2f' %
        (trade.pnl, trade.pnlcomm))

    def next(self):
        # 记录收盘价
        self.log('next func: Close, %.2f' % self.dataclose[0])

        # 如果有订单正在挂起，不操作
        if self.order:
            return

        # 如果没有持仓则买入
        if not self.position:
            # 今天的收盘价 < 昨天收盘价
            if self.dataclose[0] < self.dataclose[-1]:
                # 昨天收盘价 < 前天的收盘价
                if self.dataclose[-1] < self.dataclose[-2]:
                    # 买入
                    self.log('买入, %.2f' % self.dataclose[0])
                    # 跟踪订单避免重复
                    self.order = self.buy()
        else:
            # 如果已经持仓，且当前交易数据量在买入后5个单位后
            if len(self) >= (self.bar_executed + 5):
                # 全部卖出
                self.log('卖出, %.2f' % self.dataclose[0])
                # 跟踪订单避免重复
                self.order = self.sell()


# 创建回测引擎
cerebro = bt.Cerebro()

# 添加数据并设置策略
for stock_code in stock_codes:
    stock_data = get_data(stock_code, start_date, end_date)
    cerebro.adddata(stock_data, name=stock_code)

cerebro.addstrategy(DoubleSMA)
#cerebro.addstrategy(TestStrategy)

#cerebro.addsizer(bt.sizers.FixedSize, stake=100)
#设置每次操作50%资金
cerebro.addsizer(bt.sizers.PercentSizer, percents=50)

# 设置初始资金
cerebro.broker.set_cash(100000)

# 设置手续费
cerebro.broker.setcommission(commission=0.001)

# 打印回测前的信息
print(f'初始资金: {cerebro.broker.getvalue()}')

# 添加交易统计分析器
cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trade_analyzer')

# 运行回测
result = cerebro.run()

# 打印回测后的信息
print(f'结束资金: {cerebro.broker.getvalue()}')

# 打印交易统计信息
trade_analyzer = result[0].analyzers.trade_analyzer.get_analysis()

# 检查交易统计，避免 KeyError
print('交易统计:')
print(f"总交易数: {trade_analyzer.get('total', {}).get('total', 0)}")
print(f"赢利交易数: {trade_analyzer.get('won', {}).get('total', 0)}")
print(f"亏损交易数: {trade_analyzer.get('lost', {}).get('total', 0)}")
print(f"平均盈利: {trade_analyzer.get('won', {}).get('average', 0)}")
print(f"平均亏损: {trade_analyzer.get('lost', {}).get('average', 0)}")


# 绘制图表
cerebro.plot()
