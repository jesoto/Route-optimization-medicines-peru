# src/solve_vrp_osrm_apu.py
from __future__ import annotations
import pandas as pd, math
from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from src.osrm import osrm_table

def hm_to_sec(hm: str) -> int:
    h, m = hm.split(":")
    return int(h) * 3600 + int(m) * 60

def _fix_window(s: int | None, e: int | None, fallback_len: int = 4*3600) -> tuple[int, int]:
    """Si la ventana es inválida (None o s>e), repara a [s, s+fallback_len] / [0,24h] por defecto."""
    if s is None or e is None:
        return 0, 24*3600
    s, e = int(s), int(e)
    if s <= e:
        return s, e
    return s, s + fallback_len  # repara ventana invertida

def build_data(centros: pd.DataFrame, demandas: pd.DataFrame, vehiculos: pd.DataFrame):
    # Un solo depósito (debe existir en centros con id = depot_id de vehículos)
    depot_id = vehiculos.iloc[0]["depot_id"]
    depo_row = centros[centros["id"] == depot_id].iloc[0]

    # Lista de nodos: 0 = depósito, luego destinos únicos que aparecen en demandas
    nodes = [depo_row]
    node_map = {depo_row["id"]: 0}
    for _, d in demandas.iterrows():
        c = centros[centros["id"] == d["center_id"]].iloc[0]
        if c["id"] not in node_map:
            node_map[c["id"]] = len(nodes)
            nodes.append(c)
    pts = pd.DataFrame(nodes).reset_index(drop=True)

    n = len(pts)
    dem_vol = [0.0] * n
    dem_kg = [0.0] * n
    service_sec = [0] * n
    tw_start = [0] * n
    tw_end = [24 * 3600] * n

    # Ventana del depósito según su horario
    depo_open = hm_to_sec(depo_row["open_from"])
    depo_close = hm_to_sec(depo_row["open_to"])
    tw_start[0], tw_end[0] = _fix_window(depo_open, depo_close, 9*3600)

    # Centros con cadena de frío (si alguna demanda lo requiere)
    cold_centers = set(demandas.loc[demandas["cold_chain"] == True, "center_id"].tolist())

    # Acumular demanda + ventanas (intersección conservadora) + servicio
    for _, d in demandas.iterrows():
        idx = node_map[d["center_id"]]
        dem_vol[idx] += float(d["vol_l"])
        dem_kg[idx]  += float(d["kg"])
        service_sec[idx] = max(service_sec[idx], int(d["service_min"]) * 60)

        s = hm_to_sec(d["tw_start"]); e = hm_to_sec(d["tw_end"])
        s, e = _fix_window(s, e)
        if tw_start[idx] == 0 and tw_end[idx] == 24*3600:
            tw_start[idx], tw_end[idx] = s, e
        else:
            # intersectar
            new_s = max(tw_start[idx], s)
            new_e = min(tw_end[idx], e)
            if new_s <= new_e:
                tw_start[idx], tw_end[idx] = new_s, new_e
            else:
                # si se cruza mal, asignar una ventanita mínima de 2h desde s
                tw_start[idx], tw_end[idx] = _fix_window(s, s + 2*3600)

    # Capacidades de vehículos y refrigeración
    veh_caps_vol = [float(v) for v in vehiculos["capacity_vol_l"].tolist()]
    veh_caps_kg  = [float(v) for v in vehiculos["capacity_kg"].tolist()]
    veh_is_refrig= [bool(v)  for v in vehiculos["refrigerated"].tolist()]

    # Turnos (para soft bounds de start/end)
    v_starts = [hm_to_sec(v) for v in vehiculos["shift_start"].tolist()]
    v_ends   = [hm_to_sec(v) for v in vehiculos["shift_end"].tolist()]
    fleet_start = min(v_starts) if v_starts else tw_start[0]
    fleet_end   = max(v_ends)   if v_ends   else tw_end[0]

    return (
        pts, dem_vol, dem_kg, service_sec, tw_start, tw_end,
        veh_caps_vol, veh_caps_kg, veh_is_refrig, cold_centers,
        fleet_start, fleet_end
    )

def solve_vrp(centros: pd.DataFrame, demandas: pd.DataFrame, vehiculos: pd.DataFrame, osrm_url: str):
    (
        points, dem_vol, dem_kg, service_sec, tw_start, tw_end,
        cap_vol, cap_kg, veh_is_refrig, cold_centers,
        fleet_start, fleet_end
    ) = build_data(centros, demandas, vehiculos)

    # Matrices OSRM
    distances, durations = osrm_table(osrm_url, points)  # m, s
    if durations is None:
        # Si OSRM no devolvió duraciones, estimar a 30 km/h
        durations = []
        for row in distances:
            durations.append([int(round(d / 1000.0 / 30.0 * 3600.0)) for d in row])

    # --- DEBUG: imprimir ventanas y servicio calculados ---
    print("DEBUG ventanas/servicio por nodo:")
    for i in range(len(points)):
        print(i, points.iloc[i]["id"], points.iloc[i]["name"],
              f"tw=[{tw_start[i]}..{tw_end[i]}] sec",
              f"svc={service_sec[i]} sec")

    n = len(points)
    V = len(vehiculos)
    starts = [0] * V
    ends   = [0] * V

    manager = pywrapcp.RoutingIndexManager(n, V, starts, ends)
    routing = pywrapcp.RoutingModel(manager)

    # Costo: distancia (m)
    def dist_cb(from_index, to_index):
        i = manager.IndexToNode(from_index); j = manager.IndexToNode(to_index)
        return int(round(distances[i][j]))
    dist_idx = routing.RegisterTransitCallback(dist_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(dist_idx)

    # Duración vial + tiempo de servicio en el nodo de salida (excepto depósito)
    def dur_cb(from_index, to_index):
        i = manager.IndexToNode(from_index); j = manager.IndexToNode(to_index)
        travel = int(round(durations[i][j]))
        service = int(service_sec[i]) if i != 0 else 0
        return travel + service
    dur_idx = routing.RegisterTransitCallback(dur_cb)

    # Dimensión de tiempo (slack grande, horizonte amplio)
    routing.AddDimension(
        dur_idx,
        6 * 3600,          # slack (espera permisible)
        14 * 3600,         # horizonte por vehículo (14h)
        True,              # start at zero
        "Time"
    )
    time_dim = routing.GetDimensionOrDie("Time")

    # SOFT BOUNDS para TODAS las ventanas (evita infeasibilidad dura)
    penalty_per_sec = 5  # ajusta: mayor = más estricto en cumplir ventanas
    for node in range(n):
        index = manager.NodeToIndex(node)
        s, e = _fix_window(int(tw_start[node]), int(tw_end[node]))
        # rango amplio para no romper:
        time_dim.CumulVar(index).SetRange(0, 24*3600)
        time_dim.SetCumulVarSoftLowerBound(index, s, penalty_per_sec)
        time_dim.SetCumulVarSoftUpperBound(index, e, penalty_per_sec)

    # Soft bounds también en START/END por vehículo (turnos)
    for v in range(V):
        s_index = routing.Start(v)
        e_index = routing.End(v)
        time_dim.CumulVar(s_index).SetRange(0, 24*3600)
        time_dim.CumulVar(e_index).SetRange(0, 24*3600)
        time_dim.SetCumulVarSoftLowerBound(s_index, fleet_start, penalty_per_sec)
        time_dim.SetCumulVarSoftUpperBound(e_index,  fleet_end,  penalty_per_sec)

    # Capacidades (enteros escalados x10)
    dem_vol_int = [int(math.ceil(v * 10)) for v in dem_vol]
    dem_kg_int  = [int(math.ceil(v * 10)) for v in dem_kg]
    cap_vol_int = [int(math.floor(v * 10)) for v in cap_vol]
    cap_kg_int  = [int(math.floor(v * 10)) for v in cap_kg]

    def vol_dem(from_index): return dem_vol_int[manager.IndexToNode(from_index)]
    def kg_dem(from_index):  return dem_kg_int[manager.IndexToNode(from_index)]
    vol_idx = routing.RegisterUnaryTransitCallback(vol_dem)
    kg_idx  = routing.RegisterUnaryTransitCallback(kg_dem)

    routing.AddDimensionWithVehicleCapacity(vol_idx, 0, cap_vol_int, True, "Volume")
    routing.AddDimensionWithVehicleCapacity(kg_idx,  0, cap_kg_int,  True, "Weight")

    # Cadena de frío: prohibir asignación en vehículos no refrigerados
    cold_nodes = set()
    for node in range(1, n):  # omitir depósito
        if points.iloc[node]["id"] in cold_centers:
            cold_nodes.add(node)
    for node in cold_nodes:
        idx = manager.NodeToIndex(node)
        for v, is_ref in enumerate(veh_is_refrig):
            if not is_ref:
                routing.VehicleVar(idx).RemoveValue(v)

    # Buscar solución
    search = pywrapcp.DefaultRoutingSearchParameters()
    search.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    search.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search.time_limit.FromSeconds(20)

    solution = routing.SolveWithParameters(search)
    if not solution:
        return None, None, points

    # Extraer rutas
    routes = []
    for v in range(V):
        idx = routing.Start(v)
        order = []
        dist_m = 0
        while not routing.IsEnd(idx):
            node = manager.IndexToNode(idx)
            order.append(node)
            nxt = solution.Value(routing.NextVar(idx))
            dist_m += routing.GetArcCostForVehicle(idx, nxt, v)
            idx = nxt
        order.append(manager.IndexToNode(idx))
        routes.append({"vehicle": v, "order": order, "meters": dist_m})
    return routes, manager, points
