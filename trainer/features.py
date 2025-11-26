import pandas as pd
import numpy as np
from datetime import datetime

def build_features(df):
    df['ts'] = pd.to_datetime(df['ts'])
    df = df.sort_values('ts')
    df['heure'] = df['ts'].dt.hour
    df['jour_semaine'] = df['ts'].dt.weekday
    df['mois'] = df['ts'].dt.month
    df['est_weekend'] = df['jour_semaine'] >= 5
    # lag features
    df['dispo_lag_1h'] = df.groupby('station_id')['available'].shift(1).fillna(method='bfill')
    df['dispo_lag_24h'] = df.groupby('station_id')['available'].shift(24).fillna(method='bfill')
    df['moy_3h'] = df.groupby('station_id')['available'].rolling(3,min_periods=1).mean().reset_index(0,drop=True)
    # capacity from column or default
    df['capacity'] = df['capacity'].fillna(20)
    return df
