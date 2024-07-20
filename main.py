#!/usr/bin/python
import argparse
import sys, os
import pdfplumber
import re
from pandas import DataFrame, to_datetime
import numpy as np
from datetime import datetime, timedelta
import scipy.optimize

basedir = os.path.dirname(__file__)

ALL_TXN = "all-txn"
SUMMARY = "summary"
SUMMARY_REGEX = re.compile (
	                r"(Closing Unit Balance: )([\d,.]+)( NAV on )([^:]+)(: INR )([\d,.]+)( Total Cost Value: )([\d,.]+)( Market Value on )([^:]+)(: INR )([\d,.]+)"
                )
TXN_REGEX = re.compile(
                r"(^\d{2}-\w{3}-\d{4})(\s.+?\s(?=[\d(]))([\d\(]+[,.]\d+[.\d\)]+)(\s[\d\(\,\.\)]+)(\s[\d\,\.]+)(\s[\d,\.]+)"
            )
# TXN with only amount, but units do not change
NON_UNITS_TXN = re.compile (
                r"(^\d{2}-\w{3}-\d{4})(\s.+?\s(?=[\d(]))([\d\(]+[,.]\d+[.\d\)]+)"
            )

class WelcomeScreen():
    def __init__(self):
        # init cli 
        print("CAMS 2 CSV CLI version")
        self.rows_map = {
            ALL_TXN : [],
            SUMMARY : [],
        }
        self.headers = {
            ALL_TXN : [
                    "Folio",
                    "Fund_name",
                    "Date",
                    "Description",
                    "Amount",
                    "Units",
                    "Price",
                    "Unit_balance",
                ],
            SUMMARY : [
                    "Folio",
                    "Fund_name",
                    "Date",
                    "Closing_unit_balance",
                    "Nav",
                    "Total_cost_value",
                    "Market_value",
                    "Xirr",
                    "Age"
                ]
        }

    def file_processing(self, file_path, doc_pwd):
        final_text = ""

        if not len(file_path) == 0:
            # try:
            with pdfplumber.open(file_path, password=doc_pwd) as pdf:
                for i in range(len(pdf.pages)):
                    txt = pdf.pages[i].extract_text()
                    final_text = final_text + "\n" + txt
                pdf.close()
            print("EXTRACTING")
            self.extract_text(final_text)

            # except Exception as e:
            #     print("Error in reading file: ", e , "\n")
        else:
            print("Please select your CAMS PDF file..\n")

    def extract_text(self, doc_txt):
        # Defining RegEx patterns
        folio_pat = re.compile(
            r"(^Folio No:\s\d+)", flags=re.IGNORECASE)  # Extracting Folio information
        fund_name = re.compile(r".*[Fund].*ISIN.*", flags=re.IGNORECASE)
        fund_txns = 0
        total_txn = 0
        for i in doc_txt.splitlines():
            
            if fund_name.match(i):
                fun_name = i
                fund_txns = 0

            if folio_pat.match(i):
                folio = i.strip()

            txt = TXN_REGEX.search(i)
            no_unit_txn = NON_UNITS_TXN.search(i)
            if txt:
                date = txt.group(1)
                description = txt.group(2)
                amount = txt.group(3)
                units = txt.group(4)
                price = txt.group(5)
                unit_bal = txt.group(6)
                # In cases of IDCW Re-investment, ignore the amt and add it 
                # to description
                description,amount = self.handle_idcw_reinvest_if_reqd(description,amount)

                self.rows_map[ALL_TXN].append(
                    [
                        folio, fun_name, date, description, amount,
                        units, price, unit_bal
                    ]
                )
                fund_txns += 1
                total_txn += 1
            elif no_unit_txn:
                # TXNS where units dont change
                date = no_unit_txn.group(1)
                description = no_unit_txn.group(2)
                amount = no_unit_txn.group(3)
                if "Stamp Duty" in description:
                    self.rows_map[ALL_TXN].append(
                        [
                            folio, fun_name, date, description, amount,
                            '0', '0', '0'
                        ]
                    )
                elif ("IDCW" in description) and ("per unit" in description):
                    if '(' not in amount: 
                        amount = '('+amount+')'
                    row = [
                            folio, fun_name, date, description, amount,
                            '0', '0', '0'
                        ]
                    print(row,"\n")
                    self.rows_map[ALL_TXN].append(
                        row
                    )

            elif i.startswith("Closing"):
                self.summerize_current_fund(fun_name,folio,i)
               
        self.txn_df = self.write_to_op_file(ALL_TXN)
        # xirr

        self.write_to_op_file(SUMMARY)  
    
    def handle_idcw_reinvest_if_reqd(self,description,amt):
        if "IDCW Reinvested" in description:
            description += (" - RS: "+amt)
            amt = "0"
        return description,amt

    def summerize_current_fund(self, fund, folio, summary: str):
        summary_items = SUMMARY_REGEX.search(summary)
        if summary_items:
            closing_units = summary_items.group(2)
            date = summary_items.group(4)
            nav = summary_items.group(6)
            cost = summary_items.group(8)
            market_val = summary_items.group(12)
            self.rows_map[SUMMARY].append(
                [
                    folio, fund, date, closing_units, nav,
                    cost, market_val, 0.00, 0
                ]
            )

    def write_to_op_file(self, op_type):
        date_str = datetime.now().strftime("%d_%m_%Y_%H_%M")
        fname_tmpl = f'CAMS_data_{date_str}.csv'
        save_file = os.path.join(".",op_type +"-"+ fname_tmpl +".csv")

        rows = self.rows_map[op_type]
        df = DataFrame (rows,columns=self.headers[op_type])
        if op_type == ALL_TXN:
            self.clean_txt(df.Amount)
            self.clean_txt(df.Units)
            self.clean_txt(df.Price)
            self.clean_txt(df.Unit_balance)

            df.Amount = df.Amount.astype("float")
            df.Units = df.Units.astype("float")
            df.Price = df.Price.astype("float")
            df.Unit_balance = df.Unit_balance.astype("float")
        elif op_type == SUMMARY:
            self.clean_txt(df.Nav)
            self.clean_txt(df.Closing_unit_balance)
            self.clean_txt(df.Total_cost_value)
            self.clean_txt(df.Market_value)

            df.Nav = df.Nav.astype("float")
            df.Closing_unit_balance = df.Closing_unit_balance.astype("float")
            df.Total_cost_value = df.Total_cost_value.astype("float")
            df.Market_value = df.Market_value.astype("float")
            self.sumarry_df = df
            # Compute XIRR
            xirrs,ages = self.compute_fund_xirrs_ages()
            df['Xirr'] = xirrs
            df['Age'] = ages
            # Overall summary
            summary = self.overll_summary()
            df.loc[len(df)] = summary
        else:
            sys.stderr.write("Unkown type: " + str(op_type))
        
        try:
            df.to_csv(save_file, index=False)
            print(
                "Process completed, file saved in current dir"
            )
        except Exception as e:
            sys.stderr.write(str(e))

        return df 
    
    def overll_summary(self):
        self.txn_df["Date"] = to_datetime(self.txn_df["Date"],
                                            format="%d-%b-%Y",
                                            dayfirst=True)
        sorted_df = self.txn_df.sort_values(by="Date")
        # First txn date
        closing_dates = to_datetime(self.sumarry_df["Date"],
                                            format="%d-%b-%Y",
                                            dayfirst=True).tolist()
        closing_date = sorted(closing_dates)[-1]
        closing_bal = self.sumarry_df["Closing_unit_balance"].sum()
        sorted_dates = sorted_df["Date"].tolist()
        sorted_dates.append(closing_date)

        sorted_txns = sorted_df["Amount"].tolist()
        total_value = self.sumarry_df["Market_value"].sum()
        sorted_txns.append(0-total_value)
        total_age,closing_date = self.calculate_fund_age_days_and_closing_date(closing_bal,sorted_dates,
                                                 sorted_txns)

        total_invested = self.sumarry_df["Total_cost_value"].sum()

        net_xirr = xirr(sorted_txns,sorted_dates,total_age,
                        total_invested,total_value) 
        net_xirr = net_xirr*100

        summary_line = [
            "Total", "Summary",closing_date.strftime('%d-%B-%y'),closing_bal,
            (total_value)/closing_bal,total_invested,total_value,net_xirr,total_age
        ]
        print(summary_line)
        return summary_line
               

    def clean_txt(self, x):
        x.replace(r",", "", regex=True, inplace=True)
        x.replace(r"\(", "-", regex=True, inplace=True)
        x.replace(r"\)", " ", regex=True, inplace=True)
        return x

    def calculate_fund_age_days_and_closing_date(self,closing_bal, dates, txns):
        if closing_bal < 0.01:
            closing_bal = 0
        
        if len(dates) == len(txns) == 1:
            # only summary available
            return timedelta().days,dates[0]
        elif len(dates) == len(txns) and len(dates) > 1:
            # atleast 1 txn and summary available
            if closing_bal != 0:
                # age does includes summary date
                age = (dates[-1]-dates[0]).days
                closing = dates[-1]
            else:
                # age does not include summary date
                age = (dates[-2]-dates[0]).days
                closing = dates[-2]
            return age, closing
        else:
            return timedelta().days, datetime.time(0)
   
    def compute_fund_xirrs_ages(self):
        count = 0
        xirrs = []
        ages = []
        for (fund,folio)in zip(self.sumarry_df.Fund_name,
                                self.sumarry_df.Folio):
            fund_txns = self.txn_df.loc[
                            (self.txn_df["Fund_name"] == fund) & 
                            (self.txn_df["Folio"] == folio)
                        ]
            fund_summ = self.sumarry_df.loc[
                            (self.sumarry_df["Fund_name"] == fund) & 
                            (self.sumarry_df["Folio"] == folio)
                        ]
            # For XIRR calcs, include the current date/val
            # Add to the txns, the current date
            #since this is a view on a df, we use count as the correct idx in the overal df
            final_date = to_datetime(fund_summ["Date"], format="%d-%b-%Y",
                                dayfirst=True)[count] 
            dates = to_datetime(fund_txns["Date"],
                                format="%d-%b-%Y",
                                dayfirst=True).tolist()
            dates.append(final_date)
            # Add to the txns, the current market val
            final_amt = fund_summ["Market_value"].tolist()
            txns = fund_txns["Amount"].tolist()
            txns.append(0-final_amt[0])
            
            # Cost value to compute absolute gain
            cost_value = fund_summ["Total_cost_value"].tolist()[0]
            closing_bal = float(fund_summ["Closing_unit_balance"][count])
            age, closing_date = self.calculate_fund_age_days_and_closing_date(closing_bal,dates,txns)
            self.sumarry_df.at[count,"Date"] = closing_date.strftime('%d-%b-%Y')
            print(fund_summ["Date"][count], closing_date.strftime('%d-%b-%Y'))
            ages.append(age)
            xirr_val = xirr(txns,dates,age,cost_value,final_amt[0])
            xirrs.append(round(xirr_val*100, 2))
            count += 1
    
        return xirrs,ages


def parse_args():
    parser = argparse.ArgumentParser(
                    prog='Cams2CSV cli',
                    description='Converts CAMS pdf to CSV format')
    parser.add_argument('filename', help="Name of the input PDF file")
    parser.add_argument( '-p', '--password', default="",
                        help="Password of the input PDF file")
    return parser.parse_args()

# Thanks to KT. for XIRR computation fns : https://stackoverflow.com/a/33260133
def xnpv(rate, values, dates):
    '''Equivalent of Excel's XNPV function.

    >>> from datetime import date
    >>> dates = [date(2010, 12, 29), date(2012, 1, 25), date(2012, 3, 8)]
    >>> values = [-10000, 20, 10100]
    >>> xnpv(0.1, values, dates)
    -966.4345...
    '''
    if rate <= -1.0:
        return float('inf')
    d0 = dates[0]    # or min(dates)
    return sum([ vi / (1.0 + rate)**((di - d0).days / 365.0) for vi, di in zip(values, dates)])
# returns the xirr ratio, not %age
def xirr(values, dates,days, cost_value, final_amt):
    '''Equivalent of Excel's XIRR function.

    >>> from datetime import date
    >>> dates = [date(2010, 12, 29), date(2012, 1, 25), date(2012, 3, 8)]
    >>> values = [-10000, 20, 10100]
    >>> xirr(values, dates)
    0.0100612...
    '''
    if days<365:
        if cost_value == 0:
            return 0
        return ((final_amt-cost_value)/cost_value)

    try:
        return scipy.optimize.newton(lambda r: xnpv(r, values, dates), 0.0)
    except RuntimeError:    # Failed to converge?
        return scipy.optimize.brentq(lambda r: xnpv(r, values, dates), -1.0, 1e10)



def main():
    args = parse_args()
    processor = WelcomeScreen()
    processor.file_processing(args.filename,args.password)

if __name__ == "__main__":
    main()