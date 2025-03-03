# 数据接口
import tushare as ts

# 基础模块
from datetime import datetime,timedelta
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import time

# 回测框架
import backtrader as bt

# 设置Tushare Token
ts.set_token('0ff27db3b933751cc13e959f62e7147d441325b4fdc2a4fd1b0aacfe')
pro = ts.pro_api()

class Strategy_wave1(bt.Strategy):
    params = (
        ('printlog', False),
        ('smoothing_period', 5),
        ('stack_len', 3),
    )

    def log(self, txt, dt=None, doprint=False):
        ''' Logging function fot this strategy'''
        if self.params.printlog or doprint:
            dt = dt or self.datas[0].datetime.date(0)
            print('%s: %s' % (dt.isoformat(), txt))
            # with open('log.txt', 'a') as file:
            # file.write('%s: %s \n' % (dt.isoformat(), txt))

    def __init__(self):
        #self.log("init")
        # Keep a reference to the "close" line in the data[0] dataseries
        self.dataclose = self.datas[0].close
        self.buyprice = None
        self.sellprice = None

        # Add a MovingAverageSimple indicator
        self.sma = bt.indicators.SimpleMovingAverage(
            self.datas[0], period=self.params.smoothing_period)
        # Add a singal stack
        self.stack = [0] * self.params.stack_len

    def notify_order(self, order):
        #self.log("notify_order")
        if order.status in [order.Submitted, order.Accepted]:
            # Buy/Sell order submitted/accepted to/by broker - Nothing to do
            return

        # Check if an order has been completed
        # Attention: broker could reject order if not enough cash
        if order.status in [order.Completed]:
            if order.isbuy():

                self.log('BUY EXECUTED, Price: %.2f, Lot:%i, Cash: %i, Value: %i' %
                         (order.executed.price,
                          order.executed.size,
                          self.broker.get_cash(),
                          self.broker.get_value()))
                self.buyprice = order.executed.price

            else:  # Sell
                self.log('SELL EXECUTED, Price: %.2f, Lot:%i, Cash: %i, Value: %i' %
                         (order.executed.price,
                          -order.executed.size,
                          self.broker.get_cash(),
                          self.broker.get_value()))
                self.sellprice = order.executed.price

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log('Order Canceled/Margin/Rejected')

        # Write down: no pending order
        # self.order = None

    def notify_trade(self, trade):
        #self.log("notify_trade")
        if not trade.isclosed:
            return

        self.log('OPERATION PROFIT, GROSS %.2f, NET %.2f' %
                 (trade.pnl, trade.pnlcomm))

    def next(self):
        #self.log('next func')
        # Check if an order is pending ... if yes, we cannot send a 2nd one
        # if self.order:
        #    return

        if len(self.sma) <= self.params.stack_len:
            return

        for i in range(1, self.params.stack_len + 1):
            self.stack[-i] = 1 if self.sma[-i + 1] - self.sma[-i] > 0 else -1

        self.log(self.stack)
        self.log([self.sma[-2],self.sma[-1],self.sma[0]])

        # Wave Buy Signal
        if self.stack[-1] == 1 and sum(self.stack) in [-1 * (self.params.stack_len - 2),
                                                       -1 * (self.params.stack_len - 3)]:
            if self.buyprice is None:
                self.log('BUY CREATE, Price: %.2f, Lots: %i, Current Position: %i' % (self.dataclose[0],
                                                                                      100,
                                                                                      self.getposition(self.data).size))
                self.buy(size=100)
            elif self.dataclose > self.buyprice:
                self.log('BUY CREATE, Price: %.2f, Lots: %i, Current Position: %i' % (self.dataclose[0],
                                                                                      100,
                                                                                      self.getposition(self.data).size))
                self.buy(size=100)

        # Wave Sell Singal
        elif self.stack[-1] == -1 and sum(self.stack) in [1 * (self.params.stack_len - 2),
                                                          1 * (self.params.stack_len - 3)]:
            if self.getposition(self.data).size > 0:
                self.log('SELL CREATE (Close), Price: %.2f, Lots: %i' % (self.dataclose[0],
                                                                         self.getposition(self.data).size))
                self.close()

        # # Wave Buy Signal
        # if self.stack == [-1,1,1] or self.stack == [-1,-1,1]:
        #     if self.buyprice is None:
        #         self.log('BUY CREATE, Price: %.2f, Lots: %i, Current Position: %i' % (self.dataclose[0],
        #                                                                               100,
        #                                                                               self.getposition(self.data).size))
        #         self.buy(size=100)
        #     elif self.dataclose > self.buyprice:
        #         self.log('BUY CREATE, Price: %.2f, Lots: %i, Current Position: %i' % (self.dataclose[0],
        #                                                                               100,
        #                                                                               self.getposition(self.data).size))
        #         self.buy(size=100)
        #
        # # Wave Sell Singal
        # elif self.stack == [1,1,-1] or self.stack == [1,-1,-1]:
        #     if self.getposition(self.data).size > 0:
        #         self.log('SELL CREATE (Close), Price: %.2f, Lots: %i' % (self.dataclose[0],
        #                                                                  self.getposition(self.data).size))
        #         self.close()
        #

        # Keep track of the created order to avoid a 2nd order
        # self.order = self.sell(size = self.getposition(data).size - opt_position)

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

if __name__ == '__main__':
    # Create a cerebro entity
    cerebro = bt.Cerebro()

    # Add a strategy
    strats = cerebro.addstrategy(Strategy_wave1, printlog=True, smoothing_period=5)

    start_date = datetime.now()-timedelta(days=365)
    start_date = start_date.strftime('%Y%m%d')
    end_date = datetime.now().strftime('%Y%m%d')

    # Create stock Data Feed
    stock_index = '002057.SZ'

    data = get_data(stock_index,start_date,end_date)

    # Add the index Data Feed to Cerebo
    cerebro.adddata(data)

    # Set cash inside the strategy
    cerebro.broker = bt.brokers.BackBroker(coc=True)
    cerebro.broker.setcash(2000)

    # Set commission
    cerebro.broker.setcommission(commission=0.001)

    # Print out the starting conditions
    start_value = cerebro.broker.getvalue()
    print('Starting Portfolio Value: %.2f' % cerebro.broker.getvalue())

    # Run over everything
    cerebro.run()

    # Print out the final result
    final_value = cerebro.broker.getvalue()
    print('Final Portfolio Value: %.2f' % cerebro.broker.getvalue())
    print('Net Profit: %.2f%%' % ((final_value - start_value) / start_value * 100))
    # 绘制图表
    #cerebro.plot()