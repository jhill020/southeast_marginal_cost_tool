import os
import glob
import json
import urllib.request
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ==============================================================================
# PAGE CONFIGURATION & AESTHETICS
# ==============================================================================
st.set_page_config(
    page_title="Southeast Marginal Cost Valuation Engine",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Premium Custom CSS styling for metric cards and containers
st.markdown(
    """<style>
/* Metric styling */
[data-testid="stMetricValue"] {
    font-size: 1.8rem;
    font-weight: 700;
    color: #0D9488; /* Sleek teal color for key figures */
}
[data-testid="stMetricLabel"] {
    font-size: 0.9rem;
    font-weight: 600;
    color: #4B5563;
}
div[data-testid="metric-container"] {
    background-color: #F8FAFC;
    border: 1px solid #E2E8F0;
    padding: 15px 18px;
    border-radius: 12px;
    box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.05), 0 2px 4px -2px rgb(0 0 0 / 0.05);
    transition: transform 0.2s ease-in-out;
}
div[data-testid="metric-container"]:hover {
    transform: translateY(-2px);
    box-shadow: 0 10px 15px -3px rgb(0 0 0 / 0.05);
}
/* Style tables and graphs */
[data-testid="stDataFrame"] {
    border: 1px solid #E2E8F0;
    border-radius: 12px;
    overflow: hidden;
}
.badge {
    display: inline-block;
    padding: 0.35em 0.65em;
    font-size: 0.85em;
    font-weight: 700;
    line-height: 1;
    text-align: center;
    white-space: nowrap;
    vertical-align: baseline;
    border-radius: 0.375rem;
}
.badge-success {
    color: #fff;
    background-color: #15803d;
}
.badge-warning {
    color: #854d0e;
    background-color: #fef08a;
    border: 1px solid #eab308;
}
.badge-danger {
    color: #fff;
    background-color: #b91c1c;
}
</style>""",
    unsafe_allow_html=True
)

# ==============================================================================
# PRE-PACKAGED LOCAL URDB TARIFS
# ==============================================================================
GP_R31_URDB = {
    "name": "Georgia Power - Schedule R-31 (Residential)",
    "fixedcharge": 16.48, # includes riders: $14.00/mo base * 1.177209 rider multiplier
    "energyratewindow": [
        [0]*24, [0]*24, [0]*24, [0]*24, [0]*24, # Jan - May (Winter = Period 0)
        [1]*24, [1]*24, [1]*24, [1]*24,         # Jun - Sep (Summer = Period 1)
        [0]*24, [0]*24, [0]*24                  # Oct - Dec (Winter = Period 0)
    ],
    "energyratestructure": [
        [{"rate": 0.142062}], # Period 0: Winter rate (8.2116¢ base + 3.8561¢ FCR) * 1.177209 riders
        [
            {"max": 650.0, "rate": 0.148101}, # Summer Tier 1 (8.7738¢ base + 3.8069¢ FCR) * 1.177209 riders
            {"max": 350.0, "rate": 0.216379}, # Summer Tier 2 (14.5738¢ base + 3.8069¢ FCR) * 1.177209 riders
            {"rate": 0.222371}                 # Summer Tier 3 (15.0828¢ base + 3.8069¢ FCR) * 1.177209 riders
        ] # Period 1: Summer tiered blocks
    ]
}

AL_FD_URDB = {
    "name": "Alabama Power - Rate FD (Family Dwelling)",
    "fixedcharge": 15.58, # $14.50/mo base + $1.08/mo NDR (averaging $13.00/yr)
    "energyratewindow": [
        [0]*24, [0]*24, [0]*24, [0]*24, [0]*24, # Jan - May (Winter = Period 0)
        [1]*24, [1]*24, [1]*24, [1]*24,         # Jun - Sep (Summer = Period 1)
        [0]*24, [0]*24, [0]*24                  # Oct - Dec (Winter = Period 0)
    ],
    "energyratestructure": [
        [
            {"max": 750.0, "rate": 0.150384}, # Winter Tier 1 (12.4384¢ base + 2.600¢ ECR)
            {"rate": 0.138384}                 # Winter Tier 2 (11.2384¢ base + 2.600¢ ECR)
        ], # Period 0: Winter tiered blocks
        [
            {"max": 1000.0, "rate": 0.150384}, # Summer Tier 1 (12.4384¢ base + 2.600¢ ECR)
            {"rate": 0.152913}                  # Summer Tier 2 (12.6913¢ base + 2.600¢ ECR)
        ] # Period 1: Summer tiered blocks
    ]
}

# ==============================================================================
# MOCK SETUP & FILE GENERATORS
# ==============================================================================
INPUT_DIRECTORY = "./Cambium_Hourly_Data_raw"

def generate_default_cwft_file(filepath="CWFT.csv"):
    """
    MOCK CWFT FILE GENERATOR:
    Creates a default 8760-hour Southeast Dual-Peak Capacity Worth Factor Table (CWFT)
    CSV file in the main directory if it doesn't exist.
    """
    if not os.path.exists(filepath):
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        cwft = np.zeros(8760)
        winter_hours = []
        summer_hours = []
        
        for h in range(1, 8761):
            if h <= 1440 and (h % 24 in [6, 7, 8, 9]):
                winter_hours.append(h - 1)
            elif 4345 <= h <= 5832 and (h % 24 in [14, 15, 16, 17, 18]):
                summer_hours.append(h - 1)
                
        # Distribute risk (45% winter, 55% summer)
        cwft[winter_hours] = 0.45 / len(winter_hours)
        cwft[summer_hours] = 0.55 / len(summer_hours)
        
        df = pd.DataFrame({
            'Hour': np.arange(1, 8761),
            'CWFT': cwft
        })
        df.to_csv(filepath, index=False)
    return filepath


def load_cwft_from_csv(filepath):
    try:
        df = pd.read_csv(filepath)
        if 'CWFT' not in df.columns:
            raise ValueError("The CWFT CSV file must contain a 'CWFT' column.")
        if len(df) != 8760:
            raise ValueError(f"The CWFT file must contain exactly 8760 rows (found {len(df)}).")
            
        cwft_array = df['CWFT'].to_numpy()
        cwft_sum = cwft_array.sum()
        if not np.isclose(cwft_sum, 1.0, atol=1e-3):
            cwft_array = cwft_array / cwft_sum
        return cwft_array
    except Exception as e:
        raise ValueError(f"Failed to parse CWFT CSV: {str(e)}")


def generate_default_load_profiles_file(filepath="load_profiles.csv"):
    if not os.path.exists(filepath):
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        hours = np.arange(1, 8761)
        np.random.seed(88)
        
        std_load = np.random.uniform(0.8, 1.2, 8760)
        he_load = np.random.uniform(0.5, 0.8, 8760)
        
        for h in hours:
            if h <= 1440 and (h % 24 in [6, 7, 8, 9]):
                std_load[h-1] = np.random.uniform(4.5, 6.5)
                he_load[h-1] = np.random.uniform(2.0, 3.2)
            elif 4345 <= h <= 5832 and (h % 24 in [14, 15, 16, 17, 18]):
                std_load[h-1] = np.random.uniform(2.5, 3.5)
                he_load[h-1] = np.random.uniform(1.4, 2.2)
                
        df = pd.DataFrame({
            'Hour': hours,
            'Standard_Heat_Pump_kW': std_load,
            'High_Efficiency_Heat_Pump_kW': he_load
        })
        df.to_csv(filepath, index=False)
    return filepath


def load_load_profiles_from_csv(filepath):
    try:
        df = pd.read_csv(filepath)
        if 'Hour' not in df.columns:
            raise ValueError("The Load Profiles CSV must contain an 'Hour' column.")
        if len(df) != 8760:
            raise ValueError(f"The Load Profiles CSV must contain exactly 8760 rows (found {len(df)}).")
            
        profile_cols = [col for col in df.columns if col != 'Hour']
        if not profile_cols:
            raise ValueError("The Load Profiles CSV must contain at least one load profile column.")
            
        for col in profile_cols:
            df[col] = pd.to_numeric(df[col], errors='raise')
        return df
    except Exception as e:
        raise ValueError(f"Failed to parse Load Profiles CSV: {str(e)}")


def generate_mock_state_file(filepath, state_code, scenario):
    """
    SAFETY NET DATA GENERATOR:
    Simulates a standard 8760-hour utility dataset capturing the distinct dual-peaking 
    load characteristics of the Southeastern United States.
    Outputs standard NREL Cambium column headers to verify the dynamic mapping engine.
    """
    state_seeds = {"AL": 42, "GA": 99, "FL": 101, "TN": 202, "MS": 303, "NC": 404, "SC": 505}
    seed = state_seeds.get(state_code, 123)
    np.random.seed(seed)
    
    hours = np.arange(1, 8761)
    
    if scenario == "HighDemandGrowth":
        energy_base = np.random.uniform(25.0, 38.0, 8760)
        carbon_base = np.random.uniform(450.0, 850.0, 8760)
        winter_spike_range = (80.0, 130.0)
        summer_spike_range = (70.0, 110.0)
    elif scenario == "LowCarbonConstraint":
        energy_base = np.random.uniform(18.0, 28.0, 8760)
        carbon_base = np.random.uniform(150.0, 450.0, 8760)
        winter_spike_range = (45.0, 80.0)
        summer_spike_range = (35.0, 70.0)
    elif scenario == "LowDemandGrowth":
        energy_base = np.random.uniform(15.0, 25.0, 8760)
        carbon_base = np.random.uniform(300.0, 650.0, 8760)
        winter_spike_range = (50.0, 80.0)
        summer_spike_range = (40.0, 70.0)
    else:  # MidCase / Default
        energy_base = np.random.uniform(20.0, 30.0, 8760)
        carbon_base = np.random.uniform(350.0, 750.0, 8760)
        winter_spike_range = (60.0, 90.0)
        summer_spike_range = (50.0, 80.0)
    
    for h in hours:
        if h <= 1440 and (h % 24 in [6, 7, 8, 9]):
            energy_base[h-1] = np.random.uniform(*winter_spike_range)
        elif 4345 <= h <= 5832 and (h % 24 in [14, 15, 16, 17, 18]):
            energy_base[h-1] = np.random.uniform(*summer_spike_range)
            
    # Outputs raw NREL Cambium column headers
    df = pd.DataFrame({
        'Hour': hours,
        'State': state_code,
        'Scenario': scenario,
        'lmp_energy': energy_base,
        'co2_combust': carbon_base
    })
    
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    df.to_csv(filepath, index=False)


def file_matches_scenario(filepath, scenario):
    filename = os.path.basename(filepath).lower()
    scenario_clean = scenario.lower()
    if scenario_clean in filename:
        return True
    try:
        head_df = pd.read_csv(filepath, nrows=5)
        if 'Scenario' in head_df.columns:
            if head_df['Scenario'].iloc[0].lower() == scenario_clean:
                return True
    except Exception:
        pass
    return False

# ==============================================================================
# PIPELINES & CALCULATORS
# ==============================================================================
def parse_cambium_columns(df):
    """
    NREL CAMBIUM COLUMN MAPPING ENGINE:
    Audits column names to dynamically map real Cambium variables.
    """
    cols = df.columns
    energy_col = None
    for name in ['lmp_energy', 'marginal_cost_energy', 'Cambium_Energy_MWh', 'marginal_cost_energy_MWh', 'energy_price']:
        for col in cols:
            if name.lower() == col.lower():
                energy_col = col
                break
        if energy_col:
            break
            
    carbon_col = None
    for name in ['co2_combust', 'marginal_co2_combust', 'Cambium_Carbon_kg_MWh', 'marginal_carbon_kg_MWh', 'carbon_intensity']:
        for col in cols:
            if name.lower() == col.lower():
                carbon_col = col
                break
        if carbon_col:
            break
            
    hour_col = None
    for name in ['hour', 'Hour_Index', 'Hour_of_Year']:
        for col in cols:
            if name.lower() == col.lower():
                hour_col = col
                break
        if hour_col:
            break
            
    # Intelligent fallbacks
    if not energy_col:
        for col in cols:
            if 'energy' in col.lower() or 'price' in col.lower() or 'mwh' in col.lower():
                energy_col = col
                break
    if not carbon_col:
        for col in cols:
            if 'co2' in col.lower() or 'carbon' in col.lower() or 'kg' in col.lower():
                carbon_col = col
                break
                
    return hour_col, energy_col, carbon_col


def load_custom_weather_file(weather_case):
    """
    Looks in Weather_Data_raw/<case_folder>/ for a .epw or .csv file and loads dry-bulb temperature (8760).
    Returns a numpy array of temperatures in Fahrenheit, or None if no file is found.
    """
    case_folder_map = {
        "2012 (Cambium-aligned baseline)": "Baseline",
        "Extreme Winter": "Extreme_Winter",
        "Extreme Summer": "Extreme_Summer"
    }
    folder_name = case_folder_map.get(weather_case, "Baseline")
    target_dir = os.path.join("Weather_Data_raw", folder_name)
    os.makedirs(target_dir, exist_ok=True)
    
    # Search for .epw or .csv files
    files = []
    for ext in ["*.epw", "*.csv"]:
        files.extend(glob.glob(os.path.join(target_dir, ext)))
        
    if not files:
        return None
        
    file_path = files[0]  # Take the first matched file
    try:
        if file_path.lower().endswith(".epw"):
            # EPW files have 8 header lines, then 8760 data lines.
            # Temperature is column index 6 (0-indexed), in Celsius.
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            data_lines = lines[8:]
            if len(data_lines) != 8760:
                data_lines = data_lines[:8760]
            
            temps_c = []
            for line in data_lines:
                parts = line.split(',')
                if len(parts) > 6:
                    temps_c.append(float(parts[6]))
                else:
                    temps_c.append(0.0)
                    
            temps_c = np.array(temps_c)
            # Convert to Fahrenheit
            temps_f = temps_c * 1.8 + 32.0
            return temps_f
            
        elif file_path.lower().endswith(".csv"):
            df = pd.read_csv(file_path)
            # Try to find a temperature column
            temp_col = None
            for col in df.columns:
                if any(x in col.lower() for x in ["temperature", "temp", "drybulb", "dry_bulb", "db_temp"]):
                    temp_col = col
                    break
            if temp_col is None:
                # If no clear header, take the first numeric column that isn't Hour or Hour index
                numeric_cols = [c for c in df.select_dtypes(include=[np.number]).columns if c.lower() not in ["hour", "hour_index", "datetime"]]
                if numeric_cols:
                    temp_col = numeric_cols[0]
                    
            if temp_col:
                temps = df[temp_col].to_numpy()
                if len(temps) != 8760:
                    temps = np.resize(temps, 8760)
                # Smart heuristic: Celsius vs Fahrenheit check
                # If max temp is < 50, assume Celsius and convert
                if np.nanmax(temps) < 50.0:
                    temps = temps * 1.8 + 32.0
                return temps
    except Exception as e:
        st.sidebar.error(f"Error loading custom weather file {os.path.basename(file_path)}: {str(e)}")
        
    return None


@st.cache_data
def load_and_aggregate_data(target_states, selected_scenario, weather_case, target_year="2026", planning_year="2040", input_directory=INPUT_DIRECTORY):
    """
    INGEST, AGGREGATE & WEATHER INJECTION PIPELINE (Cached):
    Loads scenario files, maps columns dynamically, aggregates them, and generates temperature shifts.
    Supports both preprocessed state files and raw NREL Cambium download structures.
    """
    os.makedirs(input_directory, exist_ok=True)
    
    # Track which states we successfully loaded from real data
    loaded_states = set()
    combined_list = []
    mapped_energy_col = None
    mapped_carbon_col = None
    
    # 1. Search recursively under the raw Cambium directory for all .csv files
    all_csv_files = []
    for root, dirs, files in os.walk(input_directory):
        if any(x in root for x in ["__pycache__"]):
            continue
        for file in files:
            if file.lower().endswith(".csv"):
                all_csv_files.append(os.path.join(root, file))
                
    for file in all_csv_files:
        try:
            # Check if this is a raw NREL Cambium file
            # Read first line without loading rows to see column list
            first_row_df = pd.read_csv(file, nrows=0)
            cols = [c.lower() for c in first_row_df.columns]
            
            is_raw_nrel = 'project' in cols and 'scenario' in cols and ('state' in cols or 'r' in cols)
            
            if is_raw_nrel:
                # Read metadata from row index 1
                meta_df = pd.read_csv(file, nrows=1)
                file_state = str(meta_df['state'].iloc[0]).upper() if 'state' in meta_df.columns else ""
                file_scenario = str(meta_df['Scenario'].iloc[0]).lower() if 'Scenario' in meta_df.columns else ""
                # Year column is t
                file_year = str(meta_df['t'].iloc[0]) if 't' in meta_df.columns else ""
                
                # Check if file matches selected scenario, state, and planning year
                if (file_scenario == selected_scenario.lower() and 
                    file_state in [s.upper() for s in target_states] and 
                    file_year == str(planning_year)):
                    
                    # Read the hourly data (header is at row index 5)
                    temp_df = pd.read_csv(file, header=5)
                    temp_df['State'] = file_state
                    temp_df['Scenario'] = selected_scenario
                    temp_df['Hour'] = np.arange(1, 8761)
                    
                    loaded_states.add(file_state)
                    filtered_df = temp_df
                else:
                    continue
            else:
                # Processed simplified format file
                if not file_matches_scenario(file, selected_scenario):
                    continue
                temp_df = pd.read_csv(file)
                if 'State' in temp_df.columns:
                    filtered_df = temp_df[temp_df['State'].isin(target_states)]
                    for s in filtered_df['State'].unique():
                        loaded_states.add(str(s).upper())
                else:
                    continue
            
            if not filtered_df.empty:
                # Dynamically map headers
                hr_c, nrel_energy_c, nrel_carbon_c = parse_cambium_columns(filtered_df)
                if nrel_energy_c:
                    mapped_energy_col = nrel_energy_c
                if nrel_carbon_c:
                    mapped_carbon_col = nrel_carbon_c
                    
                rename_dict = {}
                if nrel_energy_c:
                    rename_dict[nrel_energy_c] = 'Cambium_Energy_MWh'
                if nrel_carbon_c:
                    rename_dict[nrel_carbon_c] = 'Cambium_Carbon_kg_MWh'
                if hr_c and hr_c != 'Hour':
                    rename_dict[hr_c] = 'Hour'
                    
                filtered_df = filtered_df.rename(columns=rename_dict)
                
                if 'Cambium_Energy_MWh' not in filtered_df.columns:
                    raise ValueError(f"Could not map wholesale energy price in {file}. Found: {list(filtered_df.columns)}")
                if 'Cambium_Carbon_kg_MWh' not in filtered_df.columns:
                    raise ValueError(f"Could not map emissions rates in {file}. Found: {list(filtered_df.columns)}")
                    
                combined_list.append(filtered_df[['Hour', 'Cambium_Energy_MWh', 'Cambium_Carbon_kg_MWh', 'State']])
                
        except Exception as e:
            # Silently pass for other files
            pass
            
    # Ensure all requested states were successfully loaded from real files
    missing_states = [s for s in target_states if s.upper() not in loaded_states]
    if missing_states:
        raise FileNotFoundError(
            f"Missing Cambium grid data for state(s): {', '.join(missing_states)} "
            f"(Scenario: {selected_scenario} | Year: {planning_year}). "
            "Please download the raw NREL CSV files and place them in the 'Cambium_Hourly_Data_raw' directory."
        )
        
    if not combined_list:
        raise ValueError(f"No source data matched scenario ({selected_scenario}), year ({planning_year}), and states: {target_states}")
        
    raw_regional_df = pd.concat(combined_list, ignore_index=True)
    
    regional_base = raw_regional_df.groupby('Hour').agg({
        'Cambium_Energy_MWh': 'mean',
        'Cambium_Carbon_kg_MWh': 'mean'
    }).reset_index()
    
    # Standard 8760-hour generation, aligned to the target year to preserve weekday/weekend assignments
    date_range = pd.date_range(start=f"{target_year}-01-01 00:00:00", periods=8760, freq="h")
    regional_base['Datetime'] = date_range
    
    # Peak Capacity Allocation Factor (PCAF) for localized T&D stress (top 100 grid hours)
    top_100_cutoff = regional_base['Cambium_Energy_MWh'].nlargest(100).min()
    regional_base['PCAF_Weight'] = 0.0
    is_peak_hour = regional_base['Cambium_Energy_MWh'] >= top_100_cutoff
    regional_base.loc[is_peak_hour, 'PCAF_Weight'] = 1.0 / is_peak_hour.sum()
    
    assert np.isclose(regional_base['PCAF_Weight'].sum(), 1.0), "PCAF values must sum to 1.0"
    
    # --------------------------------------------------------------------------
    # Weather Profile & Temperature Generation
    # --------------------------------------------------------------------------
    hours = regional_base['Hour'].to_numpy()
    np.random.seed(42)
    
    # Try to load custom weather file (.epw or .csv) from Weather_Data_raw/
    custom_temp = load_custom_weather_file(weather_case)
    
    if custom_temp is not None:
        temperature = custom_temp
    else:
        # Fall back to synthetic profile
        seasonal_temp = 62.0 - 22.0 * np.cos(2 * np.pi * (hours - 360) / 8760)
        daily_temp = -8.0 * np.cos(2 * np.pi * (hours - 15) / 24)
        temp_noise = np.random.normal(0, 3.0, 8760)
        temperature = seasonal_temp + daily_temp + temp_noise
        
    energy_price = regional_base['Cambium_Energy_MWh'].to_numpy()
    
    cwft_derived = np.zeros(8760)
    winter_hours = []
    summer_hours = []
    for h in range(1, 8761):
        if h <= 1440 and (h % 24 in [6, 7, 8, 9]):
            winter_hours.append(h - 1)
        elif 4345 <= h <= 5832 and (h % 24 in [14, 15, 16, 17, 18]):
            summer_hours.append(h - 1)
            
    if weather_case == "Extreme Winter":
        if custom_temp is None:
            cold_snap_mask = (hours >= 120) & (hours <= 180)
            temperature[cold_snap_mask] -= 22.0
            
        winter_morning_mask = (hours <= 1440) & (np.isin(hours % 24, [6, 7, 8, 9]))
        energy_price[winter_morning_mask] *= np.random.uniform(2.2, 3.5, size=winter_morning_mask.sum())
        
        if custom_temp is None:
            energy_price[cold_snap_mask & (np.isin(hours % 24, [6, 7, 8, 9]))] *= 2.0
            
        cwft_derived[winter_hours] = 0.80 / len(winter_hours)
        cwft_derived[summer_hours] = 0.20 / len(summer_hours)
        
    elif weather_case == "Extreme Summer":
        if custom_temp is None:
            heatwave_mask = (hours >= 4800) & (hours <= 4860)
            temperature[heatwave_mask] += 10.0
            
        summer_afternoon_mask = (hours >= 4345) & (hours <= 5832) & (np.isin(hours % 24, [14, 15, 16, 17, 18]))
        energy_price[summer_afternoon_mask] *= np.random.uniform(2.2, 3.5, size=summer_afternoon_mask.sum())
        
        if custom_temp is None:
            energy_price[heatwave_mask & (np.isin(hours % 24, [14, 15, 16, 17, 18]))] *= 2.0
            
        cwft_derived[winter_hours] = 0.15 / len(winter_hours)
        cwft_derived[summer_hours] = 0.85 / len(summer_hours)
        
    else:
        cwft_derived[winter_hours] = 0.45 / len(winter_hours)
        cwft_derived[summer_hours] = 0.55 / len(summer_hours)
        
    regional_base['Temperature_F'] = temperature
    regional_base['Cambium_Energy_MWh'] = energy_price
    regional_base['CWFT_derived'] = cwft_derived
    regional_base['Mapped_Energy_Col'] = mapped_energy_col
    regional_base['Mapped_Carbon_Col'] = mapped_carbon_col
    
    return regional_base


@st.cache_data
def calculate_avoided_costs(df, cap_value, trans_value, dist_value, carbon_tax, cwft_array):
    regional_base = df.copy()
    regional_base['CWFT'] = cwft_array
    
    regional_base['Gen_Capacity_Value_MWh'] = cap_value * regional_base['CWFT'] * 1000
    regional_base['Trans_Value_MWh'] = trans_value * regional_base['PCAF_Weight'] * 1000
    regional_base['Dist_Value_MWh'] = dist_value * regional_base['PCAF_Weight'] * 1000
    regional_base['Emissions_Value_MWh'] = (regional_base['Cambium_Carbon_kg_MWh'] / 1000.0) * carbon_tax
    
    regional_base['Total_Avoided_Cost_MWh'] = (
        regional_base['Cambium_Energy_MWh'] +
        regional_base['Gen_Capacity_Value_MWh'] +
        regional_base['Trans_Value_MWh'] +
        regional_base['Dist_Value_MWh'] +
        regional_base['Emissions_Value_MWh']
    )
    return regional_base


def calculate_urdb_bill(load_kw, datetime_series, rate_json):
    """
    URDB COMPLIANT BILLING ENGINE:
    Parses URDB JSON structures (including V3 weekday/weekend schedules) 
    and applies them to the hourly 8760 load profile.
    """
    fixed_charge_monthly = rate_json.get("fixedcharge", 0.0)
    
    energy_wd = rate_json.get("energyweekdayschedule", rate_json.get("energyratewindow"))
    energy_we = rate_json.get("energyweekendschedule", rate_json.get("energyratewindow"))
    energy_structure = rate_json.get("energyratestructure")
    
    demand_wd = rate_json.get("demandweekdayschedule", rate_json.get("demandratewindow"))
    demand_we = rate_json.get("demandweekendschedule", rate_json.get("demandratewindow"))
    demand_structure = rate_json.get("demandratestructure")
    
    months = datetime_series.dt.month.to_numpy()
    hours = datetime_series.dt.hour.to_numpy()
    dayofweek = datetime_series.dt.dayofweek.to_numpy() # 0=Mon, 6=Sun
    
    total_bill = 0.0
    monthly_bills = []
    
    for m in range(1, 13):
        mask = months == m
        if not mask.any():
            continue
            
        m_load = load_kw[mask]
        m_hours = hours[mask]
        m_dow = dayofweek[mask]
        
        # 1. Fixed monthly charge
        m_bill = fixed_charge_monthly
        
        # 2. Energy charge
        if energy_structure is not None and energy_wd is not None and energy_we is not None:
            period_usage = {}
            for i, kw in enumerate(m_load):
                hr = m_hours[i]
                dow = m_dow[i]
                period_idx = energy_we[m - 1][hr] if dow >= 5 else energy_wd[m - 1][hr]
                period_usage[period_idx] = period_usage.get(period_idx, 0.0) + kw
                
            for period_idx, kwh in period_usage.items():
                if period_idx < len(energy_structure):
                    tiers = energy_structure[period_idx]
                    remaining_kwh = kwh
                    tier_charge = 0.0
                    for tier in tiers:
                        tier_max = tier.get("max", float("inf"))
                        tier_rate = tier.get("rate", 0.0) + tier.get("adj", 0.0)
                        
                        kwh_in_tier = min(remaining_kwh, tier_max)
                        tier_charge += kwh_in_tier * tier_rate
                        remaining_kwh -= kwh_in_tier
                        if remaining_kwh <= 0:
                            break
                    m_bill += tier_charge
                    
        # 3. Demand charge
        if demand_structure is not None and demand_wd is not None and demand_we is not None:
            period_peaks = {}
            for i, kw in enumerate(m_load):
                hr = m_hours[i]
                dow = m_dow[i]
                period_idx = demand_we[m - 1][hr] if dow >= 5 else demand_wd[m - 1][hr]
                period_peaks[period_idx] = max(period_peaks.get(period_idx, 0.0), kw)
                
            for period_idx, peak_kw in period_peaks.items():
                if period_idx < len(demand_structure):
                    tiers = demand_structure[period_idx]
                    remaining_kw = peak_kw
                    tier_charge = 0.0
                    for tier in tiers:
                        tier_max = tier.get("max", float("inf"))
                        tier_rate = tier.get("rate", 0.0) + tier.get("adj", 0.0)
                        
                        kw_in_tier = min(remaining_kw, tier_max)
                        tier_charge += kw_in_tier * tier_rate
                        remaining_kw -= kw_in_tier
                        if remaining_kw <= 0:
                            break
                    m_bill += tier_charge
                    
        total_bill += m_bill
        monthly_bills.append(m_bill)
        
    return total_bill, np.array(monthly_bills)


def fetch_urdb_rate(rate_label, api_key="DEMO_KEY"):
    """
    URDB API DOWNLOAD ENGINE:
    Retrieves rate structure dynamically from the NREL OpenEI URDB API.
    """
    url = f"https://api.openei.org/utility_rates?version=3&format=json&api_key={api_key}&detail=full&getpage={rate_label}"
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            items = data.get("items", [])
            if items:
                return items[0]
            else:
                raise ValueError(f"No rate found matching label: {rate_label}")
    except Exception as e:
        raise ConnectionError(f"Failed to connect to NREL URDB API: {str(e)}")


def dispatch_dr_program(datetime_series, cwft_array, dr_hours_per_year, season_name, max_hours_per_day, dr_capacity_kw, baseline_load):
    months = datetime_series.dt.month
    eligible_mask = np.ones(8760, dtype=bool)
    
    if season_name == "Summer Only (Jun-Sep)":
        eligible_mask = np.isin(months, [6, 7, 8, 9])
    elif season_name == "Winter Only (Oct-May)":
        eligible_mask = np.isin(months, [10, 11, 12, 1, 2, 3, 4, 5])
        
    eligible_indices = np.where(eligible_mask)[0]
    sorted_eligible = eligible_indices[np.argsort(-cwft_array[eligible_indices])]
    
    selected_hours = []
    daily_counts = {}
    dates = datetime_series.dt.date.to_numpy()
    
    for idx in sorted_eligible:
        date = dates[idx]
        count = daily_counts.get(date, 0)
        if count < max_hours_per_day:
            selected_hours.append(idx)
            daily_counts[date] = count + 1
            if len(selected_hours) >= dr_hours_per_year:
                break
                
    dr_reduction = np.zeros(8760)
    for idx in selected_hours:
        dr_reduction[idx] = min(dr_capacity_kw, baseline_load[idx])
    return dr_reduction, selected_hours

# ==============================================================================
# SIDEBAR CONTROLS & INPUT PARAMETERS
# ==============================================================================
st.sidebar.markdown(
    """<div style="text-align: center; margin-bottom: 20px;">
<h2 style="margin: 0; color: #1E293B; font-weight: 700;">Region & Scenario Settings</h2>
<p style="margin: 5px 0 0 0; color: #64748B; font-size: 0.85rem;">Configure wholesale and retail inputs below</p>
</div>""",
    unsafe_allow_html=True
)

# 1. Weather & Scenario Selectors
st.sidebar.markdown("### 🌤️ Grid Weather & Scenario")
scenario_options = ["HighDemandGrowth", "MidCase", "LowCarbonConstraint", "LowDemandGrowth"]
selected_scenario = st.sidebar.selectbox(
    "NREL Future Scenario",
    options=scenario_options,
    index=0
)

planning_year = st.sidebar.selectbox(
    "NREL Planning Year",
    options=["2025", "2030", "2035", "2040", "2045", "2050"],
    index=3,
    help="Select the target grid planning year for valuation."
)

weather_case = st.sidebar.selectbox(
    "Grid Weather Case",
    options=["2012 (Cambium-aligned baseline)", "Extreme Winter", "Extreme Summer"],
    index=0,
    help="Alters temperatures, pushes peaks, and shifts reliability CWFT risk."
)

target_states = st.sidebar.multiselect(
    "Target States",
    options=["AL", "GA", "FL", "TN", "MS", "NC", "SC"],
    default=["AL", "GA"]
)

# 2. Split Capacity Values
st.sidebar.markdown("---")
st.sidebar.markdown("### 💸 Grid Valuation Scalars")
cap_value = st.sidebar.number_input(
    "Gen Capacity Value ($/kW-year)",
    min_value=0.0, max_value=1000.0, value=100.00, step=5.00, format="%.2f"
)

trans_value = st.sidebar.number_input(
    "Transmission Deferral ($/kW-year)",
    min_value=0.0, max_value=500.0, value=15.00, step=1.00, format="%.2f"
)

dist_value = st.sidebar.number_input(
    "Distribution Deferral ($/kW-year)",
    min_value=0.0, max_value=500.0, value=15.00, step=1.00, format="%.2f"
)

carbon_tax = st.sidebar.slider(
    "Carbon Penalty ($/metric ton)",
    min_value=0.0, max_value=100.00, value=30.00, step=5.00, format="$%.2f"
)

# 3. Retail Tariff & URDB Selector
st.sidebar.markdown("---")
st.sidebar.markdown("### 🔌 Retail Tariff (NREL URDB)")
tariff_type = st.sidebar.selectbox(
    "Retail Utility Tariff Type",
    options=[
        "Georgia Power - Schedule R-31 (Residential)",
        "Alabama Power - Rate FD (Family Dwelling)",
        "Import from NREL URDB (API Label)",
        "Paste Custom URDB V3 JSON",
        "Custom Flat Rate / Demand"
    ],
    index=0,
    help="Define customer bill impact using packaged rates, pasting URDB JSONs, or querying the OpenEI API."
)

retail_escalation_rate = st.sidebar.number_input(
    "Retail Price Escalation (%)",
    min_value=-5.0, max_value=15.0, value=2.0, step=0.5, format="%.1f"
)

active_tariff_json = None
custom_rate_kwh = 0.12
custom_demand_charge_kw = 0.0

if tariff_type == "Georgia Power - Schedule R-31 (Residential)":
    active_tariff_json = GP_R31_URDB
elif tariff_type == "Alabama Power - Rate FD (Family Dwelling)":
    active_tariff_json = AL_FD_URDB
elif tariff_type == "Import from NREL URDB (API Label)":
    urdb_label = st.sidebar.text_input(
        "URDB Rate Label", 
        value="5d4b00595457a3e73a0e6988", 
        help="OpenEI unique tariff label (e.g. 5d4b00595457a3e73a0e6988)"
    )
    with st.sidebar.expander("❓ How to get the Rate Label"):
        st.markdown(
            """1. Go to NREL's [Utility Rate Database](https://openei.org/wiki/Utility_Rate_Database).
2. Search for your utility (e.g., *Georgia Power*) and select the target rate plan.
3. In the rate details page URL, copy the final segment (e.g., `5d4b00595457a3e73a0e6988` from `https://openei.org/apps/USURDB/rate/view/5d4b00595457a3e73a0e6988`)."""
        )
    urdb_api_key = st.sidebar.text_input("OpenEI API Key", value="DEMO_KEY", type="password")
    
    if st.sidebar.button("📥 Fetch Tariff Structure", use_container_width=True):
        with st.spinner("Downloading rate from NREL OpenEI..."):
            try:
                fetched_rate = fetch_urdb_rate(urdb_label, urdb_api_key)
                st.session_state['fetched_urdb_json'] = fetched_rate
                st.sidebar.success(f"✓ Connected! Loaded: {fetched_rate.get('name', 'Rate')}")
            except Exception as e:
                st.sidebar.error(f"Failed to fetch rate: {str(e)}")
                
    if 'fetched_urdb_json' in st.session_state:
        active_tariff_json = st.session_state['fetched_urdb_json']
        st.sidebar.caption(f"Active: *{active_tariff_json.get('name', 'Fetched Tariff')}*")
    else:
        st.sidebar.warning("Click Fetch to load tariff details.")
        
elif tariff_type == "Paste Custom URDB V3 JSON":
    raw_pasted_json = st.sidebar.text_area("Paste URDB JSON here", height=150, help="Paste a full NREL V3 utility rate JSON response.")
    if raw_pasted_json:
        try:
            active_tariff_json = json.loads(raw_pasted_json)
            st.sidebar.success(f"✓ Valid JSON! Loaded: {active_tariff_json.get('name', 'Pasted Rate')}")
        except Exception as e:
            st.sidebar.error(f"Invalid JSON: {str(e)}")
            
elif tariff_type == "Custom Flat Rate / Demand":
    custom_rate_kwh = st.sidebar.number_input("Custom Energy ($/kWh)", min_value=0.0, value=0.12, step=0.01, format="%.3f")
    custom_demand_charge_kw = st.sidebar.number_input("Custom Demand ($/kW-month)", min_value=0.0, value=0.00, step=1.00, format="%.2f")

# 4. Demand Response Program Toggle
st.sidebar.markdown("---")
st.sidebar.markdown("### 📶 Demand Response (DR) Mode")
dr_mode = st.sidebar.toggle(
    "Enable DR Program Mode",
    value=False,
    help="Curbs load reduction dynamically during high-stress hours subject to call limits."
)

dr_hours_per_year = 50
dr_season = "Summer Only (Jun-Sep)"
dr_max_hours_per_day = 4
dr_capacity_kw = 1.0

if dr_mode:
    dr_hours_per_year = st.sidebar.number_input("DR Call Hours per Year", min_value=1, max_value=8760, value=50, step=5)
    dr_season = st.sidebar.selectbox("DR Season of Applicability", ["Summer Only (Jun-Sep)", "Winter Only (Oct-May)", "Both Seasons"])
    dr_max_hours_per_day = st.sidebar.slider("Max Daily Call Hours", min_value=1, max_value=24, value=4)
    dr_capacity_kw = st.sidebar.number_input("DR Curtailment Capacity (kW)", min_value=0.1, value=1.0, step=0.5, format="%.2f")

# 5. Financial Lifetime & NPV Adjustments
st.sidebar.markdown("---")
st.sidebar.markdown("### ⏳ Asset Lifetime & NPV")
asset_life = st.sidebar.number_input("Asset Lifetime (Years)", min_value=1, max_value=50, value=15, step=1)
discount_rate = st.sidebar.number_input("Discount Rate / WACC (%)", min_value=0.0, max_value=25.0, value=7.0, step=0.5, format="%.1f")
escalation_rate = st.sidebar.number_input("Grid Price Escalation (%)", min_value=-5.0, max_value=15.0, value=2.0, step=0.5, format="%.1f")
degradation_rate = st.sidebar.number_input("Annual Efficiency Decay (%)", min_value=0.0, max_value=10.0, value=1.0, step=0.1, format="%.1f")

# 6. File Input Paths
st.sidebar.markdown("---")
st.sidebar.markdown("### 📂 Input File Paths")
use_custom_cwft = st.sidebar.checkbox("Use Custom CWFT CSV File", value=True)
cwft_filepath = st.sidebar.text_input("CWFT CSV File Path", value="CWFT.csv")
load_profiles_filepath = st.sidebar.text_input("Load Profiles CSV Path", value="load_profiles.csv")

st.sidebar.markdown("---")
# Metadata Tracker inputs
st.sidebar.markdown("### 🏷️ Weather Alignment Metadata")
meta_load_weather = st.sidebar.text_input("Load Profile Weather Year", value="2012")
meta_cambium_weather = st.sidebar.text_input("Cambium Weather Year", value="2012")
meta_cwft_weather = st.sidebar.text_input("CWFT Weather Year", value="2012")

run_simulation = st.sidebar.button("🚀 Run Valuation Engine", type="primary", use_container_width=True)

if 'simulation_executed' not in st.session_state:
    st.session_state['simulation_executed'] = False
if 'saved_runs' not in st.session_state:
    st.session_state['saved_runs'] = []

if run_simulation:
    st.session_state['simulation_executed'] = True

# ==============================================================================
# MAIN PANEL
# ==============================================================================
if not st.session_state['simulation_executed']:
    st.info("💡 **Welcome:** Verify your setting panels in the sidebar and click **Run Valuation Engine** to execute calculations.")
    st.markdown(
        """<div style="background-color: #F8FAFC; border: 1px solid #E2E8F0; padding: 30px; border-radius: 12px; margin-top: 10px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.05); font-family: sans-serif;">
<h3 style="margin-top: 0; color: #1E3A8A; font-weight: 700; border-bottom: 2px solid #DBEAFE; padding-bottom: 8px;">
📋 Instructions: Preparing Inputs for Energy & Capacity Valuation
</h3>
<p style="color: #475569; line-height: 1.6; font-size: 1.05rem;">
To calculate both <strong>Energy Avoided Cost Savings</strong> and <strong>Capacity Deferral Savings (from CWFT)</strong> in a single run, the calculator requires two chronologically synchronized CSV files.
</p>
<h4 style="color: #0F766E; margin-top: 20px; font-weight: 600;">1. Load Profiles Input (<code>load_profiles.csv</code>)</h4>
<p style="color: #475569; line-height: 1.6; margin-bottom: 8px;">
This file contains the hourly electricity consumption (kW) for your baseline and proposed systems (e.g. standard vs. high-efficiency heat pump), typically simulated in EnergyPlus.
</p>
<ul style="padding-left: 20px; color: #475569; line-height: 1.6;">
<li><strong>Format:</strong> Must contain exactly <strong>8,760 rows</strong> of hourly data.</li>
<li><strong>Columns:</strong> An <code>Hour</code> index column (1 to 8760) and at least one load profile column (e.g. <code>Standard_Heat_Pump_kW</code>). You can include multiple columns to evaluate several systems side-by-side.</li>
<li><strong>Units:</strong> Electric demand must be in <strong>kilowatts (kW)</strong>.</li>
</ul>
<h4 style="color: #0F766E; margin-top: 20px; font-weight: 600;">2. Capacity Worth Factor Table Input (<code>CWFT.csv</code>)</h4>
<p style="color: #475569; line-height: 1.6; margin-bottom: 8px;">
This file allocates fixed annual generation capacity value ($/kW-yr) into hourly weights based on grid reliability risk.
</p>
<ul style="padding-left: 20px; color: #475569; line-height: 1.6;">
<li><strong>Format:</strong> Must contain exactly <strong>8,760 rows</strong>.</li>
<li><strong>Columns:</strong> An <code>Hour</code> index column (1 to 8760) and a <code>CWFT</code> column containing the allocation weights.</li>
<li><strong>Constraint:</strong> The sum of the <code>CWFT</code> column <strong>MUST equal exactly 1.0 (100%)</strong> so that the annual capacity value is precisely recovered.</li>
</ul>
<h4 style="color: #0F766E; margin-top: 20px; font-weight: 600;">🔑 How to Find an NREL URDB Rate Label</h4>
<p style="color: #475569; line-height: 1.6; margin-bottom: 8px;">
To import custom tariffs dynamically from NREL's OpenEI database:
</p>
<ol style="padding-left: 20px; color: #475569; line-height: 1.6;">
<li>Go to the <a href="https://openei.org/wiki/Utility_Rate_Database" target="_blank" style="color: #0D9488; font-weight: 600; text-decoration: underline;">NREL Utility Rate Database (URDB)</a>.</li>
<li>Search for your utility company (e.g., <em>"Georgia Power Co"</em>) and select your target rate plan.</li>
<li>Look at the URL in your browser address bar. The <strong>Rate Label</strong> is the final segment of the URL (e.g., in <code>https://openei.org/apps/USURDB/rate/view/5d4b00595457a3e73a0e6988</code>, the label is <code>5d4b00595457a3e73a0e6988</code>).</li>
</ol>
<h4 style="color: #B45309; margin-top: 25px; border-top: 1px solid #FED7AA; padding-top: 15px; font-weight: 600;">
⚠️ Critical Alignment Rules to Satisfy Both Calculations
</h4>
<p style="color: #475569; line-height: 1.6; margin-bottom: 8px;">
Because grid risk and heat pump loads are highly non-linear and temperature-coincident, your files must align:
</p>
<ol style="padding-left: 20px; color: #475569; line-height: 1.6;">
<li><strong>Weather Year Match:</strong> Both the building load shape (E+ output) and the grid risk shape (CWFT) must represent the <strong>same historical weather year</strong> (e.g., 2012 AMY).</li>
<li><strong>Calendar Match:</strong> Both files must start on the same day of the week (e.g., if 2012 started on Sunday, Hour 1 must be Sunday for both load and CWFT).</li>
<li><strong>Local Standard Time:</strong> Disable daylight savings offsets in your building simulations to ensure hours 1 to 8760 line up exactly.</li>
</ol>
<p style="color: #64748B; font-style: italic; margin-top: 20px; border-top: 1px solid #E2E8F0; padding-top: 15px;">
💡 <b>Note:</b> A default mock setup (dual-peak 2012 weather profile for AL/GA) will be written to <code>CWFT.csv</code> and <code>load_profiles.csv</code> automatically in your main directory if the files are not found on execution.
</p>
</div>""",
        unsafe_allow_html=True
    )
else:
    if not target_states:
        st.warning("⚠️ **Selection Required:** Please choose at least one state in the sidebar multi-select.")
    else:
        try:
            # 1. Load profiles and grid aggregated data
            default_load_path = generate_default_load_profiles_file(load_profiles_filepath)
            load_profiles_df = load_load_profiles_from_csv(load_profiles_filepath)
            profile_columns = [col for col in load_profiles_df.columns if col != 'Hour']
            
            raw_df = load_and_aggregate_data(
                target_states, 
                selected_scenario, 
                weather_case, 
                target_year=meta_load_weather,
                planning_year=planning_year
            )
            datetime_series = raw_df['Datetime']
            
            # Retrieve mapped variables for reporting
            mapped_e_col = raw_df['Mapped_Energy_Col'].iloc[0] if raw_df['Mapped_Energy_Col'].iloc[0] else 'lmp_energy (default)'
            mapped_c_col = raw_df['Mapped_Carbon_Col'].iloc[0] if raw_df['Mapped_Carbon_Col'].iloc[0] else 'co2_combust (default)'
            
            # Load CWFT array
            if use_custom_cwft:
                generate_default_cwft_file(cwft_filepath)
                cwft_array = load_cwft_from_csv(cwft_filepath)
            else:
                cwft_array = raw_df['CWFT_derived'].to_numpy()
                
            results_df = calculate_avoided_costs(raw_df, cap_value, trans_value, dist_value, carbon_tax, cwft_array)
            
            # Setup Baseline and Proposed loads
            if dr_mode:
                baseline_col = st.sidebar.selectbox("Baseline Profile for DR", options=profile_columns, index=0)
                baseline_load = load_profiles_df[baseline_col].to_numpy()
                
                dr_reduction, dr_indices = dispatch_dr_program(
                    datetime_series, cwft_array, dr_hours_per_year, dr_season, dr_max_hours_per_day, dr_capacity_kw, baseline_load
                )
                proposed_load = baseline_load - dr_reduction
                load_reduction = dr_reduction
                st.sidebar.info(f"DR Mode Active: {len(dr_indices)} hours dispatched. Proposed load is Baseline - DR.")
            else:
                baseline_col = st.sidebar.selectbox("Baseline Load Profile", options=profile_columns, index=0)
                proposed_col = st.sidebar.selectbox("Proposed Load Profile", options=profile_columns, index=min(1, len(profile_columns)-1))
                baseline_load = load_profiles_df[baseline_col].to_numpy()
                proposed_load = load_profiles_df[proposed_col].to_numpy()
                load_reduction = baseline_load - proposed_load
            
            # 2. Retail Tariff Lost Revenue Calculations via URDB Compliance Engine
            if active_tariff_json is not None:
                ann_bill_baseline, bills_baseline = calculate_urdb_bill(baseline_load, datetime_series, active_tariff_json)
                ann_bill_proposed, bills_proposed = calculate_urdb_bill(proposed_load, datetime_series, active_tariff_json)
                tariff_name_label = active_tariff_json.get("name", tariff_type)
            else:
                # Custom Flat Rate Fallback
                fallback_rate_json = {
                    "fixedcharge": 0.0,
                    "energyratewindow": [[0]*24]*12,
                    "energyratestructure": [[{"rate": custom_rate_kwh}]]
                }
                if custom_demand_charge_kw > 0:
                    fallback_rate_json["demandratewindow"] = [[0]*24]*12
                    fallback_rate_json["demandratestructure"] = [[{"rate": custom_demand_charge_kw}]]
                    
                ann_bill_baseline, bills_baseline = calculate_urdb_bill(baseline_load, datetime_series, fallback_rate_json)
                ann_bill_proposed, bills_proposed = calculate_urdb_bill(proposed_load, datetime_series, fallback_rate_json)
                tariff_name_label = f"Custom Flat Rate (${custom_rate_kwh:.3f}/kWh)"
                
            annual_lost_revenue = ann_bill_baseline - ann_bill_proposed
            
            # 3. Grid Avoided Cost Calculations
            reduction_mwh = load_reduction / 1000.0
            
            gen_cap_savings_h = reduction_mwh * results_df['Gen_Capacity_Value_MWh'].to_numpy()
            trans_savings_h = reduction_mwh * results_df['Trans_Value_MWh'].to_numpy()
            dist_savings_h = reduction_mwh * results_df['Dist_Value_MWh'].to_numpy()
            energy_savings_h = reduction_mwh * results_df['Cambium_Energy_MWh'].to_numpy()
            emissions_savings_h = reduction_mwh * results_df['Emissions_Value_MWh'].to_numpy()
            total_savings_h = reduction_mwh * results_df['Total_Avoided_Cost_MWh'].to_numpy()
            
            annual_gen_cap_savings = gen_cap_savings_h.sum()
            annual_trans_savings = trans_savings_h.sum()
            annual_dist_savings = dist_savings_h.sum()
            annual_energy_savings = energy_savings_h.sum()
            annual_emissions_savings = emissions_savings_h.sum()
            annual_grid_savings = total_savings_h.sum()
            
            # 4. Multi-year NPV discounting
            years = np.arange(1, asset_life + 1)
            discount_pct = discount_rate / 100.0
            escalation_pct = escalation_rate / 100.0
            retail_escalation_pct = retail_escalation_rate / 100.0
            degradation_pct = degradation_rate / 100.0
            
            grid_esc_factors = (1 + escalation_pct) ** (years - 1)
            retail_esc_factors = (1 + retail_escalation_pct) ** (years - 1)
            deg_factors = (1 - degradation_pct) ** (years - 1)
            disc_factors = 1 / ((1 + discount_pct) ** years)
            
            grid_pv_multipliers = (grid_esc_factors * deg_factors) * disc_factors
            retail_pv_multipliers = (retail_esc_factors * deg_factors) * disc_factors
            
            npv_grid_savings = annual_grid_savings * grid_pv_multipliers.sum()
            npv_retail_lost_revenue = annual_lost_revenue * retail_pv_multipliers.sum()
            
            npv_net_savings = npv_grid_savings - npv_retail_lost_revenue
            rim_ratio = npv_grid_savings / npv_retail_lost_revenue if npv_retail_lost_revenue > 0 else 0.0
            
            # 5. Peak Coincidence, EPC & ELCC Proxy Math
            epc_baseline = (baseline_load * cwft_array).sum()
            epc_proposed = (proposed_load * cwft_array).sum()
            epc_reduction = (load_reduction * cwft_array).sum()
            
            elcc_baseline = epc_baseline / baseline_load.max() if baseline_load.max() > 0 else 0.0
            elcc_proposed = epc_proposed / proposed_load.max() if proposed_load.max() > 0 else 0.0
            # User adjustment: elcc_reduction is relative to baseline_peak_load
            elcc_reduction = epc_reduction / baseline_load.max() if baseline_load.max() > 0 else 0.0
            
            # Peak coincidence
            top_50_cwft_indices = np.argsort(-cwft_array)[:50]
            top_100_cwft_indices = np.argsort(-cwft_array)[:100]
            
            top_100_price_cutoff = results_df['Cambium_Energy_MWh'].nlargest(100).min()
            top_100_price_indices = np.where(results_df['Cambium_Energy_MWh'] >= top_100_price_cutoff)[0]
            
            coinc_50_base = baseline_load[top_50_cwft_indices].sum() / baseline_load.sum()
            coinc_50_prop = proposed_load[top_50_cwft_indices].sum() / proposed_load.sum()
            coinc_50_reduct = load_reduction[top_50_cwft_indices].sum() / load_reduction.sum() if load_reduction.sum() > 0 else 0.0
            
            coinc_100_base = baseline_load[top_100_cwft_indices].sum() / baseline_load.sum()
            coinc_100_reduct = load_reduction[top_100_cwft_indices].sum() / load_reduction.sum() if load_reduction.sum() > 0 else 0.0
            
            coinc_price_base = baseline_load[top_100_price_indices].sum() / baseline_load.sum()
            coinc_price_reduct = load_reduction[top_100_price_indices].sum() / load_reduction.sum() if load_reduction.sum() > 0 else 0.0
            
            # Peak vs Off-peak Average demand (Top 100 CWFT hours)
            peak_mask_100 = np.zeros(8760, dtype=bool)
            peak_mask_100[top_100_cwft_indices] = True
            
            avg_peak_base = baseline_load[peak_mask_100].mean()
            avg_peak_prop = proposed_load[peak_mask_100].mean()
            avg_peak_reduct = load_reduction[peak_mask_100].mean()
            
            avg_offpeak_base = baseline_load[~peak_mask_100].mean()
            avg_offpeak_prop = proposed_load[~peak_mask_100].mean()
            avg_offpeak_reduct = load_reduction[~peak_mask_100].mean()
            
            ratio_base = avg_peak_base / avg_offpeak_base if avg_offpeak_base > 0 else 0.0
            ratio_prop = avg_peak_prop / avg_offpeak_prop if avg_offpeak_prop > 0 else 0.0
            ratio_reduct = avg_peak_reduct / avg_offpeak_reduct if avg_offpeak_reduct > 0 else 0.0
            
            # Statistical Temperature-Load Weather Sensitivity Correlation Check
            months_arr = datetime_series.dt.month.to_numpy()
            temp_vals = results_df['Temperature_F'].to_numpy()
            
            heating_mask = np.isin(months_arr, [10, 11, 12, 1, 2, 3, 4, 5]) & (temp_vals < 60)
            cooling_mask = np.isin(months_arr, [6, 7, 8, 9]) & (temp_vals > 70)
            
            if heating_mask.sum() > 10:
                heat_corr = np.corrcoef(baseline_load[heating_mask], 60.0 - temp_vals[heating_mask])[0, 1]
            else:
                heat_corr = 0.0
                
            if cooling_mask.sum() > 10:
                cool_corr = np.corrcoef(baseline_load[cooling_mask], temp_vals[cooling_mask] - 70.0)[0, 1]
            else:
                cool_corr = 0.0
                
            if np.isnan(heat_corr):
                heat_corr = 0.0
            if np.isnan(cool_corr):
                cool_corr = 0.0
                
            max_corr = max(abs(heat_corr), abs(cool_corr))
            if max_corr >= 0.60:
                weather_sensitivity_status = "Responsive (Strong Temperature Correlation)"
                weather_color = "#ECFDF5"  # light green
                weather_text_color = "#065F46"
            elif max_corr >= 0.35:
                weather_sensitivity_status = "Moderate Sensitivity"
                weather_color = "#FFFBEB"  # light yellow
                weather_text_color = "#92400E"
            else:
                weather_sensitivity_status = "Unresponsive / Low Sensitivity"
                weather_color = "#FEF2F2"  # light red
                weather_text_color = "#991B1B"
                
            weather_aligned = (meta_load_weather == meta_cambium_weather == meta_cwft_weather)
            alignment_status = f"{weather_sensitivity_status} | User Label: {'Aligned' if weather_aligned else 'Mixed'}"
            
            # ==================================================================
            # TABS DISPLAY
            # ==================================================================
            tab_summary, tab_calculator, tab_grid, tab_weather_diag, tab_scenarios, tab_top_hours, tab_guide, tab_weather_gen = st.tabs([
                "📊 Overview Scorecard",
                "🔌 Retail lost revenue & RIM",
                "📅 Wholesale Grid avoided costs",
                "🌡️ Weather & peak coincidence",
                "⏳ Lifetime NPV & Scenario manager",
                "🔍 Debugger & top hours",
                "📖 EPW Calibration guide",
                "🌩️ AMY Weather Generator"
            ])
            
            # ------------------------------------------------------------------
            # TAB 1: EXECUTIVE SUMMARY
            # ------------------------------------------------------------------
            with tab_summary:
                # Weather Sensitivity and Year Alignment Row
                st.markdown(
                    f"""<div style="background-color: {weather_color}; border: 1px solid {'#10B981' if max_corr >= 0.6 else '#F59E0B' if max_corr >= 0.35 else '#EF4444'}; padding: 15px; border-radius: 8px; margin-bottom: 20px; font-size: 0.95rem; color: {weather_text_color};">
<b>Weather Sensitivity Check (NOT year alignment):</b> <b>{weather_sensitivity_status}</b> (Max $r = {max_corr:.2f}$)<br>
• Heating Season Correlation: <b>{heat_corr:.2f}</b> | • Cooling Season Correlation: <b>{cool_corr:.2f}</b><br>
• Documented Weather Years: Load = <b>{meta_load_weather}</b> | Cambium Grid = <b>{meta_cambium_weather}</b> | CWFT = <b>{meta_cwft_weather}</b> {'(Aligned)' if weather_aligned else '(Mixed)'}<br>
<i>ℹ️ Note: This check confirms temperature-driven responsiveness of the load profile, NOT perfect chronological synchronization with Cambium weather. Users must still ensure matching weather years (e.g. 2012) are loaded for both.</i>
</div>""",
                    unsafe_allow_html=True
                )
                
                # Main KPI row
                col1, col2, col3, col4, col5 = st.columns(5)
                with col1:
                    st.metric(
                        label="Net Valuation NPV",
                        value=f"${npv_net_savings:,.2f}",
                        delta=f"Avoided - Lost Rev"
                    )
                with col2:
                    badge_style = "color: #15803d; font-weight: bold;" if rim_ratio >= 1.0 else "color: #b91c1c; font-weight: bold;"
                    st.markdown(
                        f"""<div data-testid="metric-container">
<div data-testid="stMetricLabel">Ratepayer Impact Measure (RIM)</div>
<div style="font-size: 1.8rem; font-weight: 700; {badge_style}">{rim_ratio:.3f}</div>
<div style="font-size: 0.8rem; color: #64748B;">NPV Benefit / NPV Cost</div>
</div>""",
                        unsafe_allow_html=True
                    )
                with col3:
                    st.metric(
                        label="NPV Grid Avoided Costs",
                        value=f"${npv_grid_savings:,.2f}"
                    )
                with col4:
                    st.metric(
                        label="NPV Customer Bill Savings",
                        value=f"${npv_retail_lost_revenue:,.2f}"
                    )
                with col5:
                    st.metric(
                        label="EPC Reduction (kW)",
                        value=f"{epc_reduction:.2f} kW",
                        help="Effective Peak Contribution (EPC) reduction. Calculated as sum(Load Reduction * CWFT). This drives 100% of the Generation Capacity deferral savings value."
                    )
                    
                st.markdown("### ⚡ Capacity Contribution Metrics")
                c1, c2, c3 = st.columns(3)
                c1.metric(
                    label="EPC Reduction (kW)",
                    value=f"{epc_reduction:,.2f} kW",
                    help="Effective Peak Contribution (EPC) reduction. Calculated as sum(Load Reduction * CWFT). This drives 100% of the Generation Capacity deferral savings value."
                )
                c2.metric(
                    label="Baseline ELCC Proxy",
                    value=f"{elcc_baseline*100:.1f}%",
                    help="Baseline Effective Load Carrying Capability proxy. Calculated as EPC Baseline / Peak Baseline."
                )
                c3.metric(
                    label="Proposed ELCC Proxy",
                    value=f"{elcc_proposed*100:.1f}%",
                    help="Proposed Effective Load Carrying Capability proxy. Calculated as EPC Proposed / Peak Baseline."
                )
                
                st.markdown("<br>", unsafe_allow_html=True)
                
                # Quick Details
                col_info1, col_info2 = st.columns(2)
                with col_info1:
                    st.markdown("#### 🔋 Valuation Run Settings")
                    st.markdown(
                        f"""- **Customer Retail Tariff:** `{tariff_name_label}`
- **NREL Wholesale Scenario:** `{selected_scenario}`
- **Selected Weather Case:** `{weather_case}`
- **Target Region:** `{', '.join(target_states)}`
- **Demand Response Mode:** `{"Active" if dr_mode else "Inactive"}`
- **Analysis Asset Horizon:** `{asset_life} years` (discount rate: {discount_rate}%)"""
                    )
                with col_info2:
                    st.markdown("#### 📉 Capacity & Value Reduction Summary")
                    st.markdown(
                        f"""- **Baseline Profile:** `{baseline_col}` (EPC: **{epc_baseline:.2f} kW**, ELCC: **{elcc_baseline * 100:.1f}%**)
- **Proposed Profile:** `{"DR Optimised Schedule" if dr_mode else proposed_col}` (EPC: **{epc_proposed:.2f} kW**, ELCC: **{elcc_proposed * 100:.1f}%**)
- **Peak Load Reduction:** `{load_reduction.max():,.2f} kW`
- **EPC Reduction:** `**{epc_reduction:.2f} kW**` *(drives capacity avoided costs)*
- **Load Reduction ELCC Proxy:** `**{elcc_reduction * 100:.1f}%**` *(EPC reduction / Baseline Peak)*
- **Annual Load Reduction:** `{(load_reduction).sum() / 1000:,.2f} MWh`"""
                    )
                    
            # ------------------------------------------------------------------
            # TAB 2: RETAIL CALCULATOR & RIM
            # ------------------------------------------------------------------
            with tab_calculator:
                st.markdown("### 🔌 Two-Sided Cost Effectiveness Table")
                st.markdown("Annual breakdown comparing retail bill reduction (cost to utility) against wholesale grid cost deferrals (benefit to utility).")
                
                # Compute energy vs demand split for lost revenue
                if active_tariff_json is not None:
                    # To split energy and demand in URDB, we create a flat energy copy of the json
                    energy_only_json = active_tariff_json.copy()
                    energy_only_json["demandratestructure"] = None
                    energy_only_json["demandratewindow"] = None
                    
                    bill_base_e, _ = calculate_urdb_bill(baseline_load, datetime_series, energy_only_json)
                    bill_prop_e, _ = calculate_urdb_bill(proposed_load, datetime_series, energy_only_json)
                    
                    retail_energy_savings = bill_base_e - bill_prop_e
                    retail_demand_savings = annual_lost_revenue - retail_energy_savings
                else:
                    retail_energy_savings = (load_reduction * custom_rate_kwh).sum()
                    retail_demand_savings = annual_lost_revenue - retail_energy_savings
                
                # Calculate PCAF peak hours demand reduction for T&D math trace
                pcaf_mask = results_df['PCAF_Weight'].to_numpy() > 0
                avg_reduct_pcaf = load_reduction[pcaf_mask].mean() if pcaf_mask.sum() > 0 else 0.0

                # Compile side-by-side values table
                data_table = {
                    "Valuation Component": [
                        "Wholesale Energy Savings",
                        "Generation Capacity Savings",
                        "Transmission Deferral Savings",
                        "Distribution Deferral Savings",
                        "Carbon Emissions Deferral",
                        "Total Grid Avoided Cost benefits",
                        "Retail Energy Bill reduction",
                        "Retail Demand Charge reduction",
                        "Total Customer bill savings (Lost Revenue)",
                        "Net Present Value (NPV) - Grid Savings",
                        "Net Present Value (NPV) - Lost Revenue",
                        "Net Present Value (NPV) - Net Benefit",
                        "Ratepayer Impact Measure (RIM) Ratio"
                    ],
                    "Annual Unit Rate": [
                        "Hourly Cambium Price",
                        f"${cap_value:,.2f}/kW-yr × {epc_reduction:.3f} kW EPC Reduction",
                        f"${trans_value:,.2f}/kW-yr × {avg_reduct_pcaf:.3f} kW Peak Reduction",
                        f"${dist_value:,.2f}/kW-yr × {avg_reduct_pcaf:.3f} kW Peak Reduction",
                        f"${carbon_tax:,.2f} /metric ton",
                        "Sum of Grid Components",
                        "URDB TOU/Energy blocks",
                        "URDB Peak Demand blocks",
                        "Sum of Tariff Components",
                        f"NPV over {asset_life} years @ {discount_rate}% WACC",
                        f"NPV over {asset_life} years @ {discount_rate}% WACC",
                        "Grid NPV - Lost Revenue NPV",
                        "Grid NPV / Lost Revenue NPV"
                    ],
                    "Value ($/yr)": [
                        annual_energy_savings,
                        annual_gen_cap_savings,
                        annual_trans_savings,
                        annual_dist_savings,
                        annual_emissions_savings,
                        annual_grid_savings,
                        retail_energy_savings,
                        retail_demand_savings,
                        annual_lost_revenue,
                        npv_grid_savings,
                        npv_retail_lost_revenue,
                        npv_net_savings,
                        rim_ratio
                    ]
                }
                df_val = pd.DataFrame(data_table)
                
                # Format output values
                def format_vals(val, name):
                    if "Ratio" in name:
                        return f"{val:.3f}"
                    return f"${val:,.2f}"
                df_val["Value ($/yr)"] = df_val.apply(lambda r: format_vals(r["Value ($/yr)"], r["Valuation Component"]), axis=1)
                
                st.dataframe(df_val, use_container_width=True, hide_index=True)
                
                # Overlay Chart for selected week
                st.markdown("#### 🕒 Weekly Profile Load reduction & Grid costs")
                st.markdown("Review how load reduction aligns with wholesale hourly avoided cost peaks.")
                
                week_options = {
                    "Winter Peak Week (Jan 1-7)": (0, 168),
                    "Summer Peak Week (Jul 15-21)": (4680, 4848),
                    "Shoulder Week (Apr 10-16)": (2376, 2544)
                }
                selected_week = st.selectbox("Select Week Window", options=list(week_options.keys()), index=0)
                start_h, end_h = week_options[selected_week]
                
                fig_calc_overlay = make_subplots(specs=[[{"secondary_y": True}]])
                cost_slice = results_df.iloc[start_h:end_h]
                dt_slice = datetime_series.iloc[start_h:end_h]
                
                fig_calc_overlay.add_trace(
                    go.Scatter(
                        x=dt_slice, y=cost_slice['Total_Avoided_Cost_MWh'],
                        name="Grid Avoided Cost ($/MWh)",
                        line=dict(color="#8B5CF6", width=2, dash='dash')
                    ),
                    secondary_y=True
                )
                fig_calc_overlay.add_trace(
                    go.Scatter(
                        x=dt_slice, y=baseline_load[start_h:end_h],
                        name="Baseline Load (kW)", line=dict(color="#EF4444", width=1.5)
                    ),
                    secondary_y=False
                )
                fig_calc_overlay.add_trace(
                    go.Scatter(
                        x=dt_slice, y=proposed_load[start_h:end_h],
                        name="Proposed Load (kW)", line=dict(color="#0D9488", width=1.5)
                    ),
                    secondary_y=False
                )
                fig_calc_overlay.add_trace(
                    go.Scatter(
                        x=dt_slice, y=load_reduction[start_h:end_h],
                        name="Load reduction (kW)", line=dict(color="#F59E0B", width=2)
                    ),
                    secondary_y=False
                )
                
                fig_calc_overlay.update_layout(
                    template="plotly_white",
                    height=400,
                    margin=dict(l=40, r=40, t=20, b=40),
                    hovermode="x unified",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )
                fig_calc_overlay.update_yaxes(title_text="Customer Load / reduction (kW)", secondary_y=False)
                fig_calc_overlay.update_yaxes(title_text="Avoided Cost ($/MWh)", secondary_y=True)
                st.plotly_chart(fig_calc_overlay, use_container_width=True)
                
            # ------------------------------------------------------------------
            # TAB 3: GRID AVOIDED COSTS
            # ------------------------------------------------------------------
            with tab_grid:
                st.markdown("### 📅 Hourly wholesale avoided cost distribution")
                st.markdown("Distribution of the wholesale energy, generation capacity (CWFT), transmission & distribution (PCAF), and emissions value.")
                
                fig_grid_full = go.Figure()
                fig_grid_full.add_trace(go.Scatter(
                    x=results_df['Datetime'],
                    y=results_df['Total_Avoided_Cost_MWh'],
                    mode='lines',
                    name='Total avoided cost rate ($/MWh)',
                    line=dict(color='#8B5CF6', width=1.2)
                ))
                fig_grid_full.update_layout(
                    xaxis_title="Date",
                    yaxis_title="Avoided Cost ($/MWh)",
                    template="plotly_white",
                    height=380,
                    margin=dict(l=40, r=30, t=10, b=40)
                )
                st.plotly_chart(fig_grid_full, use_container_width=True)
                
                # Stacked components for peak weeks
                col_st1, col_st2 = st.columns(2)
                with col_st1:
                    st.markdown("#### ❄️ Winter morning peak details (Jan 1-7)")
                    winter_slice = results_df.iloc[0:168]
                    fig_w_stack = go.Figure()
                    
                    grid_components = [
                        ('Cambium_Energy_MWh', 'Wholesale Energy', '#F59E0B'),
                        ('Gen_Capacity_Value_MWh', 'Generation Capacity (CWFT)', '#0D9488'),
                        ('Trans_Value_MWh', 'Transmission Deferral (PCAF)', '#3B82F6'),
                        ('Dist_Value_MWh', 'Distribution Deferral (PCAF)', '#EC4899'),
                        ('Emissions_Value_MWh', 'Emissions Compliance', '#10B981')
                    ]
                    
                    for col_n, label_n, col_color in grid_components:
                        fig_w_stack.add_trace(go.Scatter(
                            x=winter_slice['Datetime'], y=winter_slice[col_n],
                            mode='lines', name=label_n, stackgroup='one',
                            line=dict(color=col_color, width=0.5)
                        ))
                    fig_w_stack.update_layout(
                        template="plotly_white", height=320,
                        margin=dict(l=40, r=20, t=10, b=40),
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                    )
                    st.plotly_chart(fig_w_stack, use_container_width=True)
                    
                with col_st2:
                    st.markdown("#### ☀️ Summer afternoon peak details (Jul 15-21)")
                    summer_slice = results_df.iloc[4680:4848]
                    fig_s_stack = go.Figure()
                    for col_n, label_n, col_color in grid_components:
                        fig_s_stack.add_trace(go.Scatter(
                            x=summer_slice['Datetime'], y=summer_slice[col_n],
                            mode='lines', name=label_n, stackgroup='one',
                            line=dict(color=col_color, width=0.5),
                            showlegend=False
                        ))
                    fig_s_stack.update_layout(
                        template="plotly_white", height=320,
                        margin=dict(l=40, r=20, t=10, b=40)
                    )
                    st.plotly_chart(fig_s_stack, use_container_width=True)
                    
            # ------------------------------------------------------------------
            # TAB 4: WEATHER & PEAK COINCIDENCE DIAGNOSTICS
            # ------------------------------------------------------------------
            with tab_weather_diag:
                st.markdown("### 🌡️ Temperature & grid coincidence diagnostics")
                
                # Extreme temperature statistics
                temp_vals = results_df['Temperature_F'].to_numpy()
                min_t = temp_vals.min()
                max_t = temp_vals.max()
                hrs_15 = (temp_vals < 15.0).sum()
                hrs_95 = (temp_vals > 95.0).sum()
                hrs_100 = (temp_vals > 100.0).sum()
                
                # CWFT during coldest and hottest hours
                coldest_20_idx = np.argsort(temp_vals)[:20]
                hottest_20_idx = np.argsort(-temp_vals)[:20]
                avg_cwft_coldest = cwft_array[coldest_20_idx].mean()
                avg_cwft_hottest = cwft_array[hottest_20_idx].mean()
                
                st.markdown("#### 🌨️ Temperature distribution check")
                col_diag1, col_diag2, col_diag3, col_diag4, col_diag5 = st.columns(5)
                with col_diag1:
                    st.metric("Minimum temp", f"{min_t:.1f} °F")
                with col_diag2:
                    st.metric("Maximum temp", f"{max_t:.1f} °F")
                with col_diag3:
                    st.metric("Hours < 15°F", f"{hrs_15} hrs")
                with col_diag4:
                    st.metric("Hours > 95°F", f"{hrs_95} hrs")
                with col_diag5:
                    st.metric("Hours > 100°F", f"{hrs_100} hrs")
                    
                col_coinc1, col_coinc2 = st.columns(2)
                with col_coinc1:
                    st.metric("Avg CWFT during coldest 20 hours", f"{avg_cwft_coldest:.6f}")
                with col_coinc2:
                    st.metric("Avg CWFT during hottest 20 hours", f"{avg_cwft_hottest:.6f}")
                    
                st.markdown("<hr>", unsafe_allow_html=True)
                st.markdown("#### ⚡ Peak coincidence metrics")
                st.markdown("Displays the share (%) of annual electricity energy consumption that occurs during critical high-stress grid hours.")
                
                coinc_table = {
                    "Coincidence Metric": [
                        "Energy share in top 50 CWFT hours (%)",
                        "Energy share in top 100 CWFT hours (%)",
                        "Energy share in highest 100 price hours (%)",
                        "Effective Peak Contribution (EPC) (kW)",
                        "Effective load carrying capability proxy (%)"
                    ],
                    "Baseline load": [
                        f"{coinc_50_base * 100:.2f}%",
                        f"{coinc_100_base * 100:.2f}%",
                        f"{coinc_price_base * 100:.2f}%",
                        f"{epc_baseline:.2f} kW",
                        f"{elcc_baseline * 100:.1f}%"
                    ],
                    "Proposed load": [
                        f"{coinc_50_prop * 100:.2f}%",
                        f"{proposed_load[top_100_cwft_indices].sum() / proposed_load.sum() * 100:.2f}%",
                        f"{proposed_load[top_100_price_indices].sum() / proposed_load.sum() * 100:.2f}%",
                        f"{epc_proposed:.2f} kW",
                        f"{elcc_proposed * 100:.1f}%"
                    ],
                    "Load reduction": [
                        f"{coinc_50_reduct * 100:.2f}%" if load_reduction.sum() > 0 else "0.00%",
                        f"{coinc_100_reduct * 100:.2f}%" if load_reduction.sum() > 0 else "0.00%",
                        f"{coinc_price_reduct * 100:.2f}%" if load_reduction.sum() > 0 else "0.00%",
                        f"{epc_reduction:.2f} kW",
                        f"{elcc_reduction * 100:.1f}%" if load_reduction.max() > 0 else "0.00%"
                    ]
                }
                st.dataframe(pd.DataFrame(coinc_table), use_container_width=True, hide_index=True)
                st.info("💡 **ELCC & EPC Note:** EPC is the weighted average load during peak risk hours: `sum(Load * CWFT)`. The ELCC proxy represents the percentage of peak demand that contributes to capacity: `EPC / Peak Load` (or `EPC / Baseline Peak` for the load reduction resource).")
                
                st.markdown("<br>", unsafe_allow_html=True)
                st.markdown("#### 📊 Peak vs. Off-Peak Demand Diagnostics (Top 100 CWFT Hours)")
                st.markdown("Quantifies electricity demand behavior during the Top 100 reliability constraint hours vs. the rest of the year.")
                
                demand_diag_table = {
                    "Demand Metric": [
                        "Average Demand during Top 100 CWFT Peaks (kW)",
                        "Average Demand during Off-Peak Hours (kW)",
                        "Peak-to-Off-Peak Demand Ratio"
                    ],
                    "Baseline load": [
                        f"{avg_peak_base:.3f} kW",
                        f"{avg_offpeak_base:.3f} kW",
                        f"{ratio_base:.3f}"
                    ],
                    "Proposed load": [
                        f"{avg_peak_prop:.3f} kW",
                        f"{avg_offpeak_prop:.3f} kW",
                        f"{ratio_prop:.3f}"
                    ],
                    "Load reduction": [
                        f"{avg_peak_reduct:.3f} kW",
                        f"{avg_offpeak_reduct:.3f} kW",
                        f"{ratio_reduct:.3f}"
                    ]
                }
                st.dataframe(pd.DataFrame(demand_diag_table), use_container_width=True, hide_index=True)

            # ------------------------------------------------------------------
            # TAB 5: LIFETIME NPV & SCENARIO MANAGER
            # ------------------------------------------------------------------
            with tab_scenarios:
                st.markdown("### ⏳ Lifetime NPV Discounting & Case manager")
                
                # Save scenario current run section
                col_save1, col_save2 = st.columns([3, 1])
                with col_save1:
                    scenario_run_name = st.text_input("Enter Scenario Run name to save", value="Base Run")
                with col_save2:
                    st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                    if st.button("💾 Save Current Run", type="secondary", use_container_width=True):
                        new_run = {
                            "Name": scenario_run_name,
                            "Grid Scenario": selected_scenario,
                            "Weather Case": weather_case,
                            "Retail Tariff": tariff_name_label,
                            "Alignment": alignment_status,
                            "Net NPV ($)": npv_net_savings,
                            "RIM Ratio": rim_ratio,
                            "ELCC proxy (%)": f"{elcc_reduction * 100:.1f}%",
                            "Gen Capacity savings ($)": annual_gen_cap_savings,
                            "T&D Deferral savings ($)": annual_trans_savings + annual_dist_savings,
                            "Lost Revenue ($)": annual_lost_revenue
                        }
                        st.session_state['saved_runs'].append(new_run)
                        st.success(f"Saved run '{scenario_run_name}' to scenario list!")
                        
                # Table of saved runs
                if st.session_state['saved_runs']:
                    st.markdown("#### 📊 Side-by-side run comparisons")
                    runs_df = pd.DataFrame(st.session_state['saved_runs'])
                    
                    st.dataframe(
                        runs_df.style.format({
                            "Net NPV ($)": "${:,.2f}",
                            "RIM Ratio": "{:.3f}",
                            "Gen Capacity savings ($)": "${:,.2f}",
                            "T&D Deferral savings ($)": "${:,.2f}",
                            "Lost Revenue ($)": "${:,.2f}"
                        }),
                        use_container_width=True, hide_index=True
                    )
                    
                    if st.button("🗑️ Clear saved runs"):
                        st.session_state['saved_runs'] = []
                        st.rerun()
                else:
                    st.info("No saved runs. Give your current configuration a name and click **Save Current Run** to build a comparison database.")
                    
                st.markdown("<hr>", unsafe_allow_html=True)
                st.markdown("#### 📈 Discounted cash flow streams")
                # Cash Flow Plotly Bar Chart
                projected_grid_nominal = annual_grid_savings * grid_esc_factors * deg_factors
                projected_grid_disc = annual_grid_savings * grid_pv_multipliers
                
                projected_lost_nominal = annual_lost_revenue * retail_esc_factors * deg_factors
                projected_lost_disc = annual_lost_revenue * retail_pv_multipliers
                
                fig_lifetime = go.Figure()
                fig_lifetime.add_trace(go.Bar(
                    x=years, y=projected_grid_nominal,
                    name='Nominal Grid savings', marker_color='#F59E0B'
                ))
                fig_lifetime.add_trace(go.Bar(
                    x=years, y=projected_grid_disc,
                    name='Discounted Grid NPV', marker_color='#0D9488'
                ))
                fig_lifetime.add_trace(go.Bar(
                    x=years, y=projected_lost_disc,
                    name='Discounted Lost Revenue NPV', marker_color='#EF4444'
                ))
                
                fig_lifetime.update_layout(
                    title="Nominal vs. Discounted present value streams",
                    xaxis_title="Operating Year",
                    yaxis_title="Annual value ($)",
                    template="plotly_white",
                    height=350,
                    margin=dict(l=40, r=20, t=30, b=40),
                    barmode='group',
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )
                st.plotly_chart(fig_lifetime, use_container_width=True)

            # ------------------------------------------------------------------
            # TAB 6: DEBUGGER & TOP VALUE HOURS EXPORT
            # ------------------------------------------------------------------
            with tab_top_hours:
                st.markdown("### 🔍 Validation and top avoided cost constraint hours")
                
                # Check validation items
                cwft_sum = cwft_array.sum()
                capacity_math_ok = np.isclose(annual_gen_cap_savings, cap_value * (load_reduction * cwft_array).sum(), atol=1e-2)
                shape_length_ok = (len(baseline_load) == 8760) and (len(proposed_load) == 8760)
                
                st.markdown("#### ⚙️ Validation checks")
                col_chk1, col_chk2, col_chk3, col_chk4 = st.columns(4)
                with col_chk1:
                    if np.isclose(cwft_sum, 1.0, atol=1e-3):
                        st.success(f"✓ Sum(CWFT) = {cwft_sum:.4f}")
                    else:
                        st.error(f"✗ Sum(CWFT) = {cwft_sum:.4f}")
                with col_chk2:
                    if capacity_math_ok:
                        st.success(f"✓ Capacity ECC x EPC matches")
                    else:
                        st.warning(f"⚠ Capacity ECC x EPC warning")
                with col_chk3:
                    if shape_length_ok:
                        st.success(f"✓ Shapes match 8760 hrs")
                    else:
                        st.error(f"✗ Shapes mismatch 8760 hrs")
                with col_chk4:
                    st.info(f"⚡ Mapped: Energy $\\rightarrow$ `{mapped_e_col}`, Carbon $\\rightarrow$ `{mapped_c_col}`")
                        
                st.markdown("<br>", unsafe_allow_html=True)
                st.markdown("#### 🧮 Capacity avoided cost mathematical trace")
                st.markdown(
                    f"""This trace proves the causality between building load shape reduction and capacity credits.
- **Generation Capacity avoided costs:**
  $$\\text{{Capacity Credit}} = \\text{{ECC}} \\times \\text{{EPC Reduction}} = \\${cap_value:,.2f}/\\text{{kW-yr}} \\times {epc_reduction:.4f}\\text{{ kW}} = \\mathbf{{\\${cap_value * epc_reduction:,.2f}/\\text{{yr}}}}$$
  *(Matches Gen Capacity Avoided Costs: **${annual_gen_cap_savings:,.2f}/yr**)*
- **Transmission Deferral avoided costs:**
  $$\\text{{Transmission Credit}} = \\text{{Transmission Scalar}} \\times \\text{{Peak Avg Reduction}} = \\${trans_value:,.2f}/\\text{{kW-yr}} \\times {avg_reduct_pcaf:.4f}\\text{{ kW}} = \\mathbf{{\\${trans_value * avg_reduct_pcaf:,.2f}/\\text{{yr}}}}$$
  *(Matches Transmission Deferral Avoided Costs: **${annual_trans_savings:,.2f}/yr**)*
- **Distribution Deferral avoided costs:**
  $$\\text{{Distribution Credit}} = \\text{{Distribution Scalar}} \\times \\text{{Peak Avg Reduction}} = \\${dist_value:,.2f}/\\text{{kW-yr}} \\times {avg_reduct_pcaf:.4f}\\text{{ kW}} = \\mathbf{{\\${dist_value * avg_reduct_pcaf:,.2f}/\\text{{yr}}}}$$
  *(Matches Distribution Deferral Avoided Costs: **${annual_dist_savings:,.2f}/yr**)*
"""
                )
                st.markdown("<hr>", unsafe_allow_html=True)
                
                # Top value hours selection
                st.markdown("#### 🔑 Top avoided cost constraint hours")
                st.markdown("Exposes hours with highest value to verify temperature coincidences and clean calendar shifts.")
                
                top_limit = st.slider("Select number of peak hours to export", min_value=10, max_value=100, value=50, step=10)
                
                sort_col = st.selectbox("Sort top hours by:", ["Total avoided cost rate ($/MWh)", "CWFT weight", "Wholesale marginal energy price ($/MWh)"])
                
                results_df_present = results_df.copy()
                results_df_present.rename(columns={
                    'Hour': 'Hour index',
                    'Datetime': 'Date & Time',
                    'Cambium_Energy_MWh': 'Wholesale marginal energy price ($/MWh)',
                    'Gen_Capacity_Value_MWh': 'Generation capacity component ($/MWh)',
                    'Trans_Value_MWh': 'Transmission component ($/MWh)',
                    'Dist_Value_MWh': 'Distribution component ($/MWh)',
                    'Emissions_Value_MWh': 'Emissions component ($/MWh)',
                    'Total_Avoided_Cost_MWh': 'Total avoided cost rate ($/MWh)',
                    'CWFT': 'CWFT weight'
                }, inplace=True)
                
                top_hours = results_df_present.sort_values(by=sort_col, ascending=False).head(top_limit)
                
                st.dataframe(
                    top_hours[[
                        'Hour index', 'Date & Time', 'Temperature_F', 'Wholesale marginal energy price ($/MWh)',
                        'Generation capacity component ($/MWh)', 'Transmission component ($/MWh)',
                        'Distribution component ($/MWh)', 'Emissions component ($/MWh)',
                        'Total avoided cost rate ($/MWh)', 'CWFT weight'
                    ]].style.format({
                        'Date & Time': lambda x: x.strftime('%b %d, %H:%M'),
                        'Temperature_F': '{:.1f} °F',
                        'Wholesale marginal energy price ($/MWh)': '${:,.2f}',
                        'Generation capacity component ($/MWh)': '${:,.2f}',
                        'Transmission component ($/MWh)': '${:,.2f}',
                        'Distribution component ($/MWh)': '${:,.2f}',
                        'Emissions component ($/MWh)': '${:,.2f}',
                        'Total avoided cost rate ($/MWh)': '${:,.2f}',
                        'CWFT weight': '{:.6f}'
                    }),
                    use_container_width=True, hide_index=True
                )
                
                debug_csv = top_hours.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label=f"📥 Download Top {top_limit} Stress Hours CSV",
                    data=debug_csv,
                    file_name=f"top_{top_limit}_stress_hours.csv",
                    mime="text/csv",
                    use_container_width=True
                )

            # ------------------------------------------------------------------
            # TAB 7: CALIBRATION GUIDE
            # ------------------------------------------------------------------
            with tab_guide:
                st.markdown("### 🌡️ EPW & Weather Calibration Guide")
                st.markdown(
                    """To conduct a valid Marginal Cost study for electric heat pumps, water heaters, or battery storage, 
the simulated hourly demand shapes must line up with the grid dataset chronologically."""
                )
                
                st.warning(
                    "⚠️ **CRITICAL ALIGNMENT RULES:**\n\n"
                    "1. **Weather Year Sync:** Ensure your building simulator uses the **2012 AMY (Actual Meteorological Year)** weather file (`.epw`). Mismatched years displace winter cold snaps, skewing the capacity coincidence value.\n\n"
                    "2. **Calendar Shift:** 2012 began on a **Sunday**. Ensure your load simulation starts on a Sunday so weekend occupied patterns align with Cambium grid weekday rate periods.\n\n"
                    "3. **Standard Time:** Standardize on **Local Standard Time (LST)** year-round. Mismatched daylight savings transitions displace load spikes by 1 hour, incorrectly zeroing out capacity savings."
                )

            # ------------------------------------------------------------------
            # TAB 8: AMY WEATHER GENERATOR (diyepw)
            # ------------------------------------------------------------------
            with tab_weather_gen:
                st.markdown("### 🌩️ AMY EPW Weather Generator (`diyepw`)")
                st.markdown(
                    """This utility automates the generation of **Actual Meteorological Year (AMY) EPW weather files** 
using PNNL's `diyepw` tool. It automatically downloads observations from the NOAA Integrated Surface Database (ISD),
interpolates missing points, and builds a customized `.epw` file using NREL's TMY3 as a template."""
                )
                
                st.info(
                    "💡 **Requirements:** Generating files requires an active internet connection to download "
                    "NOAA observations (~1MB per station/year) and NREL TMY3 templates. The process may take 1-2 minutes."
                )
                
                col1, col2 = st.columns(2)
                with col1:
                    wmo_id = st.number_input(
                        "WMO Station ID (6-digit)",
                        min_value=100000,
                        max_value=999999,
                        value=722300, # Default: Birmingham Shuttlesworth, AL
                        help="Check WMO IDs for your location from NOAA or climate databases. E.g. Atlanta, GA is 722190."
                    )
                    
                    target_year = st.selectbox(
                        "Weather Observation Year",
                        options=[2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024],
                        index=2 # Default: 2012
                    )
                
                with col2:
                    weather_destination = st.selectbox(
                        "Weather Case Destination Folder",
                        options=["Baseline", "Extreme_Winter", "Extreme_Summer"],
                        index=0,
                        help="Determines which 'Weather_Data_raw/' folder the generated EPW file will be saved in."
                    )
                    
                    st.write("") # spacing
                    st.write("")
                    generate_button = st.button("⚡ Generate AMY Weather File", type="primary", use_container_width=True)
                
                if generate_button:
                    try:
                        # Local import of diyepw to prevent app startup failure if not installed
                        import diyepw
                        
                        target_dir = os.path.join("Weather_Data_raw", weather_destination)
                        os.makedirs(target_dir, exist_ok=True)
                        
                        with st.spinner(f"Downloading observations and generating AMY EPW for WMO {wmo_id} (Year {target_year})..."):
                            diyepw.create_amy_epw_files_for_years_and_wmos(
                                years=[target_year],
                                wmos=[wmo_id],
                                max_records_to_interpolate=10,
                                max_records_to_impute=25,
                                max_missing_amy_rows=5,
                                allow_downloads=True,
                                amy_epw_dir=target_dir
                            )
                        st.success(f"🎉 Success! AMY EPW file generated and saved to: `Weather_Data_raw/{weather_destination}/`")
                        st.balloons()
                        
                    except ImportError:
                        st.error(
                            "❌ **Missing Library:** The `diyepw` package is not installed. "
                            "Please run `pip install diyepw` in your environment to use this generator."
                        )
                    except Exception as e:
                        st.error(f"❌ **Error generating EPW file:** {str(e)}")
                        st.info("Check that the WMO ID is valid and that you have a stable internet connection.")

        except Exception as e:
            st.error(f"❌ **Data Processing/CSV Parsing Error:** {str(e)}")
            st.info("Check your inputs and file paths. Ensure files represent exactly 8760 hours.")
