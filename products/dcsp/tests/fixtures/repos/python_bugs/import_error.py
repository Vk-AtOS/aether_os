from config import DATABASE_URL
from utils.helpers import format_date
import pandas as pd

def load_data(filepath):
    df = pd.read_csv(filepath)
    return df
