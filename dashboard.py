import streamlit as st
import pandas as pd
import json

# 1. Page Configuration
st.set_page_config(page_title="AI Watchdog", layout="wide", page_icon="🚨")
st.title("🚨 AI Vendor SRE Dashboard: Twilio")
st.markdown("Automated architecture monitoring powered by **Groq** and **Llama 3**.")
st.divider()

# 2. Load the Local Data
try:
    with open("watchdog_alerts.json", "r") as f:
        alerts = json.load(f)
except FileNotFoundError:
    alerts = []

# 3. Build the Visuals
if not alerts:
    st.success("✅ **System Status:** All monitored messaging & email services are operational.")
else:
    # Convert JSON to a Pandas DataFrame
    df = pd.DataFrame(alerts)
    
    # Ensure 'category' exists for backward compatibility with older test runs
    if 'category' not in df.columns:
        df['category'] = 'SRE Incident' # Default fallback for older tests
        
    # Split the data into two separate DataFrames
    sre_df = df[df['category'] == 'SRE Incident']
    arch_df = df[df['category'] == 'Architecture Deprecation']
    
    # Top-level metric scorecards side-by-side
    col1, col2 = st.columns(2)
    col1.metric(label="🔴 Active SRE Incidents", value=len(sre_df))
    col2.metric(label="⚠️ Architecture Deprecations", value=len(arch_df))
    
    st.divider()
    
    # Define a smart column order that handles both old and new variable names
    ideal_columns = ['logged_at', 'timestamp', 'product_impacted', 'type', 'status', 'status_or_date', 'title', 'impact_summary']
    available_cols = [c for c in ideal_columns if c in df.columns]
    
    # ==========================================
    # SECTION 1: SRE INCIDENTS
    # ==========================================
    st.subheader("🔴 Live SRE Incidents")
    if not sre_df.empty:
        st.dataframe(
            sre_df[available_cols],
            use_container_width=True,
            hide_index=True
        )
    else:
        st.success("✅ No active live incidents.")
        
    st.markdown("<br>", unsafe_allow_html=True)
    
    # ==========================================
    # SECTION 2: ARCHITECTURE DEPRECATIONS
    # ==========================================
    st.subheader("⚠️ Architecture Deprecations & Breaking Changes")
    if not arch_df.empty:
        st.dataframe(
            arch_df[available_cols],
            use_container_width=True,
            hide_index=True
        )
    else:
        st.success("✅ No upcoming deprecations found.")
