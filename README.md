# Marginal Cost & Retail Savings Valuation Tool

A rigorous, 8760-hourly marginal cost energy valuation application built with Python and Streamlit. This tool enables users to analyze utility avoided costs (generation capacity, transmission & distribution, carbon/emissions, energy) and calculate customer bill savings under different rate structures.

---

## 🚀 Getting Started

Follow these steps to set up and run the application locally:

### 1. Create a Python Virtual Environment
Navigate to your project directory and create a virtual environment (`venv`):
```bash
python -m venv venv
```

### 2. Activate the Virtual Environment
Activate the environment based on your operating system:
* **Windows (PowerShell)**:
  ```powershell
  .\venv\Scripts\Activate.ps1
  ```
* **Windows (Command Prompt)**:
  ```cmd
  .\venv\Scripts\activate.bat
  ```
* **Mac / Linux**:
  ```bash
  source venv/bin/activate
  ```

### 3. Install Dependencies
Install all required packages from `requirements.txt`:
```bash
pip install -r requirements.txt
```

### 4. Run the Application
Launch the Streamlit dashboard in your web browser:
```bash
streamlit run app.py
```

---

## 📊 Energy & Avoided Cost Datasets

### Current Coverage
This repository includes processed baseline datasets preloaded under the `cambium_data/` directory. Currently, it supports:
* **Alabama (AL)** (Midcase & High Demand Growth scenarios)
* **Georgia (GA)** (Midcase & High Demand Growth scenarios)

### Expanding to Other Regions (Full NREL Cambium Data)
To evaluate projects in states or balancing authorities outside of Alabama and Georgia, users must download the raw Cambium datasets from the official NREL sources:

1. **Visit the NREL Scenario Viewer**:  
   Download datasets directly from [NREL Scenario Viewer](https://scenarioviewer.nlr.gov/).
2. **Additional Information**:  
   Read more about the methodology, metrics, and scenario assumptions on the [NREL Cambium Homepage](https://www.nlr.gov/analysis/cambium).

#### Ingesting New Data:
The tool is built to dynamically pull, parse, and aggregate raw Cambium datasets recursively. You do **not** need to manually rename, preprocess, or format individual files. 

To evaluate other regions or scenarios, download any of NREL's hourly scenario datasets from the Scenario Viewer and **paste the raw CSV files directly into the `Cambium_Hourly_Data_raw/` directory** at the root of the project.

The application's ingestion engine will automatically:
1. **Recursive Scan**: Recursively scan the `Cambium_Hourly_Data_raw/` directory for all `.csv` files.
2. **Metadata Audit**: For each file, look at the NREL-standard first two lines to extract the file's static state, scenario, and year information.
3. **Filter and Aggregate**: Filter for files matching your sidebar selections:
   * **NREL Future Scenario** (e.g., `HighDemandGrowth`)
   * **NREL Planning Year** (2025, 2030, 2035, 2040, 2045, or 2050)
   * **Target States** (e.g., `AL`, `GA`, etc.)
4. **Multi-row Skip & Map**: Skip the first 5 metadata/description rows of raw files to load the actual hourly 8760 data, and auto-resolve column headers using an intelligent variable mapping engine (mapping energy price columns like `energy_cost_busbar` or `energy_cost_enduse` and emission columns like `lrmer_co2_c`).



> [!WARNING]
> **Capacity Weighting Factor Table (CWFT) Data:**  
> The provided `CWFT.csv` file in this repository is currently a **mocked placeholder** and does not reflect realistic utility peak risk conditions. It should **not** be used for final engineering or economic evaluations. Users must replace it with a valid, region-specific Capacity Weighting Factor dataset.

---

## 📂 Project Structure

- `app.py`: The core Streamlit application containing the avoided cost calculation engine, custom rate schedules (Alabama Power FD, Georgia Power R), and dashboard visualizations.
- `requirements.txt`: Python package dependencies (Streamlit, Pandas, NumPy, Plotly).
- `Cambium_Hourly_Data_raw/`: Folder where users should place raw NREL hourly CSV downloads (for any scenario/year).
- `CWFT.csv`: The Capacity Weighting Factor Table (CWFT) representing hour-by-hour system risk weights. *(Note: Must be replaced with real utility/ISO risk factor data for real-world evaluations).*
- `load_profiles.csv`: Standard building load shapes for baseline and dynamic load modification analysis.
- `southeast_avoided_costs_AL_GA.csv`: Hourly avoided cost projections derived from NREL Cambium datasets for Alabama and Georgia balancing authorities.


