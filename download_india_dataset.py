import csv
import json
import urllib.request


OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OUTPUT_FILE = "charging_stations_india.csv"
QUERY = """
[out:json][timeout:180];
area["ISO3166-1"="IN"][admin_level=2]->.india;
nwr[amenity=charging_station](area.india);
out center tags;
"""


def main():
    request = urllib.request.Request(
        OVERPASS_URL,
        data=QUERY.encode(),
        headers={
            "Content-Type": "text/plain",
            "User-Agent": "ChargeFlow EV Allocation/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=210) as response:
        data = json.load(response)

    fields = [
        "id",
        "name",
        "latitude",
        "longitude",
        "capacity",
        "connector_types",
        "status",
        "source",
    ]
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for element in data.get("elements", []):
            tags = element.get("tags") or {}
            center = element.get("center") or {}
            latitude = element.get("lat") or center.get("lat")
            longitude = element.get("lon") or center.get("lon")
            if not latitude or not longitude:
                continue
            writer.writerow(
                {
                    "id": f"osm-{element.get('type')}-{element.get('id')}",
                    "name": tags.get("name")
                    or tags.get("operator")
                    or f"Charging station #{element.get('id')}",
                    "latitude": latitude,
                    "longitude": longitude,
                    "capacity": tags.get("capacity")
                    or tags.get("charging:stations")
                    or "",
                    "connector_types": "DC capable"
                    if tags.get("socket:type2_combo") or tags.get("socket:ccs")
                    else "Charging station",
                    "status": tags.get("operational_status")
                    or tags.get("lifecycle")
                    or "operational",
                    "source": "OpenStreetMap",
                }
            )

    print(f"Wrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()