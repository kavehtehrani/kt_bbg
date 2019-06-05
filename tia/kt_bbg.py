"""
# set of wrapper functions for python/bloomberg functionality
# can work on localhost terminal (personal PC) or bpipe terminal
# based on the tia package

Kaveh Tehrani (kavehtheblacksmith@gmail.com)
"""

import pandas as pd
import datetime
import scipy.interpolate
import datetime
import tia.bbg
import re
from functools import lru_cache
from typing import Tuple, Union, List


class BBG:
    def __init__(self, host='localhost', port=8194, bpipe=False, str_bpipeappname=''):
        if bpipe:
            if not host:
                raise ValueError('Need to pass in the IP address of the bpipe terminal.')

            self.dm = tia.bbg.v3api.Terminal(host=host, port=port, bpipe=True, str_bpipeappname=str_bpipeappname)
        else:
            self.dm = tia.bbg.v3api.Terminal(host=host, port=port)

    @lru_cache()
    def get_futures_curve(self, str_ticker: str, b_include_historical: bool = False) -> pd.DataFrame:
        # futures curve for a ticker (CT)
        futures_curve = self.dm.get_reference_data(str_ticker, 'fut_chain',
            'include_expired_contracts=Y' if b_include_historical else None).as_frame().iloc[0].loc['fut_chain']

        futures_curve = self.dm.get_reference_data(futures_curve.iloc[:, 0], ['fut_month_yr', 'last_tradeable_dt']).as_frame()
        futures_curve['month'] = futures_curve.iloc[:, 0].map(lambda x: datetime.datetime.strptime(x, '%b %y').month)
        futures_curve['year'] = futures_curve.iloc[:, 0].map(lambda x: datetime.datetime.strptime(x, '%b %y').year)
        futures_curve['days_to_expiry'] = (futures_curve['last_tradeable_dt'] - pd.Timestamp.now()).dt.days

        futures_curve = futures_curve.sort_values('last_tradeable_dt')

        return futures_curve

    @lru_cache()
    def get_option_futures_chain(self, str_ticker: str)  -> pd.DataFrame:
        opt_futures_curve = self.dm.get_reference_data(str_ticker, 'opt_futures_chain_dates').as_frame()\
            .iloc[0].loc['opt_futures_chain_dates']
        opt_futures_curve.sort_values('Option Expiration', inplace=True)

        return opt_futures_curve

    def get_option_spread(self, str_ticker: str, b_complete_spread: bool = True) -> pd.DataFrame:
        """
        option spread for a ticker (OMON)
        """
        option_spread = self.dm.get_reference_data(str_ticker, 'opt_chain').as_frame().iloc[0].loc['opt_chain']
        option_spread.set_index(option_spread.columns[0], inplace=True)

        if b_complete_spread:
            option_spread = self.get_option_fields(option_spread.index)

        # option_spread.to_clipboard()
        return option_spread

    def get_option_fields(self, str_ticker: str) -> pd.DataFrame:
        # default set of fields
        dict_fields = {'last_price': 'last_price',
                       'bid': 'bid',
                       'ask': 'ask',
                       'ivol_bid': 'ivol_bid',
                       'ivol_mid': 'ivol_mid',
                       'ivol_ask': 'ivol_ask',
                       'delta_mid_rt': 'delta',
                       'gamma': 'gamma',
                       'vega': 'vega',
                       'opt_theta': 'theta',
                       'rho': 'rho',
                       'opt_cont_size': 'opt_cont_size',
                       'opt_undl_px': 'underlying_price',
                       'underlying_security_des': 'underlying_ticker',
                       'opt_strike_px': 'strike',
                       'opt_put_call': 'pc'
                       }

        # check if it's single option or an option chain
        if isinstance(str_ticker, str):
            str_type = str_ticker.split()[-1]
        else:
            str_type = str_ticker[0].split()[-1]

        if str_type.lower() == 'equity':
            dict_append = { 'opt_expire_dt': 'last_tradeable_dt' }
        elif str_type.lower() == 'comdty':
            dict_append = { 'opt_expire_dt': 'last_tradeable_dt',
                            'current_contract_month_yr': 'cont_month_year' }
        else:
            raise TypeError(f'{str_type} is not currently implemented.')

        dict_fields.update(dict_append)
        option_ret = pd.DataFrame(index=[str_ticker])
        option_ret = self.dm.get_reference_data(str_ticker, dict_fields).as_frame()
        option_ret.rename(columns=dict_fields, inplace=True)

        # adjustments and new additions
        if 'cont_month_year' in option_ret.columns:
            option_ret['month'] = option_ret['cont_month_year'].map(lambda x: datetime.datetime.strptime(x, '%b %y').month)
            option_ret['year'] = option_ret['cont_month_year'].map(lambda x: datetime.datetime.strptime(x, '%b %y').year)

        # take out COMB out of the bbg ticker
        option_ret['underlying_ticker'] = option_ret['underlying_ticker'].apply(lambda x: x.replace(' COMB', ''))

        return option_ret

    @lru_cache()
    def get_general_fields(self, str_ticker: str, str_fields: Tuple = ('px_last'),
                           ignore_security_error=0, ignore_field_error=0, **overrides) -> pd.DataFrame:

        return self.dm.get_reference_data(str_ticker, str_fields,
                                          ignore_security_error=0, ignore_field_error=0, **overrides).as_frame()

    @lru_cache()
    def get_general_field_single(self, str_ticker: str, str_field: str) -> pd.DataFrame:
        ret_val = self.dm.get_reference_data(str_ticker, str_field).as_frame().iloc[0, 0]
        if str_field.lower() == 'underlying_security_des':
            ret_val = ret_val.replace(' COMB', '')
        return ret_val

    @lru_cache()
    def get_historical_quick(self, str_tickers: Union[Tuple, str], str_fields=('px_last'),
                             dt_beg: Union[datetime.datetime, str] = None,
                             dt_end: Union[datetime.datetime, str] = None) -> pd.DataFrame:
        df_ret = self.dm.get_historical(str_tickers, str_fields, dt_beg, dt_end).as_frame()

        # if only one security, drop multiindex
        if isinstance(str_tickers, str):
            df_ret.columns = df_ret.columns.droplevel(0)

        return df_ret

    @lru_cache()
    def get_historical_quick_single(self, str_tickers: Union[Tuple, str], str_fields: Union[Tuple, str],
                                    dt_tgt: Union[datetime.datetime, str]):
        return self.dm.get_historical(str_tickers, str_fields, dt_tgt, dt_tgt).as_frame().iloc[0, 0]

    @lru_cache()
    def convert_bbg_tenor_tag(self, str_tag: str) -> str:
        (num, letter) = split_letters_numbers(str_tag)
        num = int(num)

        if letter.lower() == 'd':           mult = 1/365
        elif letter.lower() == 'w':         mult = 1/52
        elif letter.lower() == 'm':         mult = 1/12
        elif letter.lower() == 'y':         mult = 1
        else:                               raise(TypeError('cannot find appropriate letter for tenor'))

        return num*mult

    def get_historical(self, sids: Union[List, Tuple, str], fields: Union[List, Tuple, str],
                       dt_beg: Union[datetime.datetime, str], dt_end: Union[datetime.datetime, str],
                       period: str = 'DAILY', **overrides):

        df_ret = self.dm.get_historical(sids, fields, dt_beg, dt_end, period,
                                        ignore_security_error=0, ignore_field_error=0, **overrides).as_frame()

        return df_ret

    @lru_cache()
    def get_ois(self, date: Union[datetime.datetime, str], tgt_tenor: float,
                str_currency: str = 'usd', num_side: str = 'mid') -> Tuple[float, pd.DataFrame]:

        # see if it exists in
        if str_currency.lower() == 'usd':       str_curve = 'YCSW0042 Index'
        elif str_currency.lower() == 'eur':     str_curve = 'YCSW0133 Index'
        elif str_currency.lower() == 'gbp':     str_curve = 'YCSW0141 Index'
        elif str_currency.lower() == 'cad':     str_curve = 'YCSW0147 Index'

        if type(date) is not str:
            date = date.strftime('%Y%m%d')

        d = self.dm.get_reference_data(str_curve, 'curve_tenor_rates', curve_date=date).as_frame()
        ret_curve = d.loc[d.index[0], 'curve_tenor_rates']
        ret_curve.rename(columns={'Tenor': 'tenor', 'Tenor Ticker': 'ticker', 'Ask Yield': 'ask', 'Mid Yield': 'mid',
                                  'Bid Yield': 'bid', 'Last Update': 'last_update'}, inplace=True)

        # convert the bbg indicator to years
        ret_curve['tenor']  = [ self.convert_bbg_tenor_tag(l) for l in ret_curve['tenor'] ]

        # interploate for the target rate
        if tgt_tenor < min(ret_curve['tenor']):
            ret_rate = float(ret_curve[ret_curve['tenor'] == min(ret_curve['tenor'])][num_side])
        else:
            ret_rate = scipy.interpolate.interp1d(list(ret_curve['tenor']),
                                                  list(ret_curve[num_side]),
                                                  kind='cubic')(tgt_tenor)
        return ret_rate, ret_curve

    @lru_cache()
    def get_options_underlying(self, str_ticker: str) -> str:
        return self.dm.get_reference_data(str_ticker, 'opt_undl_ticker').as_frame().iloc[0].loc['opt_undl_ticker']

    # ensuring consistency of referring to fields across applications
    bbg_field_matching = { 'futures':
                               { 'bid': 'px_bid',
                                 'ask': 'px_ask',
                                 'mid': 'px_mid',
                                 'last': 'px_last',
                                 'settle': 'px_settle',
                                 'volume': 'volume',
                                 'open_interest': 'open_int',
                                 }
                           }


def split_letters_numbers(str_in):
    ret = re.split(r'(\d*\.\d+|\d+)', str_in)
    if '' in ret:
        ret.remove('')
    return ret


def insert_year_into_ticker(str_ticker: str, str_year: str) -> str:
    str_year = str(str_year)
    mod_ticker = split_letters_numbers(str_ticker)
    if len(mod_ticker) < 3:
        raise IOError('the ticker passed in needs to conform to bbg standards.')
    if not mod_ticker[1].isdigit():
        raise IOError('cannot find year indicator in the ticker.')
    if len(str_year) != 4:
        raise IOError('year must be a four digit input')

    mod_ticker[1] = str_year[2] + mod_ticker[1]
    mod_ticker = ''.join(mod_ticker)

    return mod_ticker


if __name__ == '__main__':
    # All diagnostics code below

    c = BBG()

    if 1:
        spot1 = c.get_general_fields('EUR Curncy', 'PX_LAST').iloc[0, 0]
        print(spot1)

        fwd1 = c.get_general_fields('KRW Curncy', 'FWD_CURVE').iloc[0, 0]
        print(fwd1)

        fwd3 = c.get_general_fields('KRW Curncy', 'FWD_CURVE', ignore_security_error=0, ignore_field_error=0,
                                    REFERENCE_DATE='20190502', FWD_CURVE_QUOTE_FORMAT='OUTRIGHT').iloc[0, 0]
        print(fwd3)

    if 1:
        h1 = c.get_historical('EUR1W BGN Curncy', 'PX_LAST',
                              '20050101', '20190101', period='DAILY', FWD_CURVE_QUOTE_FORMAT='OUTRIGHT')
        print(h1)

        h2 = c.get_historical('GBP1W BGN Curncy', 'PX_LAST',
                              '20050101', '20190101', period='DAILY', FWD_CURVE_QUOTE_FORMAT='OUTRIGHT')
        print(h2)

    if 1:
        df_opt_spread = c.get_option_spread('CLA Comdty')

    if 1:
        df_hist_px = c.get_historical_quick('CLA Comdty', str_fields=('px_last', 'volume'),
                                            dt_beg='20170101', dt_end=datetime.datetime.now().strftime('%Y%m%d'))
        print(df_hist_px)

    if 1:
        tgt_rate, ret_curve = c.get_ois(datetime.datetime.now().strftime('%Y%m%d'), 1/12,
                                        str_currency='usd', num_side='mid')
        print(tgt_rate)
        print(ret_curve)
    if 1:
        fut_curve = c.get_futures_curve('CLA Comdty', b_include_historical=True)
        print(fut_curve)

    print('All done.')

