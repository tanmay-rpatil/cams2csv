#!/usr/bin/python
import argparse
import sys, os
import pdfplumber
import re
from pandas import DataFrame, to_datetime
import numpy as np
from datetime import datetime
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
                    "Xirr"
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
                folio = i

            txt = TXN_REGEX.search(i)
            if txt:
                date = txt.group(1)
                description = txt.group(2)
                amount = txt.group(3)
                units = txt.group(4)
                price = txt.group(5)
                unit_bal = txt.group(6)
                self.rows_map[ALL_TXN].append(
                    [
                        folio, fun_name, date, description, amount,
                        units, price, unit_bal
                    ]
                )
                fund_txns += 1
                total_txn += 1
            elif i.startswith("Closing"):
                self.summerize_current_fund(fun_name,folio,i)
            elif "*** Stamp Duty ***" in i:
                line = ((i.strip()).split())
                duty = line[-1]
                date = line[0]
                description = line[1]
                print(duty,date,description)
                # self.rows_map[ALL_TXN].append(
                #     [
                #         folio, fun_name, date, description, duty,
                #         '0', '0', '0'
                #     ]
                # )
                
            
               
        self.txn_df = self.write_to_op_file(ALL_TXN)
        # xirr

        self.write_to_op_file(SUMMARY)  
        
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
                    cost, market_val, 0.00
                ]
            )

    def write_to_op_file(self, op_type):
        date_str = datetime.now().strftime("%d_%m_%Y_%H_%M")
        fname_tmpl = f'CAMS_data_{date_str}.csv'
        save_file = os.path.join(".",op_type +"-"+ fname_tmpl +".csv")

        rows = self.rows_map[op_type]
        print((len(rows),len(self.headers[op_type])))
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
            xirrs = self.compute_xirrs()
            df['Xirr'] = xirrs

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

    def clean_txt(self, x):
        x.replace(r",", "", regex=True, inplace=True)
        x.replace(r"\(", "-", regex=True, inplace=True)
        x.replace(r"\)", " ", regex=True, inplace=True)
        return x

    def compute_xirrs(self):
        count = 0
        xirrs = []
        for fund in self.sumarry_df.Fund_name:
            fund_txns = self.txn_df.loc[
                            self.txn_df["Fund_name"] == fund
                        ]
            fund_summ = self.sumarry_df.loc[
                            self.sumarry_df["Fund_name"] == fund
                        ]
            # For XIRR calcs, include the current date/val
            # Add to the txns, the current date
            final_date = to_datetime(fund_summ["Date"])[count]
            dates = to_datetime(fund_txns["Date"],
                                format="%d-%b-%Y",
                                dayfirst=True).tolist()
            dates.append(final_date)
            # Add to the txns, the current market val
            final_amt = fund_summ["Market_value"].tolist()
            txns = fund_txns["Amount"].tolist()
            txns.append(0-final_amt[0])
            
            xirr_val = xirr(txns,dates)
            xirrs.append(round(xirr_val*100, 2))
            count += 1
    
        return xirrs


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

def xirr(values, dates):
    '''Equivalent of Excel's XIRR function.

    >>> from datetime import date
    >>> dates = [date(2010, 12, 29), date(2012, 1, 25), date(2012, 3, 8)]
    >>> values = [-10000, 20, 10100]
    >>> xirr(values, dates)
    0.0100612...
    '''
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