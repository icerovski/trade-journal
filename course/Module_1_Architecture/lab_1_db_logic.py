# lab_1_db_logic.py
# -----------------------------------------------------------------------------
# GOAL: Understand how Python transforms Database Rows into fast Dictionaries.
# -----------------------------------------------------------------------------

# 1. THE DATA (Simulating what comes out of your SQLite database)
# In your app, 'cursor.fetchall()' returns a list of row objects.
mock_db_rows = [
    {'conid': '141973400', 'ticker': 'AGQ', 'atr_value': 2.5, 'stop_type': 'TRAILING'},
    {'conid': '123456789', 'ticker': 'NVDA', 'atr_value': 15.0, 'stop_type': 'FIXED'},
    {'conid': '987654321', 'ticker': 'AAPL', 'atr_value': 5.2, 'stop_type': 'TRAILING'},
]

def demonstrate_comprehension(rows):
    # This is a "Dictionary Comprehension"
    # It creates a Map for high-speed lookup.
    
    # CONCEPT: { KEY : VALUE for ITEM in LIST }
    result = { r['ticker'] : r['atr_value'] for r in rows }
    
    return result

# 2. THE EXECUTION
if __name__ == "__main__":
    print("--- RAW DB ROWS (Slow to search) ---")
    print(mock_db_rows)
    
    fast_map = demonstrate_comprehension(mock_db_rows)
    
    print("\n--- PROCESSED DICTIONARY (Instant lookup) ---")
    print(fast_map)
    
    # 3. TEST THE LOOKUP
    target = 'AGQ'
    print(f"\nLookup {target}: The ATR value is {fast_map[target]}")

# -----------------------------------------------------------------------------
# PYTHON CONCEPTS TO LEARN:
# 1. Dictionaries {}: Key-Value stores. Essential for "System Truth".
# 2. Comprehensions: A shorthand way to write loops. 
# 3. f-strings: f"Text {variable}" - the modern way to format text in Python.
# -----------------------------------------------------------------------------
