import streamlit as st
import requests, itertools, math
from typing import List, Tuple, Dict
from folium import Map, Marker, PolyLine
from streamlit_folium import st_folium

# -----------------------
# Config
# -----------------------
st.set_page_config(page_title="Route Optimizer", layout="wide")
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
DEFAULT_OSRM = "https://router.project-osrm.org"
USER_AGENT = "route-optimizer-app/1.0 (contact: you@example.com)"  # cámbialo por el tuyo

# -----------------------
# Helpers
# -----------------------
def geocode_search(query: str, limit: int = 6, country_code: str = "") -> List[Dict]:
    """Search places via Nominatim. Optional country filter (ISO-2)."""
    if not query:
        return []
    params = {
        "q": query,
        "format": "json",
        "limit": limit,
        "addressdetails": 1,
    }
    if country_code.strip():
        params["countrycodes"] = country_code.strip().lower()
    headers = {"User-Agent": USER_AGENT}
    r = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=20)
    r.raise_for_status()
    data = r.json()
    out = []
    for d in data:
        out.append({
            "display_name": d.get("display_name"),
            "lat": float(d.get("lat")),
            "lon": float(d.get("lon")),
        })
    return out

def osrm_table(osrm_url: str, points: List[Tuple[float, float]]):
    coords = ";".join([f"{lon},{lat}" for lat, lon in points])
    url = f"{osrm_url}/table/v1/driving/{coords}"
    params = {"annotations": "distance,duration"}
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data["distances"], data.get("durations")

def osrm_route(osrm_url: str, points: List[Tuple[float, float]]):
    coords = ";".join([f"{lon},{lat}" for lat, lon in points])
    url = f"{osrm_url}/route/v1/driving/{coords}"
    params = {"overview": "full", "geometries": "geojson", "steps": "false"}
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    routes = data.get("routes", [])
    return routes[0] if routes else None

def total_distance_duration_from_table(order: List[int], dist, dur):
    total_m = 0
    total_s = 0
    legs = []
    for a, b in zip(order[:-1], order[1:]):
        total_m += dist[a][b]
        if dur:
            total_s += dur[a][b]
        legs.append((a, b, dist[a][b], (dur[a][b] if dur else None)))
    return total_m, total_s, legs

def format_duration(seconds: float) -> str:
    m = int(round(seconds / 60.0)) if seconds is not None else 0
    h = m // 60
    mm = m % 60
    return f"{h}h {mm}m" if h > 0 else f"{m}m"

def brute_force_from_start(dist, n_dests: int, roundtrip: bool) -> List[int]:
    """
    0 = start fijo; destinos = 1..n.
    roundtrip=True: 0 -> perm(1..n) -> 0
    roundtrip=False: 0 -> perm(1..n)
    """
    mids = list(range(1, n_dests + 1))
    best, best_cost = None, math.inf
    for perm in itertools.permutations(mids):
        order = [0] + list(perm)
        if roundtrip:
            order = order + [0]
        cost, _, _ = total_distance_duration_from_table(order, dist, None)
        if cost < best_cost:
            best_cost, best = cost, order
    return best

def build_map(pts, names, order, route_geojson, legs_idx, total_km, total_time_str):
    center = (sum([p[0] for p in pts]) / len(pts), sum([p[1] for p in pts]) / len(pts))
    m = Map(location=center, zoom_start=12, control_scale=True)

    # Marcadores con secuencia
    for seq, i in enumerate(order):
        lat, lon = pts[i]
        Marker([lat, lon], popup=f"{seq}: {names[i]}").add_to(m)

    # Polilínea OSRM
    coords = route_geojson["geometry"]["coordinates"]  # [ [lon,lat], ... ]
    path = [(latlon[1], latlon[0]) for latlon in coords]
    PolyLine(path, weight=6, opacity=0.9,
             tooltip=f"Total {total_km:.2f} km · {total_time_str}").add_to(m)

    # Segmentos casi invisibles con tooltip por tramo
    for (a, b, dm, ds) in legs_idx:
        alat, alon = pts[a]; blat, blon = pts[b]
        km = dm / 1000.0
        tt = format_duration(ds) if ds else "n/a"
        PolyLine([(alat, alon), (blat, blon)], weight=3, opacity=0.0001,
                 tooltip=f"{names[a]} → {names[b]}: {km:.2f} km · {tt}").add_to(m)
    return m

# -----------------------
# State init
# -----------------------
if "start_point" not in st.session_state:
    st.session_state.start_point = None  # {"name","lat","lon"}
if "destinations" not in st.session_state:
    st.session_state.destinations = []   # list of {"name","lat","lon"}
if "search_results_start" not in st.session_state:
    st.session_state.search_results_start = []
if "search_results_dest" not in st.session_state:
    st.session_state.search_results_dest = []
if "route_result" not in st.session_state:
    st.session_state.route_result = None

# -----------------------
# UI
# -----------------------
st.title("🚚 Route Optimizer")
st.caption("Set a **Start** and up to **5 destinations**, then compute an optimized road route using OSRM.")

with st.sidebar:
    st.header("Settings")
    osrm_url = st.text_input("OSRM server URL", value=DEFAULT_OSRM)
    country_code = st.text_input("Country filter (ISO-2, optional)", value="", help="e.g., 'pe' for Peru, 'us' for USA; empty = global")
    roundtrip = st.checkbox("Round trip (end at start)", value=True)
    optimize = st.checkbox("Optimize order", value=True)

# 1) Start point
st.subheader("1) Start point")
col_s1, col_s2 = st.columns([2,1])
with col_s1:
    query_s = st.text_input("🔎 Search start (e.g., 'PUCP Lima' or 'NYC Times Square')", key="start_query")
    if st.button("Search Start", key="btn_search_start"):
        try:
            st.session_state.search_results_start = geocode_search(query_s, country_code=country_code)
            if not st.session_state.search_results_start:
                st.warning("No start results found.")
        except Exception as e:
            st.error(f"Search error: {e}")
with col_s2:
    if st.button("Clear Start", key="btn_clear_start"):
        st.session_state.start_point = None
        st.session_state.route_result = None

res_start = st.session_state.get("search_results_start", [])
if res_start:
    labels = [f"{i+1}. {r['display_name']}" for i, r in enumerate(res_start)]
    idx_s = st.selectbox("Pick start result:", options=list(range(len(res_start))),
                         format_func=lambda i: labels[i], key="sel_start")
    if st.button("✅ Set as Start", key="btn_set_start"):
        sel = res_start[idx_s]
        st.session_state.start_point = {"name": sel["display_name"], "lat": sel["lat"], "lon": sel["lon"]}
        st.session_state.route_result = None

if st.session_state.start_point:
    sp = st.session_state.start_point
    st.success(f"Start: **{sp['name']}**  \n({sp['lat']:.6f}, {sp['lon']:.6f})")

# 2) Destinations
st.subheader("2) Destinations (max 5)")
col_d1, col_d2 = st.columns([2,1])
with col_d1:
    query_d = st.text_input("🔎 Search destination (e.g., 'BCRP Lima' or 'Golden Gate Bridge')", key="dest_query")
    if st.button("Search Destination", key="btn_search_dest"):
        try:
            st.session_state.search_results_dest = geocode_search(query_d, country_code=country_code)
            if not st.session_state.search_results_dest:
                st.warning("No destination results found.")
        except Exception as e:
            st.error(f"Search error: {e}")

with col_d2:
    if st.button("Clear ALL destinations", key="btn_clear_dest_all"):
        st.session_state.destinations = []
        st.session_state.route_result = None

res_dest = st.session_state.get("search_results_dest", [])
if res_dest:
    labels_d = [f"{i+1}. {r['display_name']}" for i, r in enumerate(res_dest)]
    idx_d = st.selectbox("Pick destination to add:", options=list(range(len(res_dest))),
                         format_func=lambda i: labels_d[i], key="sel_dest")
    if st.button("➕ Add destination", key="btn_add_dest"):
        if len(st.session_state.destinations) >= 5:
            st.error("Max 5 destinations allowed.")
        else:
            sel = res_dest[idx_d]
            st.session_state.destinations.append({"name": sel["display_name"], "lat": sel["lat"], "lon": sel["lon"]})
            st.session_state.route_result = None

# List with individual delete
if len(st.session_state.destinations) == 0:
    st.info("No destinations yet. Add up to 5.")
else:
    st.write("**Selected destinations:**")
    to_delete = None
    for i, w in enumerate(st.session_state.destinations):
        c1, c2 = st.columns([8,1])
        with c1:
            st.write(f"**{i}** — {w['name']}  \n({w['lat']:.6f}, {w['lon']:.6f})")
        with c2:
            if st.button("🗑", key=f"del_{i}"):
                to_delete = i
    if to_delete is not None:
        st.session_state.destinations.pop(to_delete)
        st.session_state.route_result = None
        st.experimental_rerun()

# 3) Compute route
st.subheader("3) Compute route")
if st.button("🧭 Compute optimized route", key="btn_compute"):
    try:
        if not st.session_state.start_point:
            st.error("Set a Start point first.")
            st.stop()
        if len(st.session_state.destinations) == 0:
            st.error("Add at least one destination.")
            st.stop()

        # Build points: 0 = start, 1..n = destinations
        pts = [(st.session_state.start_point["lat"], st.session_state.start_point["lon"])]
        names = [st.session_state.start_point["name"]]
        for d in st.session_state.destinations:
            pts.append((d["lat"], d["lon"]))
            names.append(d["name"])

        dist, dur = osrm_table(osrm_url, pts)

        # Order
        if len(pts) == 2:
            order = [0, 1] + ([0] if roundtrip else [])
        else:
            if optimize:
                order = brute_force_from_start(dist, n_dests=len(pts)-1, roundtrip=roundtrip)
            else:
                order = list(range(len(pts)))
                if roundtrip:
                    order = order + [0]

        ordered_points = [pts[i] for i in order]
        route = osrm_route(osrm_url, ordered_points)
        if not route:
            st.error("OSRM did not return a route. Try other points.")
            st.stop()

        total_m, total_s, legs_idx = total_distance_duration_from_table(order, dist, dur)
        total_km = total_m / 1000.0
        total_time_str = format_duration(total_s) if total_s else "n/a"

        st.session_state.route_result = {
            "pts": pts,
            "names": names,
            "order": order,
            "route_geojson": route,
            "legs_idx": legs_idx,
            "total_km": total_km,
            "total_time_str": total_time_str,
        }
    except Exception as e:
        st.error(f"Error computing route: {e}")

# 4) Persistent render
res = st.session_state.get("route_result", None)
if res:
    st.success(f"Total distance: **{res['total_km']:.2f} km** — Total time: **{res['total_time_str']}**")
    m = build_map(res["pts"], res["names"], res["order"],
                  res["route_geojson"], res["legs_idx"], res["total_km"], res["total_time_str"])
    st_folium(m, width=1100, height=600, key="map_view")
    st.write("**Visiting order:**")
    st.write(" → ".join([f"{i}:{res['names'][i]}" for i in res["order"]]))
