"""Generate a realistic test manifest XLSX for the ingestion pipeline."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

# 25 rows of realistic liquidation inventory data
# Mix of: exact ASIN matches, UPC matches, fuzzy title matches, and unmatched items
rows = [
    # Exact ASIN matches (match canonical products we'll seed)
    {"ASIN": "B08N5WRWNW", "Item Description": "Instant Pot Duo 7-in-1 6Qt", "Qty": 5, "Unit Cost": 22.50, "Condition": "New", "Retail Price": 89.99, "Brand": "Instant Pot", "Category": "Kitchen"},
    {"ASIN": "B07S85TPLG", "Item Description": "Ninja Professional Blender 72oz", "Qty": 3, "Unit Cost": 17.50, "Condition": "Open Box", "Retail Price": 69.99, "Brand": "Ninja", "Category": "Kitchen"},
    {"ASIN": "B09KZ26N23", "Item Description": "KitchenAid Hand Mixer 5-Speed", "Qty": 4, "Unit Cost": 13.75, "Condition": "Like New", "Retail Price": 54.99, "Brand": "KitchenAid", "Category": "Kitchen"},
    {"ASIN": "B0BDHX9JPC", "Item Description": "Apple AirPods Pro 2nd Gen", "Qty": 8, "Unit Cost": 62.00, "Condition": "New in Box", "Retail Price": 249.99, "Brand": "Apple", "Category": "Electronics"},
    {"ASIN": "B09V3KXJPB", "Item Description": "JBL Flip 6 Portable Speaker", "Qty": 6, "Unit Cost": 32.00, "Condition": "Refurbished", "Retail Price": 129.99, "Brand": "JBL", "Category": "Electronics"},
    {"ASIN": "B0BT9CXXXX", "Item Description": "Anker PowerCore 20000mAh", "Qty": 10, "Unit Cost": 12.00, "Condition": "Brand New", "Retail Price": 49.99, "Brand": "Anker", "Category": "Electronics"},
    # UPC matches
    {"UPC": "190199882744", "Item Description": "Apple Watch SE 40mm GPS", "Qty": 3, "Unit Cost": 85.00, "Condition": "Open Box", "Retail Price": 249.00, "Brand": "Apple Inc.", "Category": "Electronics"},
    {"UPC": "889842640977", "Item Description": "Xbox Wireless Controller", "Qty": 7, "Unit Cost": 18.00, "Condition": "New", "Retail Price": 59.99, "Brand": "Microsoft", "Category": "Gaming"},
    {"UPC": "097855157430", "Item Description": "Lodge Cast Iron Skillet 12in", "Qty": 4, "Unit Cost": 9.50, "Condition": "Gently Used", "Retail Price": 39.99, "Brand": "Lodge", "Category": "Kitchen"},
    # Fuzzy title matches (close but not exact)
    {"ASIN": "", "Item Description": "Instant Pot Duo 7in1 Electric Pressure Cooker 6 Quart", "Qty": 2, "Unit Cost": 24.00, "Condition": "Sealed", "Retail Price": 89.99, "Brand": "Instant Pot", "Category": "Kitchen"},
    {"ASIN": "", "Item Description": "Ninja Pro Blender 72 oz Pitcher", "Qty": 1, "Unit Cost": 15.00, "Condition": "Used - Good", "Retail Price": 69.99, "Brand": "Ninja", "Category": "Kitchen"},
    {"ASIN": "", "Item Description": "KitchenAid 5 Speed Hand Mixer White", "Qty": 3, "Unit Cost": 12.00, "Condition": "Good", "Retail Price": 54.99, "Brand": "KitchenAid Corp", "Category": "Kitchen"},
    {"ASIN": "", "Item Description": "JBL Flip6 Bluetooth Speaker Black", "Qty": 2, "Unit Cost": 28.00, "Condition": "Tested Working", "Retail Price": 129.99, "Brand": "JBL", "Category": "Electronics"},
    # More variety
    {"ASIN": "B08PZHYWJS", "Item Description": "Keurig K-Mini Single Serve", "Qty": 4, "Unit Cost": 20.00, "Condition": "New", "Retail Price": 79.99, "Brand": "Keurig", "Category": "Kitchen"},
    {"ASIN": "B09JQM8K1N", "Item Description": "Sony WH-1000XM5 Headphones", "Qty": 2, "Unit Cost": 88.00, "Condition": "Open Box", "Retail Price": 349.99, "Brand": "Sony", "Category": "Electronics"},
    {"ASIN": "B0B3PSRHHN", "Item Description": "Dyson V8 Origin Cordless Vacuum", "Qty": 1, "Unit Cost": 95.00, "Condition": "Refurbished", "Retail Price": 349.99, "Brand": "Dyson", "Category": "Home"},
    {"UPC": "841058102298", "Item Description": "Hydro Flask 32oz Wide Mouth", "Qty": 12, "Unit Cost": 8.50, "Condition": "New", "Retail Price": 44.95, "Brand": "Hydro Flask", "Category": "Outdoors"},
    {"ASIN": "B084DDDNRP", "Item Description": "Ring Video Doorbell Wired", "Qty": 3, "Unit Cost": 18.00, "Condition": "Open Box", "Retail Price": 64.99, "Brand": "Ring", "Category": "Smart Home"},
    {"ASIN": "", "Item Description": "Amazon Echo Dot 5th Gen", "Qty": 6, "Unit Cost": 11.00, "Condition": "Factory Sealed", "Retail Price": 49.99, "Brand": "Amazon", "Category": "Smart Home"},
    {"ASIN": "B0CFDJQ2QQ", "Item Description": "Stanley Quencher 40oz Tumbler", "Qty": 15, "Unit Cost": 10.50, "Condition": "New", "Retail Price": 45.00, "Brand": "Stanley", "Category": "Outdoors"},
    # Some items with condition edge cases
    {"UPC": "072785138681", "Item Description": "Crayola 96 Count Crayons", "Qty": 20, "Unit Cost": 1.25, "Condition": "Damaged", "Retail Price": 5.99, "Brand": "Crayola", "Category": "Toys"},
    {"ASIN": "", "Item Description": "Misc kitchen utensil set 12pc", "Qty": 8, "Unit Cost": 3.50, "Condition": "As-Is", "Retail Price": 19.99, "Brand": "", "Category": "Kitchen"},
    {"ASIN": "B09HGV7TPF", "Item Description": "Beats Studio Buds True Wireless", "Qty": 4, "Unit Cost": 35.00, "Condition": "Acceptable", "Retail Price": 149.99, "Brand": "Beats", "Category": "Electronics"},
    {"ASIN": "", "Item Description": "Philips Sonicare 4100 Toothbrush", "Qty": 5, "Unit Cost": 12.00, "Condition": "New in Box", "Retail Price": 49.99, "Brand": "Philips", "Category": "Health"},
    {"UPC": "810028587878", "Item Description": "Owala FreeSip 24oz Water Bottle", "Qty": 10, "Unit Cost": 6.00, "Condition": "Brand New", "Retail Price": 27.99, "Brand": "Owala", "Category": "Outdoors"},
]

df = pd.DataFrame(rows)
output = os.path.join(os.path.dirname(__file__), "test_manifest.xlsx")
df.to_excel(output, index=False, engine="openpyxl")
print(f"Created {output} with {len(rows)} rows")
