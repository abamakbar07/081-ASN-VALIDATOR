# WMS Template Validation Tool

## Overview

This project provides a lightweight validation tool built with **Python** and **Streamlit** to validate structured Excel templates used in warehouse operational processes.

The tool helps detect formatting issues, inconsistent keys, and incorrect data mappings **before the data is processed by downstream systems**. This reduces manual checking and helps prevent operational errors.

The application was originally developed to support day‑to‑day operational workflows in a warehouse environment. All company‑specific data, naming conventions, and internal templates have been **anonymized** for confidentiality.

---

## Key Features

* Validate Excel mapping templates with **Header and Detail structure**
* Detect missing or inconsistent **Generic Keys** between sheets
* Pattern validation for specific fields
* Row‑level error reporting with actionable messages
* Excel validation report export
* Optional **column anonymization** for safe public sharing

---

## Technology Stack

* Python
* Streamlit
* Pandas
* OpenPyXL

---

## How It Works

1. Upload the Excel mapping template

2. The system scans the workbook and detects the header and detail sheets

3. Validation rules are applied to check:

   * Key consistency
   * Column format rules
   * Mapping integrity
   * Data anomalies

4. The application generates:

   * Summary validation metrics
   * Error summary
   * Row‑level error details
   * Downloadable validation report

---

## Example Validation Checks

The validator includes several automated checks such as:

* Generic key mismatch between header and detail sheets
* Invalid column format patterns
* Inconsistent mapping values
* Potential mapping leakage between fields

These checks help ensure that uploaded templates follow the expected structure before being used in operational workflows.

---

## Installation

Clone the repository:

```
git clone https://github.com/yourusername/wms-template-validator.git
cd wms-template-validator
```

Install dependencies:

```
pip install -r requirements.txt
```

Run the application:

```
streamlit run app.py
```

---

## Usage

1. Start the Streamlit application
2. Upload the Excel template
3. Run validation
4. Review detected errors
5. Download the validation report

---

## Data Privacy Notice

This repository **does not contain any real operational data**.

All column names, templates, and datasets in this repository have been **anonymized and simplified** to remove any sensitive information related to internal warehouse systems.

The project is shared strictly for **demonstration and portfolio purposes**.

---

## Possible Improvements

Future improvements may include:

* Configurable validation rules
* Support for additional template formats
* Integration with automated data pipelines
* Role‑based validation workflows

---

## Author

Muhamad Akbar Afriansyah

Warehouse Operations & Process Automation Enthusiast

---

## License

This project is shared for educational and demonstration purposes.
