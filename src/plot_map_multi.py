import folium, pandas as pd, polyline

def _color(i:int):
    palette = ["blue","red","green","purple","orange","darkred","lightred","beige","darkblue","darkgreen","cadetblue","darkpurple","gray","black","lightgray"]
    return palette[i % len(palette)]

def plot_multi(points_csv: str, routes: list[dict], legs_by_vehicle: dict, out_html: str = "outputs/mapa.html"):
    df = pd.read_csv(points_csv).reset_index(drop=True)
    m = folium.Map(location=[df.lat.mean(), df.lon.mean()], zoom_start=8, control_scale=True)

    for i, row in df.iterrows():
        folium.Marker([row.lat, row.lon], popup=f"{row['id']}: {row['name']}").add_to(m)

    for r in routes:
        v = r["vehicle"]
        color = _color(v)
        legs = legs_by_vehicle.get(v, [])
        total_km = 0.0
        for leg in legs:
            km = leg["meters"] / 1000.0
            total_km += km
            geom = leg.get("geometry")
            a_name, b_name = leg["from_name"], leg["to_name"]
            if geom:
                coords = polyline.decode(geom)
                folium.PolyLine(coords, weight=5, opacity=0.85, color=color,
                                tooltip=f"V{v}: {a_name} → {b_name} | {km:.2f} km").add_to(m)
        if legs:
            mid = legs[len(legs)//2]
            folium.Marker(
                [df.loc[df['id']==mid['to_id'], 'lat'].iloc[0],
                 df.loc[df['id']==mid['to_id'], 'lon'].iloc[0]],
                popup=f"Veh {v} — Total: {total_km:.2f} km"
            ).add_to(m)

    m.save(out_html)
    return out_html
