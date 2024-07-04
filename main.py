#!/usr/bin/python
import argparse
import sys, os
import pdfplumber
import re
from pandas import DataFrame
from datetime import datetime
import threading

basedir = os.path.dirname(__file__)


class WelcomeScreen():
    def __init__(self):
        # init cli 
        print("CAMS 2 CSV CLI version")


    def file_processing(self, file_path, doc_pwd):
        final_text = ""

        if not len(file_path) == 0:
            try:
                with pdfplumber.open(file_path, password=doc_pwd) as pdf:
                    for i in range(len(pdf.pages)):
                        txt = pdf.pages[i].extract_text()
                        final_text = final_text + "\n" + txt
                    pdf.close()

                self.extract_text(final_text)

            except:
                print("Encrypted file, please enter your password\n")
        else:
            print("Please select your CAMS PDF file..\n")

    def extract_text(self, doc_txt):
        # Defining RegEx patterns
        folio_pat = re.compile(
            r"(^Folio No:\s\d+)", flags=re.IGNORECASE)  # Extracting Folio information
        fund_name = re.compile(r".*[Fund].*ISIN.*", flags=re.IGNORECASE)
        trans_details = re.compile(
            r"(^\d{2}-\w{3}-\d{4})(\s.+?\s(?=[\d(]))([\d\(]+[,.]\d+[.\d\)]+)(\s[\d\(\,\.\)]+)(\s[\d\,\.]+)(\s[\d,\.]+)"
        )  # Extracting Transaction data

        # Represents a row in all txn csv
        line_itms = []
        for i in doc_txt.splitlines():
            if fund_name.match(i):
                fun_name = i

            if folio_pat.match(i):
                folio = i

            txt = trans_details.search(i)
            if txt:
                date = txt.group(1)
                description = txt.group(2)
                amount = txt.group(3)
                units = txt.group(4)
                price = txt.group(5)
                unit_bal = txt.group(6)
                line_itms.append(
                    [
                        folio, fun_name, date, description, amount,
                        units, price, unit_bal
                    ]
                )

            df = DataFrame(
                line_itms,
                columns=[
                    "Folio",
                    "Fund_name",
                    "Date",
                    "Description",
                    "Amount",
                    "Units",
                    "Price",
                    "Unit_balance",
                ],
            )
            self.clean_txt(df.Amount)
            self.clean_txt(df.Units)
            self.clean_txt(df.Price)
            self.clean_txt(df.Unit_balance)

            df.Amount = df.Amount.astype("float")
            df.Units = df.Units.astype("float")
            df.Price = df.Price.astype("float")
            df.Unit_balance = df.Unit_balance.astype("float")

            date_str = datetime.now().strftime("%d_%m_%Y_%H_%M")
            file_name = f'CAMS_data_{date_str}.csv'
            save_file = os.path.join(".","all-txn-"+ file_name +".csv")

            try:
                df.to_csv(save_file, index=False)
                print(
                    "Process completed, file saved in current dir"
                )

            except Exception as e:
                sys.stderr.write(str(e))

    def clean_txt(self, x):
        x.replace(r",", "", regex=True, inplace=True)
        x.replace(r"\(", "-", regex=True, inplace=True)
        x.replace(r"\)", " ", regex=True, inplace=True)
        return x


def parse_args():
    parser = argparse.ArgumentParser(
                    prog='Cams2CSV cli',
                    description='Converts CAMS pdf to CSV format')
    parser.add_argument('filename', help="Name of input PDF file")
    return parser.parse_args()

def main():
    args = parse_args()
    print(args.filename)
    processor = WelcomeScreen()
    processor.file_processing(args.filename,"")

if __name__ == "__main__":
    main()