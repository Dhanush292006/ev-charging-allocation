import hashlib
import math
import secrets
from datetime import datetime

import pandas as pd
import requests
import streamlit as st


SEARCH_RADIUS_KM = 15
OPEN_CHARGE_MAP_URL = "https://api.openchargemap.io/v3/poi/"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_FALLBACK_URLS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
PHOTON_URL = "https://photon.komoot.io/api/"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving"
ROUTING_URLS = [
    OSRM_URL,
    "https://routing.openstreetmap.de/routed-car/route/v1/driving",
]
EV_MODELS = [
    "Ather 450X",
    "Ather 450S",
    "Ather 450 Apex",
    "Ather Rizta",
    "Bajaj Chetak",
    "Bajaj Chetak 35 Series",
    "TVS iQube",
    "TVS X",
    "Ola S1 Pro",
    "Ola S1 Air",
    "Ola S1 X",
    "Hero Vida V2",
    "Hero Vida V1",
    "Revolt RV400",
    "Simple One",
    "Oben Rorr",
    "Matter Aera",
    "Ultraviolette F77",
    "Tata Tiago EV",
    "Tata Tigor EV",
    "Tata Punch EV",
    "Tata Nexon EV",
    "Tata Curvv EV",
    "Citroen eC3",
    "Citroen eC3 Aircross",
    "Maruti Suzuki e Vitara",
    "Mahindra XUV400 EV",
    "Mahindra BE 6",
    "Mahindra XEV 9e",
    "Hyundai Kona Electric",
    "Hyundai Creta Electric",
    "Hyundai Ioniq 5",
    "Kia EV6",
    "Kia EV9",
    "MG Comet EV",
    "MG ZS EV",
    "MG Windsor EV",
    "BYD Atto 3",
    "BYD Seal",
    "BYD Sealion 7",
    "BMW i4",
    "BMW iX",
    "Mercedes-Benz EQB",
    "Volvo XC40 Recharge",
    "Volvo C40 Recharge",
    "Audi Q4 e-tron",
    "Audi e-tron GT",
    "Jaguar I-Pace",
    "Porsche Taycan",
    "Nissan Leaf",
    "Other / custom model",
]

st.set_page_config(page_title="ChargeFlow", page_icon="⚡", layout="wide")

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');
    :root { --teal: #0d7773; --teal-dark: #075754; --coral: #ef8a66; --ink: #182126; }
    html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
    h1, h2, h3 { font-family: 'Space Grotesk', sans-serif; color: var(--ink); }
    h1 { font-size: 2.3rem; margin-bottom: 0; }
    h2 { font-size: 1.7rem; }
    .eyebrow { color: #82918f; font-size: .72rem; font-weight: 700; letter-spacing: .12rem; }
    .brand { color: var(--teal-dark); font: 700 1.6rem 'Space Grotesk', sans-serif; margin-bottom: 1.5rem; }
    .brand span { color: var(--teal); }
    .metric-card { background: #f0f5f2; border: 1px solid #e4e9e8; padding: 1rem; border-radius: 6px; }
    .station-card { border: 1px solid #dce6e2; border-left: 5px solid var(--teal); padding: 1rem 1.1rem; margin: .6rem 0; border-radius: 5px; background: white; }
    .station-card strong { color: var(--teal-dark); font-size: 1.05rem; }
    .tag { color: #738087; font-size: .8rem; }
    section[data-testid="stSidebar"] { background: #f0f5f2; }
    </style>
    """,
    unsafe_allow_html=True,
)


def api_get(url, params=None):
    response = requests.get(url, params=params, timeout=20)
    response.raise_for_status()
    return response.json()


def fetch_photon_stations(latitude, longitude, search_radius_km):
    delta_latitude = search_radius_km / 111
    delta_longitude = search_radius_km / (111 * max(math.cos(math.radians(latitude)), 0.2))
    photon_data = api_get(
        PHOTON_URL,
        {
            "q": "charging_station",
            "lat": latitude,
            "lon": longitude,
            "limit": 50,
            "bbox": f"{longitude - delta_longitude},{latitude - delta_latitude},{longitude + delta_longitude},{latitude + delta_latitude}",
        },
    )
    stations = []
    for feature in photon_data.get("features", []):
        properties = feature.get("properties") or {}
        coordinates = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coordinates) != 2:
            continue
        station_lon, station_lat = coordinates
        if math.hypot(
            (station_lat - latitude) * 111,
            (station_lon - longitude) * 111 * math.cos(math.radians(latitude)),
        ) > search_radius_km:
            continue
        stations.append(
            {
                "id": f"photon-{properties.get('osm_type')}-{properties.get('osm_id')}",
                "name": properties.get("name") or "Unnamed charging station",
                "lat": station_lat,
                "lon": station_lon,
                "capacity": None,
                "type": "Charging station",
                "status": "Operational",
                "source": "OpenStreetMap via Photon",
            }
        )
    return stations


def fetch_stations(latitude, longitude, search_radius_km):
    try:
        data = api_get(
            OPEN_CHARGE_MAP_URL,
            {
                "output": "json",
                "latitude": latitude,
                "longitude": longitude,
                "distance": search_radius_km,
                "distanceunit": "KM",
                "maxresults": 50,
                "compact": "true",
            },
        )
        stations = []
        for entry in data:
            info = entry.get("AddressInfo") or {}
            connections = entry.get("Connections") or []
            status = (entry.get("StatusType") or {}).get("Title", "operational").lower()
            if any(term in status for term in ("planned", "construction", "disused", "closed", "abandoned")):
                continue
            station_lat = info.get("Latitude")
            station_lon = info.get("Longitude")
            if not station_lat or not station_lon:
                continue
            capacity = sum(connection.get("Quantity") or 0 for connection in connections) or None
            connector_types = [
                (connection.get("ConnectionType") or {}).get("Title")
                for connection in connections
            ]
            stations.append(
                {
                    "id": f"ocm-{entry.get('ID')}",
                    "name": info.get("Title") or f"Charging station #{entry.get('ID')}",
                    "lat": station_lat,
                    "lon": station_lon,
                    "capacity": capacity,
                    "type": " + ".join(value for value in connector_types if value)[:80] or "Charging station",
                    "status": status.title(),
                    "source": "Open Charge Map",
                }
            )
        if stations:
            return stations
    except requests.RequestException:
        pass

    try:
        photon_stations = fetch_photon_stations(latitude, longitude, search_radius_km)
        if photon_stations:
            return photon_stations
    except requests.RequestException:
        pass

    query = f"[out:json][timeout:20];nwr[amenity=charging_station](around:{search_radius_km * 1000},{latitude},{longitude});out center tags;"
    for overpass_url in [OVERPASS_URL, *OVERPASS_FALLBACK_URLS]:
        try:
            response = requests.post(
                overpass_url,
                data=query,
                headers={"Content-Type": "text/plain"},
                timeout=30,
            )
            response.raise_for_status()
            stations = []
            for element in response.json().get("elements", []):
                station_lat = element.get("lat") or (element.get("center") or {}).get("lat")
                station_lon = element.get("lon") or (element.get("center") or {}).get("lon")
                tags = element.get("tags") or {}
                if not station_lat or not station_lon:
                    continue
                status = tags.get("operational_status") or tags.get("lifecycle") or "operational"
                if status.lower() in {"planned", "construction", "disused", "closed", "abandoned"}:
                    continue
                raw_capacity = tags.get("capacity") or tags.get("charging:stations")
                try:
                    capacity = int(raw_capacity) if raw_capacity else None
                except (TypeError, ValueError):
                    capacity = None
                stations.append(
                    {
                        "id": f"osm-{element.get('type')}-{element.get('id')}",
                        "name": tags.get("name") or tags.get("operator") or f"Charging station #{element.get('id')}",
                        "lat": station_lat,
                        "lon": station_lon,
                        "capacity": capacity,
                        "type": "DC capable" if tags.get("socket:type2_combo") or tags.get("socket:ccs") else "Charging station",
                        "status": status.title(),
                        "source": "OpenStreetMap",
                    }
                )
            if stations:
                return stations
        except requests.RequestException:
            continue

    return []



def add_road_data(stations, latitude, longitude):
    enriched = []
    for station in stations[:12]:
        route_found = False
        for routing_url in ROUTING_URLS:
            try:
                route = api_get(
                    f"{routing_url}/{longitude},{latitude};{station['lon']},{station['lat']}?overview=false"
                )
                if route.get("code") != "Ok":
                    continue
                route_data = route["routes"][0]
                enriched.append(
                    {
                        **station,
                        "distance": route_data["distance"] / 1000,
                        "eta": max(1, round(route_data["duration"] / 60)),
                    }
                )
                route_found = True
                break
            except requests.RequestException:
                continue
        if not route_found:
            distance = math.hypot(
                (station["lat"] - latitude) * 111,
                (station["lon"] - longitude) * 111 * math.cos(math.radians(latitude)),
            )
            enriched.append({**station, "distance": distance, "eta": None, "distance_type": "Straight-line"})
    return enriched


def score_stations(stations, battery_level, arrival_window):
    if not stations:
        return []
    urgency = max(0, min(1, (55 - battery_level) / 35))
    max_distance = max(station["distance"] for station in stations) or 1
    routed_stations = [station for station in stations if station["eta"] is not None]
    max_eta = max((station["eta"] for station in routed_stations), default=1)
    ranked = []
    for station in stations:
        availability = min(station["capacity"], 10) / 10 if station["capacity"] else 0.5
        distance_score = 1 - station["distance"] / max_distance
        eta_score = 1 - station["eta"] / max_eta if station["eta"] is not None else 0
        if not routed_stations:
            score = 0.6 * availability + 0.25 * distance_score + 0.15 * urgency
        elif arrival_window == "Emergency":
            score = 0.15 * availability + 0.35 * distance_score + 0.35 * eta_score + 0.15 * urgency
        else:
            score = 0.3 * availability + 0.3 * distance_score + 0.2 * eta_score + 0.2 * urgency
        ranked.append({**station, "score": score})
    return sorted(ranked, key=lambda station: station["score"], reverse=True)


def reservation_token(vehicle_id, station_id):
    source = f"{vehicle_id}-{station_id}-{datetime.now().isoformat()}"
    digest = hashlib.sha256(source.encode()).hexdigest()[:4].upper()
    return f"CF-{''.join(character for character in vehicle_id if character.isdigit())[-4:] or '0000'}-{digest}"


with st.sidebar:
    st.markdown("<div class='brand'>⚡ charge<span>flow</span></div>", unsafe_allow_html=True)
    st.caption("WORKSPACE")
    st.write("▸ Allocation")
    st.write("▣ Stations")
    st.write("◷ Activity")
    st.divider()
    st.success("System operational")
    st.caption("Live map data · adjustable radius")

st.markdown("<div class='eyebrow'>THURSDAY, 03 SEPTEMBER 2026</div>", unsafe_allow_html=True)
st.title("Allocation command center")
st.write("Find the right charger before you need it.")

with st.container(border=True):
    st.markdown("<div class='eyebrow'>01 / VEHICLE REQUEST</div>", unsafe_allow_html=True)
    st.subheader("Tell us about the trip")
    first_row = st.columns(3)
    with first_row[0]:
        vehicle_id = st.text_input("Vehicle ID", "TN 09 EV 2471")
    with first_row[1]:
        vehicle_model = st.selectbox("Vehicle model", EV_MODELS)
    with first_row[2]:
        mobile_number = st.text_input("Mobile number", placeholder="+91 98765 43210")
    if vehicle_model == "Other / custom model":
        vehicle_model = st.text_input("Custom EV model", placeholder="Enter make and model")

    second_row = st.columns(3)
    with second_row[0]:
        battery_level = st.slider("Current battery", 5, 100, 24, format="%d%%")
    with second_row[1]:
        latitude = st.number_input("Current latitude", value=13.0827, format="%.5f", help="Default: Chennai")
    with second_row[2]:
        longitude = st.number_input("Current longitude", value=80.2707, format="%.5f", help="Default: Chennai")

    search_radius_km = st.slider("Search radius", 5, 50, SEARCH_RADIUS_KM, 5, format="%d km")

    third_row = st.columns(2)
    with third_row[0]:
        destination = st.text_input("Destination (optional)", placeholder="e.g. Chennai Airport")
    with third_row[1]:
        arrival_window = st.selectbox("Arrival window", ["ASAP", "Within 30 minutes", "Within 1 hour", "Emergency"])

    locate = st.button("Allocate best station", type="primary", use_container_width=True)

if locate:
    if len("".join(character for character in mobile_number if character.isdigit())) < 10:
        st.error("Enter a valid mobile number with at least 10 digits.")
    else:
        with st.spinner("Loading live station and route data..."):
            try:
                raw_stations = fetch_stations(latitude, longitude, search_radius_km)
                stations = add_road_data(raw_stations, latitude, longitude)
                st.session_state["ranked_stations"] = score_stations(stations, battery_level, arrival_window)
                st.session_state["location"] = (latitude, longitude)
                st.session_state["vehicle_id"] = vehicle_id
                st.session_state["mobile_number"] = mobile_number
                st.session_state["vehicle_model"] = vehicle_model
            except requests.RequestException as error:
                st.error(f"Live map data is unavailable right now: {error}")

ranked_stations = st.session_state.get("ranked_stations", [])
st.markdown("<div class='eyebrow'>02 / NETWORK PULSE</div>", unsafe_allow_html=True)
summary = st.columns(3)
summary[0].metric("Stations found", len(ranked_stations))
summary[1].metric("With charger data", sum(bool(station["capacity"]) for station in ranked_stations))
summary[2].metric("Search radius", f"{search_radius_km} km")

st.markdown("<div class='eyebrow'>03 / RECOMMENDED ALLOCATION</div>", unsafe_allow_html=True)
st.header("Stations near your route")
st.caption("Ranked by charger availability, distance, travel time, and battery urgency. If road routing is unavailable, distance means straight-line distance and ETA is omitted.")
if not ranked_stations:
    if "ranked_stations" in st.session_state:
        st.warning("No verified live station routes are available right now. Try again later when the map services respond.")
    else:
        st.info("Enter the trip details and select Allocate best station to load live recommendations.")
else:
    for index, station in enumerate(ranked_stations):
        label = " · BEST MATCH" if index == 0 else ""
        st.markdown(
            f"""<div class='station-card'><strong>{station['name']}{label}</strong><br>
            <span class='tag'>{station['type']} · {station['status']} · {station['source']}</span></div>""",
            unsafe_allow_html=True,
        )
        details = st.columns(5)
        distance_label = f"{station.get('distance_type', 'Road')} distance"
        details[0].metric(distance_label, f"{station['distance']:.1f} km")
        details[1].metric("Capacity", f"{station['capacity']} connectors" if station["capacity"] else "Not listed")
        details[2].metric("Travel time", f"{station['eta']} min" if station["eta"] is not None else "Unavailable")
        details[3].metric("Score", f"{station['score'] * 100:.1f}")
        if details[4].button("Reserve this" if index == 0 else "Reserve", key=f"reserve-{station['id']}"):
            token = reservation_token(st.session_state["vehicle_id"], station["id"])
            otp = f"{secrets.randbelow(900000) + 100000}"
            st.session_state["reservation"] = {"station": station, "token": token, "otp": otp}

reservation = st.session_state.get("reservation")
if reservation:
    station = reservation["station"]
    st.success(f"{station['name']} reserved. Connector held for {st.session_state['vehicle_id']}.")
    ticket = pd.DataFrame(
        [{
            "Reservation token": reservation["token"],
            "One-time code": reservation["otp"],
            "Arrive by": f"{station['eta']} min from now" if station["eta"] is not None else "Road ETA unavailable",
            "Mobile delivery": st.session_state["mobile_number"],
        }]
    )
    st.dataframe(ticket, hide_index=True, use_container_width=True)
    directions = f"https://www.google.com/maps/dir/?api=1&destination={station['lat']},{station['lon']}&travelmode=driving"
    st.link_button("Start navigation", directions, use_container_width=True)
