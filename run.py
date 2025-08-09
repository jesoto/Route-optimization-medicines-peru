import os, argparse, pandas as pd
from src.solve_vrp_osrm_apu import solve_vrp
from src.osrm import osrm_leg
from src.plot_map_multi import plot_multi

def main(centros_csv, demandas_csv, vehiculos_csv, osrm_url):
    os.makedirs("outputs", exist_ok=True)
    centros   = pd.read_csv(centros_csv)
    demandas  = pd.read_csv(demandas_csv)
    vehiculos = pd.read_csv(vehiculos_csv)

    routes, manager, points = solve_vrp(centros, demandas, vehiculos, osrm_url)
    if routes is None:
        print("No se encontró solución.")
        return

    out_plan = []
    for r in routes:
        v = r["vehicle"]; order = r["order"]
        for seq, node in enumerate(order):
            out_plan.append({"vehicle": v, "seq": seq, "node_index": node, "id": points.iloc[node]["id"], "name": points.iloc[node]["name"]})
    pd.DataFrame(out_plan).to_csv("outputs/plan_entregas.csv", index=False)

    legs_by_vehicle = {}
    for r in routes:
        v = r["vehicle"]; order = r["order"]
        legs = []
        for a, b in zip(order[:-1], order[1:]):
            a_row = points.iloc[a]; b_row = points.iloc[b]
            # llamar OSRM por tramo para distancia real y geometría
            leg = osrm_leg(osrm_url, (a_row.lon, a_row.lat), (b_row.lon, b_row.lat), overview="full")
            if leg:
                legs.append({
                    "from": a, "to": b,
                    "from_id": a_row["id"], "to_id": b_row["id"],
                    "from_name": a_row["name"], "to_name": b_row["name"],
                    "meters": leg["distance"], "seconds": leg["duration"],
                    "geometry": leg["geometry"]
                })
        legs_by_vehicle[v] = legs

    rows = []
    for v, legs in legs_by_vehicle.items():
        for leg in legs:
            rows.append({"vehicle": v, **{k:leg[k] for k in ["from_id","to_id","from_name","to_name","meters","seconds"]}})
    pd.DataFrame(rows).to_csv("outputs/leg_distances.csv", index=False)

    out_html = plot_multi("data/centros.csv", routes, legs_by_vehicle, "outputs/mapa.html")
    print(f"Mapa: {out_html}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--centros", default="./data/centros.csv")
    ap.add_argument("--demandas", default="./data/demandas.csv")
    ap.add_argument("--vehiculos", default="./data/vehiculos.csv")
    ap.add_argument("--osrm", default="https://router.project-osrm.org")
    args = ap.parse_args()
    main(args.centros, args.demandas, args.vehiculos, args.osrm)
