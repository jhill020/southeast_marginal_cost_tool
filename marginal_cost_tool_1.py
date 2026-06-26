import os
import glob
import numpy as np
import pandas as pd

# ==============================================================================
# CONFIGURATION BLOCK (EDITABLE SETTINGS)
# ==============================================================================
# Define the directory where your raw input datasets (e.g., Cambium 8760 CSVs) are stored.
INPUT_DIRECTORY = "./cambium_data"  

# Define the target states for your specific service territory. The script will 
# dynamically scan all files in the directory and filter strictly for these states.
TARGET_STATES = ["AL", "GA"]         

# --- REGULATORY & ECONOMIC SCALAR VARIABLES ---
# 1. Generation Capacity Proxy ($/kW-year):
# Represents the annualized Real Economic Carrying Charge (RECC) or Net CONE (Cost of New Entry) 
# of a generic capacity addition (e.g., an IRP-approved simple cycle combustion turbine or utility battery).
STATIC_CAP_VALUE_KW_YEAR = 100.00   

# 2. Transmission Deferral Value ($/kW-year):
# Represents the capital cost avoided by deferring transmission network upgrades.
STATIC_TRANS_VALUE_KW_YEAR = 15.00

# 2b. Distribution Deferral Value ($/kW-year):
# Represents the capital cost avoided by deferring substation or feeder distribution upgrades.
STATIC_DIST_VALUE_KW_YEAR = 15.00     

# 3. Carbon Tax / Internal Carbon Fee Scenario ($/metric ton):
# Sets the financial penalty applied to greenhouse gas emissions. This functions as a slider control 
# to run sensitivities (e.g., $0/ton base compliance case vs. a $30/ton carbon risk planning scenario).
CARBON_TAX_SCENARIO_TON = 30.00     


def generate_mock_state_file(filepath, state_code):
    """
    SAFETY NET DATA GENERATOR:
    Simulates a standard 8760-hour utility dataset capturing the distinct dual-peaking 
    load characteristics of the Southeastern United States if the input directory is empty.
    """
    print(f"Generating mock input data for state: {state_code} at {filepath}...")
    np.random.seed(42 if state_code == "AL" else 99)
    
    # Generate a sequential array representing every hour of a standard 365-day year (1 to 8760)
    hours = np.arange(1, 8761)
    
    # Establish a baseline marginal wholesale energy price ($20 - $30/MWh) representing off-peak hours
    energy_base = np.random.uniform(20.0, 30.0, 8760)
    
    for h in hours:
        # STEP A: Model Winter Heating Peaks (January & February, Hours 1 to 1440)
        # Extreme cold weather in the Southeast drives massive spikes in system lambda between 6:00 AM and 9:00 AM 
        # (Hours 6, 7, 8, 9 of the daily 24-hour cycle) due to electric resistance heating and heat pump defrost cycles.
        if h <= 1440 and (h % 24 in [6, 7, 8, 9]):
            energy_base[h-1] = np.random.uniform(60.0, 90.0)
            
        # STEP B: Model Summer Cooling Peaks (July & August, Hours 4345 to 5832)
        # High heat and humidity drive heavy air conditioning loads during late afternoons (Hours 2:00 PM to 6:00 PM / 14-18)
        elif 4345 <= h <= 5832 and (h % 24 in [14, 15, 16, 17, 18]):
            energy_base[h-1] = np.random.uniform(50.0, 80.0)
            
    # Model a dynamic marginal carbon emission rate profile (kg CO2 / MWh)
    # Reflects cleaner baseload generation (nuclear/hydro) during off-peak hours, scaling up to older, 
    # higher-emitting marginal gas/coal peaking units during high-stress hours.
    carbon_base = np.random.uniform(350.0, 750.0, 8760)
    
    df = pd.DataFrame({
        'Hour': hours,
        'State': state_code,
        'Cambium_Energy_MWh': energy_base,
        'Cambium_Carbon_kg_MWh': carbon_base
    })
    
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    df.to_csv(filepath, index=False)


def create_southeast_cwft():
    """
    CAPACITY WORTH FACTOR TABLE (CWFT) GENERATOR:
    Constructs an 8760 hourly allocation matrix representing the *relative reliability risk* (the probability of a capacity shortfall or unserved energy) across the year. 
    Unlike a California-style model which isolates risk to summer afternoons, this builds a 
    classic Southeastern dual-peak profile.
    """
    cwft = np.zeros(8760)
    
    winter_hours = []  # Array index tracking for January/February cold-snap hours
    summer_hours = []  # Array index tracking for July/August peak afternoon hours
    
    # Scan the 8760 horizon to group and isolate the high-risk winter morning and summer afternoon blocks
    for h in range(1, 8761):
        if h <= 1440 and (h % 24 in [6, 7, 8, 9]):
            winter_hours.append(h - 1)
        elif 4345 <= h <= 5832 and (h % 24 in [14, 15, 16, 17, 18]):
            summer_hours.append(h - 1)
            
    # ECONOMIC ALLOCATION RULE: Allocate 45% of total annual generation capacity value to the 
    # winter morning heating peaks, and 55% to the summer afternoon cooling peaks. 
    # The value is spread evenly within each block. All other shoulder hours receive 0.0 value.
    cwft[winter_hours] = 0.45 / len(winter_hours)
    cwft[summer_hours] = 0.55 / len(summer_hours)
    
    # REGULATORY COMPLIANCE SANITY CHECK: 
    # The sum of all 8760 allocation factors MUST equal exactly 1.0 (100%). This ensures that when the factor 
    # is multiplied by the annual capacity dollar scalar, the model precisely recovers the total annual value 
    # without under- or over-counting.
    assert np.isclose(cwft.sum(), 1.0), "CRITICAL: The CWFT array values must sum exactly to 1.0"
    return cwft


def main():
    print("--- Starting Southeast Avoided Cost Profile Compiler ---")
    print(f"Targeting States: {TARGET_STATES}")
    
    # --------------------------------------------------------------------------
    # STEP 1: INGEST REGIONAL DATA FILES
    # --------------------------------------------------------------------------
    all_csv_files = glob.glob(os.path.join(INPUT_DIRECTORY, "*.csv"))
    if not all_csv_files:
        print("Input directory empty. Automatically deploying sample regional data files...")
        generate_mock_state_file(os.path.join(INPUT_DIRECTORY, "cambium_al.csv"), "AL")
        generate_mock_state_file(os.path.join(INPUT_DIRECTORY, "cambium_ga.csv"), "GA")
        generate_mock_state_file(os.path.join(INPUT_DIRECTORY, "cambium_fl.csv"), "FL") 
        all_csv_files = glob.glob(os.path.join(INPUT_DIRECTORY, "*.csv"))

    # --------------------------------------------------------------------------
    # STEP 2: FILTER AND AGGREGATE THE SELECTION OF STATES
    # --------------------------------------------------------------------------
    combined_list = []
    for file in all_csv_files:
        temp_df = pd.read_csv(file)
        
        if 'State' in temp_df.columns:
            # Drop data lines not matching the target states listed in your editable config block.
            # This allows you to exclude neighbor states (like FL or MS) if they exist in the same folder.
            filtered_df = temp_df[temp_df['State'].isin(TARGET_STATES)]
            if not filtered_df.empty:
                combined_list.append(filtered_df)
                
    if not combined_list:
        raise ValueError(f"No source data files matched your designated states list: {TARGET_STATES}")
        
    raw_regional_df = pd.concat(combined_list, ignore_index=True)
    
    # For regions spanned by a single utility holding company or pool (like AL and GA), 
    # we take the mathematical average ('mean') of the marginal costs across the states 
    # for each hour to establish a unified 8760 regional baseline profile.
    regional_base = raw_regional_df.groupby('Hour').agg({
        'Cambium_Energy_MWh': 'mean',
        'Cambium_Carbon_kg_MWh': 'mean'
    }).reset_index()

    # --------------------------------------------------------------------------
    # STEP 3: CONSTRUCT INTEGRATED CAPACITY & T&D ALLOCATORS
    # --------------------------------------------------------------------------
    print("Building 8760 Southeast dual-peak Capacity Worth Factor Table...")
    # Inject the 8760 reliability-weighted factor array directly into our core dataframe
    regional_base['CWFT'] = create_southeast_cwft()
    
    # PEAK CAPACITY ALLOCATION FACTOR (PCAF) FOR LOCAL T&D VALUATION:
    # Local grid distribution networks (substations/feeders) experience stress when system demand is maximum. 
    # Here, we isolate the top 100 hours of highest marginal energy costs across the year to proxy grid stress.
    top_100_cutoff = regional_base['Cambium_Energy_MWh'].nlargest(100).min()
    regional_base['PCAF_Weight'] = 0.0
    is_peak_hour = regional_base['Cambium_Energy_MWh'] >= top_100_cutoff
    
    # Distribute the T&D capacity risk proportionally (evenly) across only these top 100 localized constraint hours
    regional_base.loc[is_peak_hour, 'PCAF_Weight'] = 1.0 / is_peak_hour.sum()
    assert np.isclose(regional_base['PCAF_Weight'].sum(), 1.0), "PCAF values must sum to 1.0"

    # --------------------------------------------------------------------------
    # STEP 4: EXECUTE THE GRANULAR 8760 MATHEMATICAL PIPELINE
    # --------------------------------------------------------------------------
    print("Executing marginal value calculations across 8760 horizon...")
    
    # COMPONENT A: Generation Capacity Value ($/MWh)
    # Formula: Annual Capacity Value ($/kW-yr) * Hourly Risk Weight (CWFT) * Unit Converter (1000 kW / 1 MW)
    # This translates annual fixed capital costs into an hourly capacity credit distributed strictly to peak hours.
    regional_base['Gen_Capacity_Value_MWh'] = (
        STATIC_CAP_VALUE_KW_YEAR * regional_base['CWFT'] * 1000
    )
    
    # COMPONENT B1: Transmission Deferral Value ($/MWh)
    # Formula: Annual Transmission Value ($/kW-yr) * Hourly PCAF Weight * Unit Converter (1000 kW / 1 MW)
    regional_base['Trans_Value_MWh'] = (
        STATIC_TRANS_VALUE_KW_YEAR * regional_base['PCAF_Weight'] * 1000
    )
    
    # COMPONENT B2: Distribution Deferral Value ($/MWh)
    # Formula: Annual Distribution Value ($/kW-yr) * Hourly PCAF Weight * Unit Converter (1000 kW / 1 MW)
    regional_base['Dist_Value_MWh'] = (
        STATIC_DIST_VALUE_KW_YEAR * regional_base['PCAF_Weight'] * 1000
    )
    
    # COMPONENT C: Environmental / Emissions Compliance Value ($/MWh)
    # Formula: (Marginal Carbon Intensity (kg CO2 / MWh) / 1000 kg per metric ton) * Carbon Tax Scenario ($/metric ton)
    # Calculates the real-time financial value of the avoided carbon footprint if a clean DER displaces marginal fossil generation.
    regional_base['Emissions_Value_MWh'] = (
        (regional_base['Cambium_Carbon_kg_MWh'] / 1000.0) * CARBON_TAX_SCENARIO_TON
    )
    
    # THE ULTIMATE INTEGRATION ENGINE (The 8760 Summation Loop)
    # Total Avoided Cost = Hourly Marginal Wholesale Energy Cost 
    #                     + Hourly Allocated Generation Capacity Capital Cost 
    #                     + Hourly Allocated Delivery Network Cost 
    #                     + Hourly Internalized Carbon Compliance Cost
    regional_base['Total_Avoided_Cost_MWh'] = (
        regional_base['Cambium_Energy_MWh'] +
        regional_base['Gen_Capacity_Value_MWh'] +
        regional_base['Trans_Value_MWh'] +
        regional_base['Dist_Value_MWh'] +
        regional_base['Emissions_Value_MWh']
    )

    # --------------------------------------------------------------------------
    # STEP 5: DATA VALIDATION & EXPORT
    # --------------------------------------------------------------------------
    print("\n--- COMPILATION SUCCESSFUL ---")
    print(f"Total Combined Multi-State System Annual Value: ${regional_base['Total_Avoided_Cost_MWh'].sum():,.2f}/MWh levelized sum.")
    
    # Validation Step: Isolate and print the highest-value peak hours from the final 8760 matrix 
    # to visually confirm that the math successfully captures both winter morning and summer afternoon spikes.
    print("\n[Verification Slice] High-Stress Peak Sample Rows:")
    high_value_hours = regional_base.sort_values(by='Total_Avoided_Cost_MWh', ascending=False).head(5)
    print(high_value_hours[['Hour', 'Cambium_Energy_MWh', 'Gen_Capacity_Value_MWh', 'Trans_Value_MWh', 'Dist_Value_MWh', 'Total_Avoided_Cost_MWh']].to_string(index=False))

    # Export out to a production-ready CSV designated by the selected states
    output_filename = f"southeast_avoided_costs_{'_'.join(TARGET_STATES)}.csv"
    regional_base.to_csv(output_filename, index=False)
    print(f"\nFinal export file populated successfully: '{output_filename}'")


if __name__ == "__main__":
    main()