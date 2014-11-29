#!/usr/bin/python

import argparse
import coinex_api
try:
    import configparser
except ImportError:
    # Python 2.7 compatbility
    import ConfigParser
    configparser = ConfigParser
import cryptsy_api
import exchange_api
import os
import sys
import time

def _FormatFloat(number):
    return ('%.8f' % number).rstrip('0').rstrip('.')

def _Log(message, *args):
    print('%s: %s' % (time.strftime('%c'), message % args))

def _LoadExchangeConfig(config, target_currencies, source_currencies, exchange_class, *keys):
    if not config.has_section(exchange_class.GetName()):
        return None

    args = {}
    for key in keys:
        if not config.has_option(exchange_class.GetName(), key):
            _Log('Missing %s.%s.', exchange_class.GetName(), key)
            return None
        args[key] = config.get(exchange_class.GetName(), key)

    try:
        exchange = exchange_class(**args)
    except exchange_api.ExchangeException as e:
        _Log('Failed to create %s instance: %s', exchange_class.GetName(), e)
        return None

    currencies = set(exchange.GetCurrencies())
    if not (currencies & set(target_currencies)):
        _Log('%s does not list any target_currencies, disabling.', exchange.GetName())
        return None
    elif source_currencies and not (currencies & set(source_currencies)):
        _Log('%s does not list any source_currencies, disabling.', exchange.GetName())
        return None
    else:
        _Log('Monitoring %s.', exchange_class.GetName())
        return exchange

verbose = True

parser = argparse.ArgumentParser(description='Script to auto-sell altcoins.')
parser.add_argument('-c', '--config', dest='config_path', default='~/.altcoin-autosell.config',
                    help='path to the configuration file')
parser.add_argument('-v', '--verbose', dest='verbose', action='store_const', const=True default=True)
args = parser.parse_args()

config = configparser.RawConfigParser()
try:
    config_path = os.path.expanduser(args.config_path)
    _Log('Using config from "%s".', config_path)
    with open(config_path) as config_file:
        config.readfp(config_file)
except IOError as e:
    _Log('Failed to read config: %s', e)
    sys.exit(1)
target_currencies = ([target_currency.strip() for target_currency in
                      config.get('General', 'target_currencies').split(',')] if
                     config.has_option('General', 'target_currencies') else ['BTC', 'LTC'])
_Log('Selling to %s.', target_currencies)
source_currencies = ([source_currency.strip() for source_currency in
                      config.get('General', 'source_currencies').split(',')] if
                     config.has_option('General', 'source_currencies') else [])
if source_currencies:
    _Log('Selling from %s.', source_currencies)
poll_delay = (config.getint('General', 'poll_delay') if
              config.has_option('General', 'poll_delay') else 60)
request_delay = (config.getint('General', 'request_delay') if
                 config.has_option('General', 'request_delay') else 1)

exchanges = [_LoadExchangeConfig(config, target_currencies, source_currencies,
                                 coinex_api.CoinEx, 'api_key', 'api_secret'),
             _LoadExchangeConfig(config, target_currencies, source_currencies,
                                 cryptsy_api.Cryptsy, 'api_private_key', 'api_public_key')]
exchanges = [exchange for exchange in exchanges if exchange is not None]
if not exchanges:
    _Log('No exchange sections defined!')
    sys.exit(1)

while True:
    for exchange in exchanges:
        try:
            balances = exchange.GetBalances()
        except exchange_api.ExchangeException as e:
            _Log('Failed to get %s balances: %s', exchange.GetName(), e)
            continue

        markets = exchange.GetMarkets()
        for (currency, balance) in balances.items():
            if (currency not in markets or
                (source_currencies and currency not in source_currencies)):
                continue
            currency_markets = markets[currency]

            for target_currency in target_currencies:
                if (not currency or
                    target_currency not in currency_markets or
                    (currency in target_currencies and
                     (target_currencies.index(target_currency) >=
                      target_currencies.index(currency)))):
                    continue
                market = currency_markets[target_currency]

                if verbose:
                    _Log("Looking at %s to %s market.",source_currency,target_currency)
                    _Log("Day's max = %s",market.GetDayMaxPrice())
                
                sell = False

                if balance < market.GetTradeMinimum() and market.GetPrices()[0] > 0:
                    if market.GetPrices()[0] > market.GetDayMaxPrice()*.93:
                        if market.GetPrices()[0] == market.GetPrices()[1] and market.GetPrices()[1] == market.GetPrices()[2] and market.GetPrices()[2] == market.GetPrices()[3] and market.GetPrices()[3] == market.GetPrices()[4] and market.GetPrices()[4] == market.GetPrices()[5]:
                                sell = True
                    elif market.GetPrices()[0] <= market.GetPrices()[1]:
                            sell = True
                
                if sell:
                #    currency = None  # don't try other markets
                #    continue

                    try:
                        orders = [order.GetPrice() for order in market.GetPublicOrders()[0]]
                        if not orders:
                            _Log('No buy orders for %s/%s on %s.',
                                 currency, target_currency, exchange.GetName())
                            continue
                        sell_price = max(orders)
                    except exchange_api.ExchangeException as e:
                        _Log('Failed to get public orders for %s/%s on %s: %s',
                             currency, target_currency, exchange.GetName(), e)
                        continue

                    try:
                        time.sleep(request_delay)
                        order = market.CreateOrder(False, balance, sell_price)
                        _Log('Created sell order %s for %s %s at %s %s on %s.',
                             order.GetOrderId(), _FormatFloat(balance), currency,
                             _FormatFloat(sell_price), target_currency, exchange.GetName())
                    except exchange_api.ExchangeException as e:
                        _Log('Failed to create sell order for %s %s at %s %s on %s: %s',
                             _FormatFloat(balance), currency, _FormatFloat(sell_price),
                             target_currency, exchange.GetName(), e)
                    finally:
                        currency = None  # don't try other markets

    time.sleep(poll_delay)
