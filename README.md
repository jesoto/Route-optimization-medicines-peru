# VRP — Reparto de medicinas en Apurímac (Perú)

Optimización de rutas con **OSRM** (distancias viales) + **OR-Tools** (VRP/TSP) y visualización en **Folium**.
Incluye capacidades (volumen/kg), ventanas horarias, tiempos de servicio y restricción de cadena de frío.

## Requisitos
```bash
conda create -n vrp_apu python=3.10 -y
conda activate vrp_apu
pip install -r requirements.txt
```

## Ejecutar
```bash
python run.py --centros ./data/centros.csv --demandas ./data/demandas.csv --vehiculos ./data/vehiculos.csv --osrm https://router.project-osrm.org
```

Salidas: `outputs/plan_entregas.csv`, `outputs/leg_distances.csv`, `outputs/mapa.html`.
