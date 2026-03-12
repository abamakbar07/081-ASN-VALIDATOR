# WMS Template Validator

A lightweight validation tool built with Python and Streamlit to verify Excel templates before uploading them into a Warehouse Management System (WMS).

This tool helps detect common data mapping mistakes in operational templates such as incorrect field formats, missing references, or mismatched identifiers.

The application was originally developed to support day-to-day warehouse operations and reduce human errors during data preparation before system uploads.

---

## Features

- Excel template validation
- Column format validation
- Generic Key consistency check
- Shipment reference validation
- WBS format validation
- Project ID format validation
- FASID format validation
- Row-level error reporting
- Downloadable validation report

The tool highlights exactly which row and column contain issues so they can be corrected quickly.

---

## Supported Validations

The validator checks several operational rules such as:

- GenericKey in Detail sheet must exist in Header sheet
- Shipment references must match between Header and Detail
- WBS format validation
- ProjectID format validation
- FASID format validation
- Detection of mapping errors between columns

Serial Number fields (LOTTABLE07) are intentionally excluded from validation.

---

## How It Works

1. Upload an Excel template
2. Run validation
3. Review validation results
4. Download validation report
5. Correct the template before uploading into WMS

---

## Installation

Install required dependencies:


pip install pandas openpyxl xlrd streamlit


---

## Run the Application


python -m streamlit run app.py


Then open the browser:


http://localhost:8501


---

## Project Structure


.
├── app.py
├── run_validator.bat
└── README.md


---

## Operational Context

This tool was built to assist operational workflows in warehouse environments where Excel templates are used to prepare data before uploading into a Warehouse Management System.

The validator helps reduce errors that may cause incorrect order creation or system data inconsistencies.

---

## Disclaimer

This repository contains a generalized validation tool and does not include any confidential data, system credentials, or proprietary business information.

---

## Author

Developed as a personal automation project to improve operational efficiency in in warehouse data preparation workflows.