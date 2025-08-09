import requests, pandas as pd

def osrm_table(osrm_url: str, points: pd.DataFrame):
    coords = ";".join([f"{row.lon},{row.lat}" for _, row in points.iterrows()])
    url = f"{osrm_url}/table/v1/driving/{coords}"
    params = {"annotations": "distance,duration"}
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data["distances"], data.get("durations")

def osrm_route(osrm_url: str, points_lonlat, overview="full"):
    coords = ";".join([f"{lon},{lat}" for lon, lat in points_lonlat])
    url = f"{osrm_url}/route/v1/driving/{coords}"
    params = {"overview": overview, "geometries": "polyline"}
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    if not data.get("routes"):
        return None
    return data["routes"][0]

def osrm_leg(osrm_url: str, a_lonlat, b_lonlat, overview="full"):
    coords = f"{a_lonlat[0]},{a_lonlat[1]};{b_lonlat[0]},{b_lonlat[1]}"
    url = f"{osrm_url}/route/v1/driving/{coords}"
    params = {"overview": overview, "geometries": "polyline"}
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    if not data.get("routes"):
        return None
    r0 = data["routes"][0]
    return {"distance": r0["distance"], "duration": r0["duration"], "geometry": r0["geometry"]}
