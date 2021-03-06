import collections
import exchange_api
import hashlib
import hmac
import json
import time
import _thread

try:
    import http.client
    import urllib.request
    import urllib.error
    import urllib.parse
except ImportError:
    # Python 2.7 compatbility
    import httplib
    class http: client = httplib
    import urllib
    import urllib2
    class urllib: request = urllib2; error = urllib2; parse = urllib

class Market(exchange_api.Market):
    _TRADE_MINIMUMS = {('Points', 'BTC') : 0.1}

    def __init__(self, exchange, source_currency, target_currency, market_id, reverse_market, prices=[-1,-1,-1,-1,-1,-1,], day_max_price=0):
        exchange_api.Market.__init__(self, exchange)
        self._source_currency = source_currency
        self._target_currency = target_currency
        self._market_id = market_id
        self._reverse_market = reverse_market
        self._prices = prices
        self._day_max_price = day_max_price

    def GetSourceCurrency(self):
        return self._source_currency

    def GetTargetCurrency(self):
        return self._target_currency

    def GetTradeMinimum(self):
        return self._TRADE_MINIMUMS.get((self._source_currency, self._target_currency), 0.0000001)

    def GetPrices(self):
        return self._prices

    def GetDayMaxPrice(self):
        return self._day_max_price

    def GetPublicOrders(self):
        try:
            post_dict = {'marketid' : self._market_id}
            orders = self._exchange._Request('marketorders', post_dict)['return']
            return ([exchange_api.Order(self, 'N/A', True,
                                        float(order['quantity']),
                                        float(order['buyprice'])) for
                     order in orders.get('buyorders', [])],
                    [exchange_api.Order(self, 'N/A', False,
                                        float(order['quantity']),
                                        float(order['sellprice'])) for
                     order in orders.get('sellorders', [])])
        except (TypeError, LookupError) as e:
            raise exchange_api.ExchangeException(e)

    def CreateOrder(self, bid_order, amount, price):
        if self._reverse_market:
            bid_order = not bid_order
        post_dict = {'marketid' : self._market_id,
                     'ordertype' : 'Buy' if bid_order else 'Sell',
                     'quantity' : amount,
                     'price' : max(0.0000001, price)}
        try:
            order_id = self._exchange._Request('createorder', post_dict)['orderid']
            return exchange_api.Order(self, order_id, bid_order, amount, price)
        except (TypeError, LookupError) as e:
            raise exchange_api.ExchangeException(e)

class Cryptsy(exchange_api.Exchange):
    @staticmethod
    def GetName():
        return 'Cryptsy'

    def __init__(self, api_public_key, api_private_key):
        self.api_auth_url = 'https://api.cryptsy.com/api'
        self.api_headers = {'Content-type' : 'application/x-www-form-urlencoded',
                            'Accept' : 'application/json',
                            'User-Agent' : 'autocoin-autosell'}
        self.api_public_key = api_public_key
        self.api_private_key = api_private_key.encode('utf-8')

        self._markets = collections.defaultdict(dict)
        try:
            self._LoadMarkets();
        except (TypeError, LookupError) as e:
            raise exchange_api.ExchangeException(e)

        _thread.start_new_thread(self._MarketRefreshLoop, ())

    def _LoadMarkets(self):
            try:
                for market in self._Request('getmarkets')['return']:
                    market1 = Market(self, market['primary_currency_code'],
                            market['secondary_currency_code'], market['marketid'], False)
                    self._markets[market1.GetSourceCurrency()][market1.GetTargetCurrency()] = market1
                    market2 = Market(self, market['secondary_currency_code'],
                            market['primary_currency_code'], market['marketid'], True)
                    self._markets[market2.GetSourceCurrency()][market2.GetTargetCurrency()] = market2
            except ExchangeException as e:
                _Log('Failed to get market: %s', e)

    def _RefreshMarkets(self):
        try:
            for market in self._Request('getmarkets')['return']:
                prices = self._markets[market['primary_currency_code']][market['secondary_currency_code']].GetPrices()
                prices.insert(0,float(market['last_trade']))
                prices.pop()
                market1 = Market(self, market['primary_currency_code'],
                        market['secondary_currency_code'], market['marketid'], False, prices, float(market['high_trade']))
                self._markets[market1.GetSourceCurrency()][market1.GetTargetCurrency()] = market1

                prices = self._markets[market['secondary_currency_code']][market['primary_currency_code']].GetPrices()
                prices.insert(0,1/float(market['last_trade']))
                prices.pop()
                if float(market['high_trade']) > 0:
                    highval = 1/float(market['high_trade'])
                else:
                    highval = 0
                market2 = Market(self, market['secondary_currency_code'],
                        market['primary_currency_code'], market['marketid'], True, prices, highval)
                self._markets[market2.GetSourceCurrency()][market2.GetTargetCurrency()] = market2
        except ExchangeException as e:
            _Log('Failed to get market: %s', e)

    def _MarketRefreshLoop(self):
        while True:
            time.sleep(5)
            self._RefreshMarkets()

    def _Request(self, method, post_dict=None):
        if post_dict is None:
            post_dict = {}
        post_dict['method'] = method
        post_dict['nonce'] = int(time.time())
        post_data = urllib.parse.urlencode(post_dict).encode('utf-8')
        digest = hmac.new(self.api_private_key, post_data, hashlib.sha512).hexdigest()
        headers = {'Key' : self.api_public_key,
                   'Sign': digest}
        headers.update(self.api_headers.items())

        try:
            request = urllib.request.Request(self.api_auth_url, post_data, headers)
            response = urllib.request.urlopen(request)
            try:
                response_json = json.loads(response.read().decode('utf-8'))
                if 'error' in response_json and response_json['error']:
                    raise exchange_api.ExchangeException(response_json['error'])
                return response_json
            finally:
                response.close()
        except (urllib.error.URLError, urllib.error.HTTPError, http.client.HTTPException,
                ValueError) as e:
            raise exchange_api.ExchangeException(e)

    def GetCurrencies(self):
        return self._markets.keys()

    def GetMarkets(self):
        return self._markets

    def GetBalances(self):
        try:
            return {currency: float(balance) for currency, balance in
                    self._Request('getinfo')['return']['balances_available'].items()}
        except (TypeError, LookupError, ValueError, AttributeError) as e:
            raise exchange_api.ExchangeException(e)
