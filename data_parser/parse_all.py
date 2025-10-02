import json

import pandas as pd

from parser import parse_flight_info


df = pd.read_excel('2025.xlsx')

with open("parsed.jsonl", "w") as f:

    for i, (shr, dep, arr) in enumerate(zip(df["SHR"], df["DEP"], df["ARR"])):
        if isinstance(dep, float):
            dep = None
        if isinstance(arr, float):
            arr = None
        parsed = parse_flight_info(shr, dep, arr).to_json_dict()
        dumped = json.dumps(parsed, ensure_ascii=False)
        print(dumped, file=f)
