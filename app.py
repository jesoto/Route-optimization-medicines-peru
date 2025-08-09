import streamlit as st
import folium
from streamlit_folium import st_folium
import requests

st.set_page_config(page_title="Optimized Route - LATAM/US/CA", layout="wide")
DEFAULT_OSRM = "https://router.project-osrm.org"

# ============ Utils ============
def safe_get(addr, keys, default=""):
    for k in keys:
        v = addr.get(k)
        if v:
            return v
    return default

def format_address_detail(item):
    addr = item.get("address", {}) or {}
    line1 = item.get("display_name", "")
    city = safe_get(addr, ["city", "town", "village", "suburb", "county"])
    state = safe_get(addr, ["state", "region", "province", "state_district"])
    country = addr.get("country", "")
    postcode = addr.get("postcode", "")
    parts = []
    if city: parts.append(f"City/District: {city}")
    if state: parts.append(f"State/Province: {state}")
    if country: parts.append(f"Country: {country}")
    if postcode: parts.append(f"Postcode: {postcode}")
    detail = " · ".join(parts) if parts else ""
    return line1, detail

def minutes_fmt(seconds):
    m = round((seconds or 0) / 60.0)
    h, mm = divmod(m, 60)
    return f"{h}h {mm}m" if h else f"{mm}m"

# ============ Geocoding ============
def search_place(query, country_code=""):
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": query, "format": "json", "addressdetails": 1, "limit": 7}
    if country_code:
        params["countrycodes"] = country_code
    headers = {"User-Agent": "streamlit-route-optimizer/1.0"}
    r = requests.get(url, params=params, headers=headers, timeout=25)
    r.raise_for_status()
    data = r.json()
    out = []
    for d in data:
        out.append({
            "display_name": d.get("display_name", ""),
            "lat": float(d.get("lat")),
            "lon": float(d.get("lon")),
            "address": d.get("address", {}),
        })
    return out

# ============ OSRM Trip ============
def get_trip(points, osrm_url=DEFAULT_OSRM, roundtrip=True):
    coords = ";".join([f"{lon},{lat}" for lat, lon in points])
    url = f"{osrm_url}/trip/v1/driving/{coords}"
    params = {
        "roundtrip": str(roundtrip).lower(),
        "source": "first",
        "destination": "last" if not roundtrip else "any",
        "overview": "full",
        "geometries": "geojson",
        "steps": "false",
    }
    r = requests.get(url, params=params, timeout=35)
    r.raise_for_status()
    data = r.json()
    trips = data.get("trips") or []
    return trips[0] if trips else None

def geometry_bounds(geojson):
    """Return [[min_lat, min_lon], [max_lat, max_lon]] for fit bounds."""
    coords = geojson.get("coordinates") or []
    lats, lons = [], []
    for lon, lat in coords:
        lats.append(lat); lons.append(lon)
    if not lats or not lons:
        return None
    return [[min(lats), min(lons)], [max(lats), max(lons)]]

# ============ Sidebar ============
with st.sidebar:
    st.header("Settings")
    osrm_url = st.text_input("OSRM server URL", value=DEFAULT_OSRM)

    country_map = {
        "🌎 No filter (Global)": "",
        "🇦🇷 Argentina": "ar", "🇧🇴 Bolivia": "bo", "🇧🇷 Brazil": "br",
        "🇨🇱 Chile": "cl", "🇨🇴 Colombia": "co", "🇨🇷 Costa Rica": "cr",
        "🇨🇺 Cuba": "cu", "🇪🇨 Ecuador": "ec", "🇸🇻 El Salvador": "sv",
        "🇬🇹 Guatemala": "gt", "🇭🇳 Honduras": "hn", "🇲🇽 Mexico": "mx",
        "🇳🇮 Nicaragua": "ni", "🇵🇦 Panama": "pa", "🇵🇾 Paraguay": "py",
        "🇵🇪 Peru": "pe", "🇵🇷 Puerto Rico": "pr", "🇺🇾 Uruguay": "uy",
        "🇻🇪 Venezuela": "ve",
        "🇺🇸 United States": "us", "🇨🇦 Canada": "ca",
    }
    options = list(country_map.keys())
    default_idx = options.index("🇵🇪 Peru") if "🇵🇪 Peru" in options else 0
    country_label = st.selectbox("🌍 Country filter for search", options, index=default_idx)
    country_code = country_map[country_label]

    roundtrip = st.checkbox("Round trip (end at start)", value=True)

# ============ State ============
if "start_point" not in st.session_state:
    st.session_state.start_point = None       # (lat, lon)
if "start_name" not in st.session_state:
    st.session_state.start_name = None
if "destinations" not in st.session_state:
    st.session_state.destinations = []        # list of dict: {lat,lon,name}
if "trip_result" not in st.session_state:
    st.session_state.trip_result = None
if "fit_all" not in st.session_state:
    st.session_state.fit_all = False

st.title("🚚 Optimized Route — LATAM / US / CA")

# ============ 1) Start ============
st.subheader("1️⃣ Start point")
col_s1, col_s2 = st.columns([2,1])
with col_s1:
    start_query = st.text_input("Search start (e.g., 'PUCP Lima' or '1600 Amphitheatre Pkwy, CA')")
    if st.button("🔎 Search start"):
        try:
            start_results = search_place(start_query, country_code)
            if not start_results:
                st.warning("No results for start.")
            else:
                st.session_state.start_search = start_results
        except Exception as e:
            st.error(f"Search error: {e}")

with col_s2:
    if st.button("🗑 Clear start"):
        st.session_state.start_point = None
        st.session_state.start_name = None
        st.session_state.trip_result = None

# Start selector + detail
start_results = st.session_state.get("start_search", [])
if start_results:
    idx = st.selectbox("Pick a start result:", list(range(len(start_results))),
                       format_func=lambda i: start_results[i]["display_name"])
    line1, detail = format_address_detail(start_results[idx])
    st.caption(f"**Confirmation:**\n\n{line1}\n\n{detail}")
    if st.button("✅ Use this start"):
        sel = start_results[idx]
        st.session_state.start_point = (sel["lat"], sel["lon"])
        st.session_state.start_name = sel["display_name"]
        st.session_state.trip_result = None
        st.success("Start set.")

if st.session_state.start_point:
    st.info(f"Start: **{st.session_state.start_name}**\n\n({st.session_state.start_point[0]:.6f}, {st.session_state.start_point[1]:.6f})")

# ============ 2) Destinations ============
st.subheader("2️⃣ Destinations (max 5)")
col_d1, col_d2, col_d3 = st.columns([2,1,1])
with col_d1:
    dest_query = st.text_input("Search destination (e.g., 'BCRP Lima' or 'Golden Gate Bridge')")
with col_d2:
    if st.button("🔎 Search destination"):
        try:
            dest_results = search_place(dest_query, country_code)
            if not dest_results:
                st.warning("No results for destination.")
            else:
                st.session_state.dest_search = dest_results
        except Exception as e:
            st.error(f"Search error: {e}")
with col_d3:
    if st.button("🧹 Clear ALL destinations"):
        st.session_state.destinations = []
        st.session_state.trip_result = None

# Destination selector + detail + add
dest_results = st.session_state.get("dest_search", [])
if dest_results:
    didx = st.selectbox("Pick a destination:", list(range(len(dest_results))),
                        format_func=lambda i: dest_results[i]["display_name"])
    dline1, ddetail = format_address_detail(dest_results[didx])
    st.caption(f"**Confirmation:**\n\n{dline1}\n\n{ddetail}")
    if st.button("➕ Add destination"):
        if len(st.session_state.destinations) >= 5:
            st.warning("Maximum 5 destinations.")
        else:
            sel = dest_results[didx]
            st.session_state.destinations.append({
                "lat": sel["lat"], "lon": sel["lon"], "name": sel["display_name"]
            })
            st.session_state.trip_result = None
            st.success("Destination added.")

# Show list with individual delete
if st.session_state.destinations:
    st.write("📍 **Current destinations:**")
    del_idx = None
    for i, d in enumerate(st.session_state.destinations):
        c1, c2 = st.columns([8,1])
        with c1:
            st.write(f"**{i+1}.** {d['name']}  \n({d['lat']:.6f}, {d['lon']:.6f})")
        with c2:
            if st.button("🗑", key=f"del_{i}"):
                del_idx = i
    if del_idx is not None:
        st.session_state.destinations.pop(del_idx)
        st.session_state.trip_result = None
        st.experimental_rerun()
else:
    st.info("Add 1 to 5 destinations.")

# ============ 3) Compute ============
st.subheader("3️⃣ Compute optimized route")
if st.button("🚀 Compute route"):
    if not st.session_state.start_point:
        st.error("Please set a start point first.")
    elif not st.session_state.destinations:
        st.error("Please add at least one destination.")
    else:
        try:
            points = [st.session_state.start_point] + [(d["lat"], d["lon"]) for d in st.session_state.destinations]
            trip = get_trip(points, osrm_url=osrm_url, roundtrip=roundtrip)
            if not trip:
                st.error("OSRM could not compute a route. Try different points.")
            else:
                st.session_state.trip_result = {
                    "trip": trip,
                    "names": [st.session_state.start_name] + [d["name"] for d in st.session_state.destinations]
                }
                st.session_state.fit_all = False  # default: center on start
                st.success("Route ready ✅")
        except Exception as e:
            st.error(f"Route error: {e}")

# ============ 4) Map + segments ============
if st.session_state.trip_result:
    trip = st.session_state.trip_result["trip"]
    names_input = st.session_state.trip_result["names"]

    total_km = (trip.get("distance") or 0) / 1000.0
    total_min = minutes_fmt(trip.get("duration") or 0)
    st.info(f"**Total:** {total_km:.2f} km · {total_min}")

    # Fit-to-route button
    col_fit1, col_fit2 = st.columns([1,3])
    with col_fit1:
        if st.button("🔍 Fit to full route"):
            st.session_state.fit_all = True
    with col_fit2:
        st.caption("Map starts centered on the start point. Use the button to fit the whole route.")

    # Always center on start (as requested)
    start_lat, start_lon = st.session_state.start_point
    m = folium.Map(location=[start_lat, start_lon], zoom_start=14, control_scale=True)

    # Main route layer
    gj = folium.GeoJson(trip["geometry"], name="Route")
    gj.add_to(m)

    # Fit bounds if requested
    if st.session_state.fit_all:
        bounds = geometry_bounds(trip["geometry"])
        if bounds:
            m.fit_bounds(bounds)

    # Waypoints and names (waypoint_index -> original input order)
    wp = trip.get("waypoints") or []
    for i, w in enumerate(wp):
        idx_in = (w.get("waypoint_index") or 0)
        name = names_input[idx_in] if 0 <= idx_in < len(names_input) else (w.get("name") or f"Point {i+1}")
        folium.Marker(
            location=[w["location"][1], w["location"][0]],
            popup=f"{i+1}. {name}",
            icon=folium.Icon(color="red" if i > 0 else "blue", icon="flag" if i > 0 else "play")
        ).add_to(m)

    # Per-leg tooltips (A→B)
    legs = trip.get("legs") or []
    for i, leg in enumerate(legs):
        if i + 1 >= len(wp):
            continue
        a, b = wp[i], wp[i+1]
        ai = (a.get("waypoint_index") or 0); bi = (b.get("waypoint_index") or 0)
        an = names_input[ai] if 0 <= ai < len(names_input) else (a.get("name") or f"A{i+1}")
        bn = names_input[bi] if 0 <= bi < len(names_input) else (b.get("name") or f"B{i+2}")
        km = (leg.get("distance") or 0) / 1000.0
        mins = minutes_fmt(leg.get("duration") or 0)
        folium.PolyLine(
            [[a["location"][1], a["location"][0]], [b["location"][1], b["location"][0]]],
            weight=6, opacity=0.0001, tooltip=f"{an} → {bn}: {km:.2f} km · {mins}"
        ).add_to(m)

    st_folium(m, width=1000, height=600)
