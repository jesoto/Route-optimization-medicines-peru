import streamlit as st
import folium
from streamlit_folium import st_folium
import requests

st.set_page_config(page_title="Ruta Optimizada - Latinoamérica", layout="wide")

DEFAULT_OSRM = "https://router.project-osrm.org"

# ========= Geocoding (Nominatim) =========
def search_place(query, country_code=""):
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": query, "format": "json", "addressdetails": 1, "limit": 5}
    if country_code:
        params["countrycodes"] = country_code
    headers = {"User-Agent": "streamlit-route-optimizer"}
    r = requests.get(url, params=params, headers=headers, timeout=25)
    r.raise_for_status()
    return r.json()

# ========= OSRM Trip (optimiza orden) =========
def get_trip(points, osrm_url=DEFAULT_OSRM, roundtrip=True):
    """
    points: [(lat, lon), ...]  -> Trip optimiza el orden.
    Retorna dict con: geometry, distance, duration, waypoints, legs
    """
    coords = ";".join([f"{lon},{lat}" for lat, lon in points])
    url = f"{osrm_url}/trip/v1/driving/{coords}"
    params = {
        "roundtrip": str(roundtrip).lower(),
        "source":   "first",                  # start fijo en el primero
        "destination": "last" if not roundtrip else "any",
        "overview": "full",
        "geometries": "geojson",
        "steps": "false"                      # no necesitamos pasos, solo legs
        # (OSRM devuelve distance/duration por leg igualmente)
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("trips"):
        return data["trips"][0]  # {geometry, distance, duration, legs[], waypoints[]}
    return None

# ========= Sidebar =========
with st.sidebar:
    st.header("Settings")
    osrm_url = st.text_input("OSRM server URL", value=DEFAULT_OSRM)

    country_map = {
        "🌎 Sin filtro (Global)": "",
        "🇦🇷 Argentina": "ar", "🇧🇴 Bolivia": "bo", "🇧🇷 Brasil": "br",
        "🇨🇱 Chile": "cl", "🇨🇴 Colombia": "co", "🇨🇷 Costa Rica": "cr",
        "🇨🇺 Cuba": "cu", "🇪🇨 Ecuador": "ec", "🇸🇻 El Salvador": "sv",
        "🇬🇹 Guatemala": "gt", "🇭🇳 Honduras": "hn", "🇲🇽 México": "mx",
        "🇳🇮 Nicaragua": "ni", "🇵🇦 Panamá": "pa", "🇵🇾 Paraguay": "py",
        "🇵🇪 Perú": "pe", "🇵🇷 Puerto Rico": "pr", "🇺🇾 Uruguay": "uy",
        "🇻🇪 Venezuela": "ve",
    }
    country_label = st.selectbox("🌍 País para filtrar búsqueda", list(country_map.keys()), index=16)
    country_code = country_map[country_label]

    roundtrip = st.checkbox("Round trip (end at start)", value=True)

# ========= Estado =========
if "start_point" not in st.session_state:
    st.session_state.start_point = None               # (lat, lon, name)
if "destinations" not in st.session_state:
    st.session_state.destinations = []                # [(lat, lon, name)]
if "trip_result" not in st.session_state:
    st.session_state.trip_result = None               # cache resultado

# ========= 1) Punto de inicio =========
st.subheader("1️⃣ Punto de inicio")
start_q = st.text_input("Buscar inicio")
if st.button("🔍 Buscar inicio"):
    try:
        res = search_place(start_q, country_code)
        if not res:
            st.warning("Sin resultados.")
        else:
            for i, r in enumerate(res):
                lbl = r["display_name"]
                if st.button(f"✅ Usar este inicio ({i+1})"):
                    st.session_state.start_point = (float(r["lat"]), float(r["lon"]), lbl)
                    st.session_state.trip_result = None
                    st.success(f"Inicio: {lbl}")
    except Exception as e:
        st.error(f"Error de búsqueda: {e}")

if st.session_state.start_point:
    lat, lon, nm = st.session_state.start_point
    st.info(f"Inicio seleccionado: **{nm}**  \n({lat:.6f}, {lon:.6f})")

# ========= 2) Destinos =========
st.subheader("2️⃣ Destinos (máx. 5)")
dest_q = st.text_input("Buscar destino")
col_add, col_clear = st.columns([1,1])
with col_add:
    if st.button("🔍 Buscar destino"):
        try:
            res = search_place(dest_q, country_code)
            if not res:
                st.warning("Sin resultados.")
            else:
                for i, r in enumerate(res):
                    lbl = r["display_name"]
                    if st.button(f"➕ Agregar destino ({i+1})", key=f"add_{i}"):
                        if len(st.session_state.destinations) < 5:
                            st.session_state.destinations.append((float(r["lat"]), float(r["lon"]), lbl))
                            st.session_state.trip_result = None
                            st.success(f"Añadido: {lbl}")
                        else:
                            st.warning("Máximo 5 destinos.")
        except Exception as e:
            st.error(f"Error de búsqueda: {e}")
with col_clear:
    if st.button("🧹 Limpiar TODOS los destinos"):
        st.session_state.destinations = []
        st.session_state.trip_result = None

# Mostrar lista con eliminación individual
if st.session_state.destinations:
    st.write("📍 Destinos seleccionados:")
    del_idx = None
    for i, (lat, lon, name) in enumerate(st.session_state.destinations):
        c1, c2 = st.columns([8,1])
        with c1:
            st.write(f"**{i+1}.** {name}")
        with c2:
            if st.button("❌", key=f"del_{i}"):
                del_idx = i
    if del_idx is not None:
        st.session_state.destinations.pop(del_idx)
        st.session_state.trip_result = None
        st.experimental_rerun()
else:
    st.info("Agrega de 1 a 5 destinos.")

# ========= 3) Calcular ruta =========
st.subheader("3️⃣ Calcular ruta optimizada")
if st.button("🚀 Calcular ruta"):
    if not st.session_state.start_point:
        st.error("Primero selecciona un inicio.")
    elif not st.session_state.destinations:
        st.error("Agrega al menos un destino.")
    else:
        try:
            # Puntos en el orden de entrada: 0 = start, luego destinos
            start_lat, start_lon, start_name = st.session_state.start_point
            points = [(start_lat, start_lon)] + [(d[0], d[1]) for d in st.session_state.destinations]
            names_by_input = [start_name] + [d[2] for d in st.session_state.destinations]

            trip = get_trip(points, osrm_url=osrm_url, roundtrip=roundtrip)
            if not trip:
                st.error("OSRM no pudo calcular la ruta. Intenta con otros puntos.")
            else:
                st.session_state.trip_result = {"trip": trip, "names_by_input": names_by_input}
                st.success("Ruta optimizada lista ✅")
        except Exception as e:
            st.error(f"Error calculando la ruta: {e}")

# ========= 4) Mostrar mapa + tramos =========
if st.session_state.trip_result:
    trip = st.session_state.trip_result["trip"]
    names_by_input = st.session_state.trip_result["names_by_input"]

    # Totales
    total_km = trip["distance"] / 1000.0
    total_min = trip["duration"] / 60.0
    st.info(f"**Total:** {total_km:.2f} km · {total_min:.1f} min")

    # Mapa
    center = [trip["waypoints"][0]["location"][1], trip["waypoints"][0]["location"][0]]
    m = folium.Map(location=center, zoom_start=12, control_scale=True)

    # Ruta principal
    folium.GeoJson(trip["geometry"], name="Ruta").add_to(m)

    # Marcadores + nombres
    # OSRM Trip devuelve: waypoints[i]["waypoint_index"] => índice del punto original
    wp = trip["waypoints"]
    for i, w in enumerate(wp):
        idx_in = w.get("waypoint_index", 0) or 0
        name = names_by_input[idx_in] if 0 <= idx_in < len(names_by_input) else (w.get("name") or f"Point {i+1}")
        folium.Marker(
            location=[w["location"][1], w["location"][0]],
            popup=f"{i+1}. {name}",
            icon=folium.Icon(color="red" if i > 0 else "blue", icon="flag" if i > 0 else "play")
        ).add_to(m)

    # Tooltips por tramo (A→B) usando legs
    # Cada leg tiene distance/duration; los extremos vienen de waypoints consecutivos
    legs = trip.get("legs", [])
    for i, leg in enumerate(legs):
        if i + 1 >= len(wp):
            continue
        a = wp[i]
        b = wp[i + 1]
        a_idx = a.get("waypoint_index", 0) or 0
        b_idx = b.get("waypoint_index", 0) or 0
        a_name = names_by_input[a_idx] if 0 <= a_idx < len(names_by_input) else (a.get("name") or f"Point {i+1}")
        b_name = names_by_input[b_idx] if 0 <= b_idx < len(names_by_input) else (b.get("name") or f"Point {i+2}")

        km = (leg.get("distance", 0.0) or 0.0) / 1000.0
        mins = (leg.get("duration", 0.0) or 0.0) / 60.0

        # línea “hoverable” entre A y B (no necesitamos geometría detallada para el tooltip)
        folium.PolyLine(
            locations=[[a["location"][1], a["location"][0]], [b["location"][1], b["location"][0]]],
            weight=6, opacity=0.0001,  # casi invisible, pero permite hover
            tooltip=f"{a_name} → {b_name}: {km:.2f} km · {mins:.1f} min"
        ).add_to(m)

    st_folium(m, width=1000, height=600)
