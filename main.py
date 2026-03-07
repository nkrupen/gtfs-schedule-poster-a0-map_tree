import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, LineString, Polygon, box as shapely_box
from shapely.affinity import translate, rotate
import zipfile
import os
import io
import re
import math
import urllib.parse
import warnings
from datetime import datetime, timedelta
import subprocess
import glob
import sys

# --- OSMNX IMPORT ---
try:
    import osmnx as ox
except ImportError:
    print("Installing osmnx...")
    subprocess.check_call(["pip", "install", "osmnx"])
    import osmnx as ox

warnings.filterwarnings("ignore")


class GTFSIntegratedPoster:
    def __init__(self, gtfs_path, routes_gpkg_path=None, water_geojson_path=None):
        self.gtfs_path = self._find_file(gtfs_path)
        self.routes_gpkg_path = self._find_file(routes_gpkg_path)
        self.water_geojson_path = self._find_file(water_geojson_path)
        self.data = {}

        # --- Configuration (UPDATED DIMENSIONS) ---
        self.bleed_mm = 3
        
        # Leikattu leveys 790 mm
        self.trim_w_mm = 790
        # Leikkuumerkein leveys 796 mm (eli trim + bleed*2)
        self.page_w_mm = self.trim_w_mm + (self.bleed_mm * 2) 
        
        # Korkeus ilman leikkuumerkkejä 1170 mm
        self.trim_h_mm = 1170 
        # Korkeus leikkuumerkkien kanssa
        self.page_h_mm = self.trim_h_mm + (self.bleed_mm * 2)

        self.config = {
            "color": "#3069b3", 
            "page_w_mm": self.page_w_mm,
            "page_h_mm": self.page_h_mm,
            "font_main": "Arial, sans-serif",
            "normal_color": "#000000",
            "school_color": "#888888",
            "holiday_color": "#00008B",
            "map_bg_color": "#F3F0EA",
            "building_color": "#E0D8D3",
            "water_color": "#B5D0D0",
            "green_color": "#CDEBC0",
            "street_fill": "#FFFFFF",
            "street_casing": "#C8C4C0",
            "street_width": 1.2,
            "street_casing_width": 2.0,
            "route_color": "#4A4A4A",
            "route_opacity": 0.8,
            "pin_color": "#E57373",
            "street_label_color": "#666666",
            "street_font_size": 6.5,
            "font_stop": "Arial, sans-serif",
            "font_pin": "Arial, sans-serif",
            "map_padding": 45,
            "stop_radius": 2.2,
            "box_padding": 1.5,
            "box_font_size": 5.5,
            "min_departures": 8,
            "layout_gap_mm": 5,
            "tree_box_h_mm": 360,
            "tree_min_viewbox_w": 3600,
            "tree_min_viewbox_h": 2600,
        }

        self.tree_viewbox = "0 0 1000 1000"
        self._load_data()

    def _find_file(self, filename):
        """Smart path resolver for Colab and local execution."""
        if not filename: return filename
        paths = [
            filename,
            f"/content/{filename}",
            os.path.join("assets", filename),
            os.path.join("/content/assets", filename),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        ]
        for p in paths:
            if os.path.exists(p):
                return p
        return filename

    # ----------------------------
    # DATA LOADING
    # ----------------------------
    def _load_data(self):
        print(f"Loading GTFS data from {self.gtfs_path}...")
        try:
            with zipfile.ZipFile(self.gtfs_path, "r") as z:
                def load_csv(name):
                    if name in z.namelist():
                        with z.open(name) as f:
                            content = f.read()
                            try:
                                text = content.decode("utf-8-sig")
                            except Exception:
                                text = content.decode("latin1")
                            first_line = text.splitlines()[0] if text.splitlines() else ""
                            sep = ";" if first_line.count(";") > first_line.count(",") else ","
                            df = pd.read_csv(
                                io.StringIO(text),
                                sep=sep,
                                dtype=str,
                                quotechar='"',
                                skipinitialspace=True,
                            )
                            df.columns = df.columns.str.lower().str.strip().str.replace('"', "")
                            return df
                    return pd.DataFrame()

                self.data["stops"] = load_csv("stops.txt")
                self.data["stop_times"] = load_csv("stop_times.txt")
                self.data["trips"] = load_csv("trips.txt")
                self.data["routes"] = load_csv("routes.txt")
                self.data["calendar"] = load_csv("calendar.txt")
                self.data["calendar_dates"] = load_csv("calendar_dates.txt")
                self.data["agency"] = load_csv("agency.txt")

                if not self.data["stops"].empty:
                    self.data["stops"]["stop_lat"] = pd.to_numeric(self.data["stops"]["stop_lat"], errors="coerce")
                    self.data["stops"]["stop_lon"] = pd.to_numeric(self.data["stops"]["stop_lon"], errors="coerce")

        except FileNotFoundError:
            print(f"Error: The file {self.gtfs_path} was not found.")
            self.data = {}

    def _is_excluded_line(self, route_short_name, headsign):
        return False

    # ----------------------------
    # HELPER FUNCTIONS
    # ----------------------------
    def get_stop_info(self, stop_id):
        stops = self.data.get("stops", pd.DataFrame())
        if stops.empty:
            return "Unknown", "???", "Unknown"
        row = stops[stops["stop_id"] == str(stop_id)]
        if row.empty:
            return "Unknown", "???", "Unknown"

        name = row.iloc[0].get("stop_name", "Unknown")
        code = row.iloc[0].get("stop_code", "")

        raw_zone = str(row.iloc[0].get("zone_id", ""))
        zone = raw_zone
        if raw_zone == "1":
            zone = "A"
        elif raw_zone == "2":
            zone = "B"

        if not str(code).startswith("K"):
            for col in row.columns:
                val = str(row.iloc[0][col])
                if val.startswith("K") and len(val) < 8:
                    code = val
                    break
        return name, code, zone

    def _clean_stop_name(self, name):
        name = re.sub(r"\s*\(.*?\)", "", str(name))
        return name.strip()

    def _read_svg_candidates(self, candidates):
        for p in candidates:
            try:
                if p and os.path.exists(p):
                    with open(p, "r", encoding="utf-8") as sf:
                        return sf.read()
            except Exception:
                pass
        return ""

    # ----------------------------
    # MAP HELPERS
    # ----------------------------
    def _load_layer_robust(self, path, target_bbox_3067, target_crs):
        if not path or not os.path.exists(path):
            return gpd.GeoDataFrame(geometry=[], crs=target_crs)
        try:
            meta = gpd.read_file(path, rows=1)
            native_crs = meta.crs if meta.crs else target_crs
            box_geom_3067 = shapely_box(*target_bbox_3067)

            if native_crs != target_crs:
                box_gdf = gpd.GeoDataFrame(geometry=[box_geom_3067], crs=target_crs)
                box_native = box_gdf.to_crs(native_crs)
                bbox_native_tuple = tuple(box_native.total_bounds)
            else:
                bbox_native_tuple = target_bbox_3067

            try:
                gdf = gpd.read_file(path, bbox=bbox_native_tuple)
            except Exception:
                gdf = gpd.read_file(path)

            if gdf.empty:
                return gpd.GeoDataFrame(geometry=[], crs=target_crs)
            if gdf.crs != target_crs:
                gdf = gdf.to_crs(target_crs)
            return gdf.clip(box_geom_3067)
        except Exception as e:
            print(f"Layer load error ({path}): {e}")
            return gpd.GeoDataFrame(geometry=[], crs=target_crs)

    def _geom_to_svg_path(self, geom, transform_func):
        if geom is None or geom.is_empty:
            return ""

        def coords_to_path(coords):
            coords = list(coords)
            if len(coords) < 2:
                return ""
            pts = [transform_func(x, y) for x, y in coords]
            return "M " + " L ".join([f"{x:.1f},{y:.1f}" for x, y in pts])

        if geom.geom_type == "LineString":
            return coords_to_path(geom.coords)
        elif geom.geom_type == "Polygon":
            return coords_to_path(geom.exterior.coords) + " Z"
        elif geom.geom_type == "MultiPolygon":
            return " ".join([coords_to_path(p.exterior.coords) + " Z" for p in geom.geoms])
        elif geom.geom_type == "MultiLineString":
            return " ".join([coords_to_path(l.coords) for l in geom.geoms])
        return ""

    def _estimate_text_box_dims(self, lines_of_text, font_size):
        max_w = 0
        total_h = 0
        line_h = font_size * 1.2
        char_multiplier = 0.55
        for line in lines_of_text:
            text_len = len(str(line).strip())
            w = max(text_len * font_size * char_multiplier, 15)
            max_w = max(max_w, w)
            total_h += line_h
        
        pad = self.config["box_padding"] * 2
        total_h += (font_size * 0.3)
        return math.ceil(max_w + pad), math.ceil(total_h + pad)

    def _check_overlap_shapely(self, candidate_geom, obstacles):
        for obs in obstacles:
            if candidate_geom.intersects(obs):
                return True
        return False

    def _wrap_line_list(self, lines_list, max_chars=18):
        rows = []
        current_row = []
        current_len = 0
        for line in lines_list:
            line = str(line)
            len_line = len(line) + 2
            if current_len + len_line > max_chars and current_row:
                rows.append(", ".join(current_row))
                current_row = [line]
                current_len = len_line
            else:
                current_row.append(line)
                current_len += len_line
        if current_row:
            rows.append(", ".join(current_row))
        return rows

    def _get_active_services_for_map(self, date_str):
        target_dt = datetime.strptime(date_str, "%Y-%m-%d")
        date_int = int(target_dt.strftime("%Y%m%d"))
        active_services = set()

        if not self.data["calendar"].empty:
            cal = self.data["calendar"]
            day_cols = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
            day_col = day_cols[target_dt.weekday()]
            mask = (
                (pd.to_numeric(cal["start_date"]) <= date_int)
                & (pd.to_numeric(cal["end_date"]) >= date_int)
                & (cal[day_col] == "1")
            )
            active_services.update(cal[mask]["service_id"].tolist())

        if not self.data["calendar_dates"].empty:
            cd = self.data["calendar_dates"]
            added = cd[(pd.to_numeric(cd["date"]) == date_int) & (cd["exception_type"] == "1")]
            removed = cd[(pd.to_numeric(cd["date"]) == date_int) & (cd["exception_type"] == "2")]
            active_services.update(added["service_id"].tolist())
            active_services.difference_update(removed["service_id"].tolist())
        return active_services

    def _get_weekly_departure_counts(self, visible_stop_ids, target_date_str):
        start_dt = datetime.strptime(target_date_str, "%Y-%m-%d")
        week_dates = [(start_dt + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
        counts = {sid: 0 for sid in visible_stop_ids}

        stop_times = self.data["stop_times"]
        trips = self.data["trips"]
        relevant_st = stop_times[stop_times["stop_id"].isin(visible_stop_ids)]
        trip_service_map = dict(zip(trips["trip_id"], trips["service_id"]))

        weekly_active_services = set()
        for d_str in week_dates:
            weekly_active_services.update(self._get_active_services_for_map(d_str))

        active_trips = set()
        for tid, sid in trip_service_map.items():
            if sid in weekly_active_services:
                active_trips.add(tid)

        valid_st = relevant_st[relevant_st["trip_id"].isin(active_trips)]
        stop_counts = valid_st["stop_id"].value_counts()
        for sid, count in stop_counts.items():
            counts[sid] = int(count)
        return counts

    def _get_high_frequency_routes(self, target_date_str, visible_stop_ids):
        start_dt = datetime.strptime(target_date_str, "%Y-%m-%d")
        week_dates = [(start_dt + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
        high_freq_routes = set()

        trips = self.data["trips"]
        routes = self.data["routes"]
        stop_times = self.data["stop_times"]

        relevant_trips = stop_times[stop_times["stop_id"].isin(visible_stop_ids)]["trip_id"].unique()
        rel_trips_df = trips[trips["trip_id"].isin(relevant_trips)]
        merged = rel_trips_df.merge(routes[["route_id", "route_short_name"]], on="route_id")
        trip_counts = merged.groupby(["service_id", "route_short_name"]).size().reset_index(name="count")

        for d_str in week_dates:
            active_services = self._get_active_services_for_map(d_str)
            if not active_services:
                continue
            daily_counts = trip_counts[trip_counts["service_id"].isin(active_services)]
            route_daily_total = daily_counts.groupby("route_short_name")["count"].sum()
            busy_routes = route_daily_total[route_daily_total > self.config["min_departures"]].index.tolist()
            high_freq_routes.update(busy_routes)

        return high_freq_routes

    def _get_stop_metadata(self, visible_stop_ids):
        if len(visible_stop_ids) == 0:
            return {}
        st = self.data["stop_times"]
        trips = self.data["trips"]
        routes = self.data["routes"]
        rel_st = st[st["stop_id"].isin(visible_stop_ids)]

        trip_ids = rel_st["trip_id"].unique()
        relevant_full_st = st[st["trip_id"].isin(trip_ids)][["trip_id", "stop_sequence"]]
        relevant_full_st["stop_sequence"] = pd.to_numeric(relevant_full_st["stop_sequence"])
        max_seqs = relevant_full_st.groupby("trip_id")["stop_sequence"].max()
        
        merged = rel_st.merge(trips[["trip_id", "route_id", "trip_headsign"]], on="trip_id")
        merged = merged.merge(routes[["route_id", "route_short_name"]], on="route_id")
        
        merged["stop_sequence"] = pd.to_numeric(merged["stop_sequence"])
        merged["max_seq"] = merged["trip_id"].map(max_seqs)
        merged = merged[merged["stop_sequence"] < merged["max_seq"]]

        metadata = {}

        def natural_sort_key(s):
            return [int(text) if text.isdigit() else text.lower() for text in re.split("([0-9]+)", str(s))]

        for sid, group in merged.groupby("stop_id"):
            lines = sorted(group["route_short_name"].unique().tolist(), key=natural_sort_key)
            headsigns = group["trip_headsign"].astype(str).tolist()
            total_trips = len(headsigns)
            direction_label = None
            if total_trips > 0:
                kantasatama_count = sum(1 for h in headsigns if "kantasatama" in h.lower())
                karhula_count = sum(1 for h in headsigns if "karhula" in h.lower())
                if (kantasatama_count / total_trips) >= 0.6:
                    direction_label = "Keskustaan"
                elif (karhula_count / total_trips) >= 0.6:
                    direction_label = "Karhulaan"
            metadata[sid] = {"lines": lines, "direction_label": direction_label}
        return metadata

    def _find_matching_column(self, gdf, route_list):
        best_col = None
        max_matches = 0
        route_set = set(map(str, route_list))
        for col in gdf.columns:
            if col == "geometry":
                continue
            unique_vals = set(gdf[col].astype(str).unique())
            matches = len(unique_vals.intersection(route_set))
            if matches > max_matches:
                max_matches = matches
                best_col = col
        return best_col

    def _determine_quietest_corner(self, width_mm, height_mm, street_gdf, stop_gdf):
        total_bounds = street_gdf.total_bounds if not street_gdf.empty else (0, 0, 1, 1)
        minx, miny, maxx, maxy = total_bounds
        midx, midy = (minx + maxx) / 2, (miny + maxy) / 2
        quads = {
            "TL": shapely_box(minx, midy, midx, maxy),
            "TR": shapely_box(midx, midy, maxx, maxy),
            "BL": shapely_box(minx, miny, midx, midy),
            "BR": shapely_box(midx, miny, maxx, midy),
        }
        scores = {}
        for q_name, q_poly in quads.items():
            s_count = len(street_gdf[street_gdf.intersects(q_poly)]) if not street_gdf.empty else 0
            st_count = len(stop_gdf[stop_gdf.intersects(q_poly)]) if not stop_gdf.empty else 0
            scores[q_name] = s_count + (st_count * 2)
        return sorted(scores.keys(), key=scores.get)

    def _generate_map_svg(self, center_stop_id, width_mm, height_mm, target_date):
        stops_df = self.data["stops"]
        center_row = stops_df[stops_df["stop_id"] == str(center_stop_id)]
        if center_row.empty:
            return ""

        c_lat, c_lon = center_row.iloc[0]["stop_lat"], center_row.iloc[0]["stop_lon"]

        target_crs = "EPSG:3067"
        center_gdf = gpd.GeoDataFrame(geometry=[Point(c_lon, c_lat)], crs="EPSG:4326").to_crs(target_crs)
        cx, cy = center_gdf.iloc[0].geometry.x, center_gdf.iloc[0].geometry.y

        svg_aspect = width_mm / height_mm
        view_h_meters = 1000
        view_w_meters = view_h_meters * svg_aspect

        min_x = cx - (view_w_meters / 2)
        max_x = cx + (view_w_meters / 2)
        min_y = cy - (view_h_meters / 2)
        max_y = cy + (view_h_meters / 2)
        target_bbox_3067 = (min_x, min_y, max_x, max_y)
        box_geom_3067 = shapely_box(*target_bbox_3067)

        fetch_radius = max(view_w_meters, view_h_meters) / 2 * 1.1

        streets = gpd.GeoDataFrame(geometry=[], crs=target_crs)
        buildings = gpd.GeoDataFrame(geometry=[], crs=target_crs)
        water = gpd.GeoDataFrame(geometry=[], crs=target_crs)
        green = gpd.GeoDataFrame(geometry=[], crs=target_crs)

        try:
            # 1) Streets (OSM)
            G = ox.graph_from_point((c_lat, c_lon), dist=fetch_radius, network_type="all")
            streets = ox.graph_to_gdfs(G, nodes=False, edges=True)
            streets = streets.to_crs(target_crs).clip(box_geom_3067)

            # 2) Water (Local file)
            water = self._load_layer_robust(self.water_geojson_path, target_bbox_3067, target_crs)

            # 3) Green areas (OSM)
            green_tags = {
                "landuse": ["grass", "forest", "meadow", "recreation_ground", "village_green", "allotments"],
                "leisure": ["park", "garden", "pitch"],
                "natural": "wood",
            }
            try:
                green = ox.features_from_point((c_lat, c_lon), tags=green_tags, dist=fetch_radius)
                if not green.empty:
                    green = green.to_crs(target_crs).clip(box_geom_3067)
            except Exception:
                pass

            # 4) Buildings (OSM)
            try:
                buildings = ox.features_from_point((c_lat, c_lon), tags={"building": True}, dist=fetch_radius)
                if not buildings.empty:
                    buildings = buildings.to_crs(target_crs).clip(box_geom_3067)
                    buildings = buildings[buildings.geometry.type.isin(["Polygon", "MultiPolygon"])]
            except Exception:
                pass

        except Exception as e:
            print(f"Warning: Issue fetching map data: {e}")

        wgs_center = center_gdf.to_crs("EPSG:4326")
        wgs_bounds = wgs_center.buffer(0.015).total_bounds
        visible_stops_df = stops_df[
            (stops_df["stop_lat"].between(wgs_bounds[1], wgs_bounds[3]))
            & (stops_df["stop_lon"].between(wgs_bounds[0], wgs_bounds[2]))
        ]
        stops_gdf = (
            gpd.GeoDataFrame(
                visible_stops_df,
                geometry=gpd.points_from_xy(visible_stops_df.stop_lon, visible_stops_df.stop_lat),
                crs="EPSG:4326",
            )
            .to_crs(target_crs)
            .clip(shapely_box(*target_bbox_3067))
        )

        visible_stop_ids = stops_gdf["stop_id"].unique()
        stop_metadata = self._get_stop_metadata(visible_stop_ids)
        departure_counts = self._get_weekly_departure_counts(visible_stop_ids, target_date)

        routes_gdf = self._load_layer_robust(self.routes_gpkg_path, target_bbox_3067, target_crs)
        if not routes_gdf.empty:
            high_freq_routes = self._get_high_frequency_routes(target_date, visible_stop_ids)
            match_col = self._find_matching_column(routes_gdf, high_freq_routes)
            if match_col:
                routes_gdf = routes_gdf[routes_gdf[match_col].astype(str).isin(set(map(str, high_freq_routes)))]

        def project(x, y):
            px = (x - min_x) / (max_x - min_x) * width_mm
            py = (max_y - y) / (max_y - min_y) * height_mm
            return px, py

        bg_svg, map_labels_svg, stop_balls_svg, lines_and_boxes_svg, pin_svg = [], [], [], [], []
        bg_svg.append(f'<rect x="0" y="0" width="{width_mm}" height="{height_mm}" fill="{self.config["map_bg_color"]}"/>')

        if not water.empty:
            for geom in water.geometry:
                path = self._geom_to_svg_path(geom, project)
                if path:
                    bg_svg.append(f'<path d="{path}" fill="{self.config["water_color"]}" stroke="none"/>')

        if not green.empty:
            for geom in green.geometry:
                path = self._geom_to_svg_path(geom, project)
                if path:
                    bg_svg.append(f'<path d="{path}" fill="{self.config["green_color"]}" stroke="none"/>')

        if not buildings.empty:
            for geom in buildings.geometry:
                path = self._geom_to_svg_path(geom, project)
                if path:
                    bg_svg.append(f'<path d="{path}" fill="{self.config["building_color"]}" stroke="none"/>')

        if not streets.empty:
            for geom in streets.geometry:
                path = self._geom_to_svg_path(geom, project)
                if path:
                    bg_svg.append(
                        f'<path d="{path}" fill="none" stroke="{self.config["street_casing"]}" stroke-width="{self.config["street_casing_width"]}" stroke-linecap="round" stroke-linejoin="round"/>'
                    )
            for geom in streets.geometry:
                path = self._geom_to_svg_path(geom, project)
                if path:
                    bg_svg.append(
                        f'<path d="{path}" fill="none" stroke="{self.config["street_fill"]}" stroke-width="{self.config["street_width"]}" stroke-linecap="round" stroke-linejoin="round"/>'
                    )

        if not routes_gdf.empty:
            for geom in routes_gdf.geometry:
                path = self._geom_to_svg_path(geom, project)
                if path:
                    bg_svg.append(
                        f'<path d="{path}" fill="none" stroke="{self.config["route_color"]}" stroke-width="2" opacity="{self.config["route_opacity"]}"/>'
                    )

        placed_boxes_obstacles, center_stop_geom, other_stops = [], None, []
        
        # --- FILTERING LOGIC (Virtuaali + Blacklist) ---
        blacklist_stops = ["Keskuskatu 17 I", "Kapteeninkatu", "Kauppakatu Hyvätuuli", "Kauppatori Keskuskatu"]
        
        for _, row in stops_gdf.iterrows():
            if str(row["stop_id"]) == str(center_stop_id):
                center_stop_geom = row
            else:
                stop_name = str(row["stop_name"])
                if "virtuaali" in stop_name.lower():
                    continue
                if stop_name.strip() in blacklist_stops:
                    continue
                other_stops.append(row)

        map_center_x, map_center_y = width_mm / 2, height_mm / 2
        you_are_here_obstacle = None

        if center_stop_geom is not None:
            gx, gy = center_stop_geom.geometry.x, center_stop_geom.geometry.y
            sx, sy = project(gx, gy)
            pin_svg.append(f'<circle cx="{sx}" cy="{sy}" r="4" fill="{self.config["pin_color"]}" stroke="none"/>')
            pin_svg.append(f'<circle cx="{sx}" cy="{sy}" r="1.5" fill="white" stroke="none"/>')

            label_txt_1, label_txt_2 = "Olet tässä", "You are here"
            ty = sy + 18
            pin_svg.append(
                f'<text x="{sx}" y="{ty}" font-family="{self.config["font_pin"]}" font-size="10" text-anchor="middle" stroke="white" stroke-width="3" paint-order="stroke">{label_txt_1}</text>'
            )
            pin_svg.append(
                f'<text x="{sx}" y="{ty}" font-family="{self.config["font_pin"]}" font-size="10" text-anchor="middle" fill="#000">{label_txt_1}</text>'
            )
            pin_svg.append(
                f'<text x="{sx}" y="{ty+10}" font-family="{self.config["font_pin"]}" font-size="9" text-anchor="middle" stroke="white" stroke-width="3" paint-order="stroke" font-style="italic">{label_txt_2}</text>'
            )
            pin_svg.append(
                f'<text x="{sx}" y="{ty+10}" font-family="{self.config["font_pin"]}" font-size="9" text-anchor="middle" fill="#444" font-style="italic">{label_txt_2}</text>'
            )
            
            you_are_here_obstacle = shapely_box(sx - 36, sy - 10, sx + 36, sy + 42)
            placed_boxes_obstacles.append(you_are_here_obstacle)

        def sort_key(r):
            dist = r.geometry.distance(center_gdf.iloc[0].geometry)
            is_close_priority = 0 if dist < 30 else 1
            dep_count = departure_counts.get(str(r["stop_id"]), 0)
            return (is_close_priority, -dep_count, dist)

        other_stops.sort(key=sort_key)

        font_size = self.config["box_font_size"]
        stop_obstacles_map = {}
        for row in other_stops:
            gx, gy = row.geometry.x, row.geometry.y
            sx, sy = project(gx, gy)
            
            r = self.config["stop_radius"]
            if not (r <= sx <= width_mm - r and r <= sy <= height_mm - r):
                continue
                
            stop_obstacles_map[str(row["stop_id"])] = Point(sx, sy).buffer(self.config["stop_radius"] + 2)

        for row in other_stops:
            sid = str(row["stop_id"])
            if sid not in stop_obstacles_map:
                continue
            my_stop_poly = stop_obstacles_map[sid]
            other_stops_polys = [v for k, v in stop_obstacles_map.items() if k != sid]
            all_stops_polys = list(stop_obstacles_map.values())
            sx, sy = my_stop_poly.centroid.x, my_stop_poly.centroid.y

            meta = stop_metadata.get(sid, {"lines": [], "direction_label": None})
            name = str(row["stop_name"])
            code = str(row.get("stop_code", "")) if str(row.get("stop_code", "")).startswith("K") else ""
            if not code:
                for c in row.index:
                    if str(row[c]).startswith("K") and len(str(row[c])) < 8:
                        code = str(row[c])
                        break

            full_box_lines = [name]
            code_line_index = -1
            if code:
                full_code_str = code
                if meta["direction_label"]:
                    full_code_str += f"    {meta['direction_label']}"
                full_box_lines.append(full_code_str)
                code_line_index = 1
            
            all_lines_str = ", ".join(meta["lines"])
            if len(all_lines_str) <= len(name) * 1.2:
                full_box_lines.append(all_lines_str)
            else:
                full_box_lines.extend(self._wrap_line_list(meta["lines"], max_chars=18))
            
            simple_box_lines = [name]

            def try_place(lines):
                bw, bh = self._estimate_text_box_dims(lines, font_size)
                vec_x, vec_y = map_center_x - sx, map_center_y - sy
                angle_to_center = math.atan2(vec_y, vec_x)
                distances = [25, 45, 65, 85, 105]
                angles = [0, 0.5, -0.5, 1.0, -1.0, 1.5, -1.5, 2.0, -2.0]
                
                dep_count = departure_counts.get(sid, 0)
                is_important_and_covered = False
                if dep_count > 10 and you_are_here_obstacle:
                    if you_are_here_obstacle.contains(Point(sx, sy)) or you_are_here_obstacle.distance(Point(sx, sy)) < 5:
                        is_important_and_covered = True

                for dist in distances:
                    for ang_offset in angles:
                        rad = angle_to_center + ang_offset
                        pcx, pcy = sx + math.cos(rad) * dist, sy + math.sin(rad) * dist
                        tlx, tly = pcx - bw / 2, pcy - bh / 2
                        mp = self.config["map_padding"]
                        tlx = max(mp, min(tlx, width_mm - mp - bw))
                        tly = max(mp, min(tly, height_mm - mp - bh))
                        box_cx, box_cy = tlx + bw / 2, tly + bh / 2
                        cand_box_poly = shapely_box(tlx, tly, tlx + bw, tly + bh)
                        conn_line = LineString([(sx, sy), (box_cx, box_cy)])
                        line_poly = conn_line.buffer(1)

                        obstacles_for_box = placed_boxes_obstacles + all_stops_polys
                        if self._check_overlap_shapely(cand_box_poly, obstacles_for_box):
                            continue
                        
                        obstacles_for_line = list(placed_boxes_obstacles) + other_stops_polys
                        
                        if is_important_and_covered and you_are_here_obstacle:
                            if you_are_here_obstacle in obstacles_for_line:
                                obstacles_for_line.remove(you_are_here_obstacle)

                        if self._check_overlap_shapely(line_poly, obstacles_for_line):
                            continue
                        
                        return (tlx, tly, bw, bh, box_cx, box_cy)
                return None

            placement = try_place(full_box_lines)
            final_lines = full_box_lines
            if not placement:
                placement = try_place(simple_box_lines)
                final_lines = simple_box_lines
                code_line_index = -1

            if placement:
                stop_balls_svg.append(
                    f'<circle cx="{sx}" cy="{sy}" r="{self.config["stop_radius"]}" fill="white" stroke="#333" stroke-width="1.5"/>'
                )
                bx, by, bw, bh, cx_box, cy_box = placement
                lines_and_boxes_svg.append(
                    f'<line x1="{sx}" y1="{sy}" x2="{cx_box}" y2="{cy_box}" stroke="black" stroke-width="1.0"/>'
                )
                lines_and_boxes_svg.append(
                    f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="1.5" ry="1.5" fill="white" stroke="black" stroke-width="0.5"/>'
                )
                curr_y = by + self.config["box_padding"] + font_size
                for i, txt in enumerate(final_lines):
                    fw = "bold" if i == 0 else ("bold" if (i == code_line_index and i != -1) else "normal")
                    fs = "italic" if (i == code_line_index and i != -1) else "normal"
                    lines_and_boxes_svg.append(
                        f'<text x="{bx + self.config["box_padding"] + 1.5}" y="{curr_y}" font-family="{self.config["font_stop"]}" font-size="{font_size}" font-weight="{fw}" font-style="{fs}" fill="black">{txt}</text>'
                    )
                    curr_y += (font_size * 1.2)
                placed_boxes_obstacles.append(shapely_box(bx, by, bx + bw, by + bh))
                placed_boxes_obstacles.append(LineString([(sx, sy), (cx_box, cy_box)]).buffer(2))

        if not streets.empty:
            processed_names = set()
            static_obstacles = placed_boxes_obstacles + list(stop_obstacles_map.values())
            if not routes_gdf.empty:
                static_obstacles.append(routes_gdf.unary_union.buffer(2))
            placed_text_obstacles = []
            for _, row in streets.iterrows():
                if "name" in row and row["name"] and isinstance(row["name"], str) and row.geometry.length > 50:
                    name = row["name"]
                    if name in processed_names:
                        continue
                    geom = row.geometry
                    if geom.geom_type == "LineString":
                        coords = list(geom.coords)
                        if len(coords) >= 2:
                            p1, p2 = coords[0], coords[-1]
                            dx, dy = p2[0] - p1[0], p2[1] - p1[1]
                            angle = math.degrees(math.atan2(dy, dx))
                            if angle > 90:
                                angle -= 180
                            elif angle < -90:
                                angle += 180
                            mid = geom.interpolate(0.5, normalized=True)
                            mx, my = project(mid.x, mid.y)

                            s_fs = self.config["street_font_size"]
                            text_w = len(name) * s_fs * 0.5
                            text_h = s_fs
                            text_poly = shapely_box(mx - text_w / 2, my - text_h / 2, mx + text_w / 2, my + text_h / 2)
                            rotated_poly = rotate(text_poly, angle, origin=(mx, my))

                            if 0 <= mx <= width_mm and 0 <= my <= height_mm:
                                all_obs = static_obstacles + placed_text_obstacles
                                if not self._check_overlap_shapely(rotated_poly, all_obs):
                                    map_labels_svg.append(
                                        f'<text x="{mx}" y="{my}" font-family="{self.config["font_main"]}" font-size="{s_fs}" fill="{self.config["street_label_color"]}" text-anchor="middle" transform="rotate({-angle}, {mx}, {my})">{name}</text>'
                                    )
                                    processed_names.add(name)
                                    placed_text_obstacles.append(rotated_poly)

        # --- SCALE BAR + NORTH ARROW ---
        meters_per_mm = view_w_meters / width_mm
        target_scale_m = 200
        scale_bar_len_mm = target_scale_m / meters_per_mm
        if scale_bar_len_mm > width_mm / 3:
            target_scale_m = 100
            scale_bar_len_mm = target_scale_m / meters_per_mm

        sb_h = 20
        sb_w = scale_bar_len_mm + 15

        preferred_corners = self._determine_quietest_corner(width_mm, height_mm, streets, stops_gdf)
        final_ex, final_ey = 0, 0
        placed_scale = False
        base_pad = 25

        for q_corner in preferred_corners:
            if q_corner == "TL":
                ex, ey = base_pad, base_pad
            elif q_corner == "TR":
                ex, ey = width_mm - sb_w - base_pad, base_pad
            elif q_corner == "BL":
                ex, ey = base_pad, height_mm - sb_h - base_pad
            else:  # BR
                ex, ey = width_mm - sb_w - base_pad, height_mm - sb_h - base_pad

            ex = max(base_pad, min(ex, width_mm - sb_w - base_pad))
            ey = max(base_pad, min(ey, height_mm - sb_h - base_pad))

            scale_box = shapely_box(ex, ey, ex + sb_w, ey + sb_h)
            if not self._check_overlap_shapely(scale_box, placed_boxes_obstacles):
                final_ex, final_ey = ex, ey
                placed_scale = True
                break

        if not placed_scale:
            final_ex = width_mm - sb_w - 40
            final_ey = height_mm - sb_h - 40

        sb_svg = (
            f'<g transform="translate({final_ex}, {final_ey})">'
            f'<line x1="0" y1="15" x2="{scale_bar_len_mm}" y2="15" stroke="#333" stroke-width="1" />'
            f'<line x1="0" y1="12" x2="0" y2="15" stroke="#333" stroke-width="1" />'
            f'<line x1="{scale_bar_len_mm}" y1="12" x2="{scale_bar_len_mm}" y2="15" stroke="#333" stroke-width="1" />'
            f'<text x="{scale_bar_len_mm/2}" y="10" font-family="Arial" font-size="5" text-anchor="middle" fill="#333">{target_scale_m} m</text>'
            f"</g>"
        )
        na_x = final_ex + scale_bar_len_mm + 5
        na_svg = (
            f'<g transform="translate({na_x}, {final_ey + 5})">'
            f'<path d="M 5,15 L 5,0 L 2,5 M 5,0 L 8,5" fill="none" stroke="#333" stroke-width="1" />'
            f'<text x="5" y="-2" font-family="Arial" font-size="6" text-anchor="middle" font-weight="bold" fill="#333">N</text>'
            f"</g>"
        )
        
        copy_svg = f'<text x="{final_ex}" y="{final_ey - 3}" font-family="Arial" font-size="5" fill="#555" text-anchor="start">© OpenStreetMap contributors</text>'

        return "".join(bg_svg + map_labels_svg + stop_balls_svg + lines_and_boxes_svg + pin_svg + [sb_svg, na_svg, copy_svg])

    # ----------------------------
    # SCHEDULE HELPERS
    # ----------------------------
    def _is_service_active_in_week(self, service_id, monday_dt, sunday_dt):
        active_days = [False] * 7
        cal = self.data.get("calendar", pd.DataFrame())
        if not cal.empty and "service_id" in cal.columns:
            row = cal[cal["service_id"] == service_id]
            if not row.empty:
                r = row.iloc[0]
                try:
                    start_date = datetime.strptime(r["start_date"], "%Y%m%d")
                    end_date = datetime.strptime(r["end_date"], "%Y%m%d")
                    if not (end_date < monday_dt or start_date > sunday_dt):
                        days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
                        for i, day_name in enumerate(days):
                            if r[day_name] == "1":
                                current_day_date = monday_dt + timedelta(days=i)
                                if start_date <= current_day_date <= end_date:
                                    active_days[i] = True
                except Exception:
                    pass

        cal_dates = self.data.get("calendar_dates", pd.DataFrame())
        if not cal_dates.empty and "service_id" in cal_dates.columns:
            dates = cal_dates[cal_dates["service_id"] == service_id]
            for _, d_row in dates.iterrows():
                try:
                    exc_date = datetime.strptime(d_row["date"], "%Y%m%d")
                    if monday_dt <= exc_date <= sunday_dt:
                        wd = exc_date.weekday()
                        if d_row["exception_type"] == "1":
                            active_days[wd] = True
                        elif d_row["exception_type"] == "2":
                            active_days[wd] = False
                except Exception:
                    pass

        return tuple(active_days)

    def _get_active_trips_for_week(self, stop_id, start_dt, end_dt):
        st = self.data.get("stop_times", pd.DataFrame())
        trips = self.data.get("trips", pd.DataFrame())
        if st.empty or trips.empty:
            return pd.DataFrame()

        stop_visits = st[st["stop_id"] == str(stop_id)]
        if stop_visits.empty:
            return pd.DataFrame()

        if "service_id" not in trips.columns:
            return pd.DataFrame()

        valid_sids = set()
        unique_sids = trips["service_id"].unique()
        schedule_map = {}
        for sid in unique_sids:
            active_tuple = self._is_service_active_in_week(sid, start_dt, end_dt)
            if any(active_tuple):
                valid_sids.add(sid)
                schedule_map[sid] = active_tuple

        relevant_trips = trips[trips["trip_id"].isin(stop_visits["trip_id"])]
        active_trips = relevant_trips[relevant_trips["service_id"].isin(valid_sids)].copy()
        active_trips["week_pattern"] = active_trips["service_id"].map(schedule_map)
        return active_trips

    def generate_line_bar_data(self, active_trips):
        if active_trips.empty:
            return []
        merged = active_trips.merge(self.data["routes"], on="route_id")
        
        # --- FILTER ALLOWED LINES (Top Bar) ---
        merged = merged[~merged.apply(lambda x: self._is_excluded_line(x["route_short_name"], x.get("trip_headsign", "")), axis=1)]

        has_agency = "agency_id" in merged.columns
        lines_data = []
        grouped = merged.groupby("route_short_name")
        for name, group in grouped:
            headsign = ""
            if "trip_headsign" in group.columns and not group["trip_headsign"].mode().empty:
                headsign = group["trip_headsign"].mode()[0]
            icon_type = "bus"
            if has_agency:
                agencies = group["agency_id"].unique().astype(str)
                if len(agencies) == 1 and "46947" in agencies[0]:
                    icon_type = "bus" 
            lines_data.append({"num": name, "dest": headsign, "icon": icon_type})

        def n_sort(s):
            return [int(t) if t.isdigit() else t.lower() for t in re.split("([0-9]+)", str(s))]

        lines_data.sort(key=lambda x: n_sort(x["num"]))
        return lines_data

    def _combine_patterns(self, p1, p2):
        if p1 is None:
            return p2
        if p2 is None:
            return p1
        return tuple(a or b for a, b in zip(p1, p2))

    def generate_schedule_html_data(self, stop_id, school_week_start, holiday_week_start):
        _, _, stop_zone = self.get_stop_info(stop_id)
        if stop_zone == "B":
            schedule_col_gap = "25px"
        else:
            schedule_col_gap = "10px"

        school_end = school_week_start + timedelta(days=6)
        holiday_end = holiday_week_start + timedelta(days=6)

        trips_s = self._get_active_trips_for_week(stop_id, school_week_start, school_end)
        trips_h = self._get_active_trips_for_week(stop_id, holiday_week_start, holiday_end)
        st = self.data["stop_times"]
        visits = st[st["stop_id"] == str(stop_id)]

        def process_trips(trips_df, is_school):
            if trips_df.empty:
                return []
            merged = visits.merge(trips_df, on="trip_id").merge(self.data["routes"], on="route_id")

            # --- FILTER ALLOWED LINES (Timetable) ---
            merged = merged[~merged.apply(lambda x: self._is_excluded_line(x["route_short_name"], x.get("trip_headsign", "")), axis=1)]

            # --- UPDATE: Filter out stops that are final on their trip (Timetable) ---
            trip_ids = merged["trip_id"].unique()
            all_st = self.data["stop_times"]
            relevant_all_st = all_st[all_st["trip_id"].isin(trip_ids)][["trip_id", "stop_sequence"]]
            relevant_all_st["stop_sequence"] = pd.to_numeric(relevant_all_st["stop_sequence"])
            max_seqs = relevant_all_st.groupby("trip_id")["stop_sequence"].max()
            
            merged["stop_sequence"] = pd.to_numeric(merged["stop_sequence"])
            merged["max_seq"] = merged["trip_id"].map(max_seqs)
            merged = merged[merged["stop_sequence"] < merged["max_seq"]]
            # ---------------------------------------------------------------------

            def parse_time(t):
                try:
                    parts = str(t).split(":")
                    return int(parts[0]), int(parts[1])
                except Exception:
                    return 0, 0

            departures = []
            for _, row in merged.iterrows():
                h, m = parse_time(row["arrival_time"])
                pat, line = row["week_pattern"], row["route_short_name"]
                departures.append(
                    {
                        "sig": (h, m, line),
                        "pattern": pat,
                        "line": line,
                        "h": h,
                        "m": m,
                        "origin": "S" if is_school else "H",
                    }
                )
            return departures

        deps_s = process_trips(trips_s, True)
        deps_h = process_trips(trips_h, False)

        merged_map = {}
        for d in deps_s:
            k = d["sig"]
            if k not in merged_map:
                merged_map[k] = {"S": None, "H": None, "line": d["line"], "h": d["h"], "m": d["m"]}
            merged_map[k]["S"] = self._combine_patterns(merged_map[k]["S"], d["pattern"])

        for d in deps_h:
            k = d["sig"]
            if k not in merged_map:
                merged_map[k] = {"S": None, "H": None, "line": d["line"], "h": d["h"], "m": d["m"]}
            merged_map[k]["H"] = self._combine_patterns(merged_map[k]["H"], d["pattern"])

        mon_fri_patterns = {}
        next_footnote = 1
        has_school_only_trips = False
        has_holiday_only_trips = False
        raw_rows = []

        for _, info in merged_map.items():
            pat_s, pat_h = info["S"], info["H"]
            final_type = "NORMAL"
            active_pat = None
            if pat_s and pat_h:
                final_type = "NORMAL"
                active_pat = pat_s
            elif pat_s and not pat_h:
                final_type = "SCHOOL"
                active_pat = pat_s
            elif not pat_s and pat_h:
                final_type = "HOLIDAY"
                active_pat = pat_h

            if final_type == "SCHOOL":
                has_school_only_trips = True
            if final_type == "HOLIDAY":
                has_holiday_only_trips = True

            if active_pat:
                mf_slice = active_pat[0:5]
                if any(mf_slice):
                    ft_idx = None
                    if not all(mf_slice):
                        if mf_slice not in mon_fri_patterns:
                            mon_fri_patterns[mf_slice] = next_footnote
                            next_footnote += 1
                        ft_idx = mon_fri_patterns[mf_slice]
                    raw_rows.append(
                        {
                            "bucket": "Mon-Fri",
                            "h": info["h"],
                            "m": info["m"],
                            "line": info["line"],
                            "footnote": ft_idx,
                            "type": final_type,
                        }
                    )
                if active_pat[5]:
                    raw_rows.append(
                        {
                            "bucket": "Sat",
                            "h": info["h"],
                            "m": info["m"],
                            "line": info["line"],
                            "footnote": None,
                            "type": "NORMAL",
                        }
                    )
                if active_pat[6]:
                    raw_rows.append(
                        {
                            "bucket": "Sun",
                            "h": info["h"],
                            "m": info["m"],
                            "line": info["line"],
                            "footnote": None,
                            "type": "NORMAL",
                        }
                    )

        # -----------------------------
        # MERGE LOGIC: SCHOOL/HOLIDAY < 4 MINS
        # -----------------------------
        mon_fri_rows = [r for r in raw_rows if r["bucket"] == "Mon-Fri"]
        other_rows = [r for r in raw_rows if r["bucket"] != "Mon-Fri"]
        
        mon_fri_rows.sort(key=lambda x: (x["h"], x["m"]))

        merged_mon_fri = []
        skip_indices = set()

        for i in range(len(mon_fri_rows)):
            if i in skip_indices:
                continue

            current = mon_fri_rows[i]
            if i + 1 < len(mon_fri_rows):
                next_row = mon_fri_rows[i+1]
                types = {current["type"], next_row["type"]}
                is_mixed_pair = ("SCHOOL" in types) and ("HOLIDAY" in types)
                same_line = (current["line"] == next_row["line"])
                t1 = current["h"] * 60 + current["m"]
                t2 = next_row["h"] * 60 + next_row["m"]
                diff = abs(t2 - t1)

                if is_mixed_pair and same_line and diff < 4:
                    current["type"] = "NORMAL"
                    merged_mon_fri.append(current)
                    skip_indices.add(i + 1)
                    continue

            merged_mon_fri.append(current)

        raw_rows = merged_mon_fri + other_rows

        # -----------------------------
        # LEGEND GENERATION
        # -----------------------------
        legend_html = '<div style="margin-top:20px; font-size: 1.4em; color: #333; line-height: 1.5;">'
        if mon_fri_patterns:
            days_fi = ["maanantaisin", "tiistaisin", "keskiviikkoisin", "torstaisin", "perjantaisin"]
            days_en = ["on Mondays", "on Tuesdays", "on Wednesdays", "on Thursdays", "on Fridays"]
            sorted_pats = sorted(mon_fri_patterns.items(), key=lambda x: x[1])
            
            for pat, fid in sorted_pats:
                idxs = [i for i, x in enumerate(pat) if x]
                
                selected_fi = [days_fi[i] for i in idxs]
                selected_en = [days_en[i] for i in idxs]
                
                if len(selected_fi) > 1:
                    fi_str = (", ".join(selected_fi[:-1]) + " ja " + selected_fi[-1]).capitalize()
                    en_str = (", ".join(selected_en[:-1]) + " and " + selected_en[-1])
                else:
                    fi_str = selected_fi[0].capitalize()
                    en_str = selected_en[0]

                legend_html += f'<div><strong>{fid})</strong> {fi_str} / <span class="en">{en_str}</span></div>'

        legend_html += '<div style="margin-top: 10px; display: flex; gap: 15px; flex-wrap: wrap; align-items: center;">'

        badge_style_base = "display: inline-block; padding: 2px 6px; border-radius: 4px; border: 1px solid transparent; font-weight: bold; margin-right: 5px;"

        style_normal = badge_style_base + "background-color: #FFFFFF; border-color: #000000; color: #000000;"
        
        legend_html += (
            f'<div>'
            'Mustalla olevat vuorot ajetaan koulupäivinä sekä koulujen lomapäivinä / <span class="en">Departures colored in black are operated on school days and school holidays</span>'
            "</div>"
        )

        if has_school_only_trips:
             style = badge_style_base + "background-color: #BBDEFB; border-color: #90CAF9; color: #0D47A1;"
             legend_html += (
                f'<div><span style="{style}">&nbsp;</span> = '
                'Vain koulupäivinä / <span class="en">On school days</span>'
                "</div>"
            )
        if has_holiday_only_trips:
            style = badge_style_base + "background-color: #FFCC80; border-color: #FFB74D; color: #CC4700;"
            legend_html += (
                f'<div><span style="{style}">&nbsp;</span> = '
                'Vain koulujen lomapäivinä / <span class="en">Only on school holidays</span>'
                "</div>"
            )
        
        legend_html += "</div>"
        legend_html += '<div style="margin-top: 5px;">Arkipyhinä ajetaan sunnuntain vuorot. / <span class="en">On public holidays, Sunday services are operated.</span></div>'
        legend_html += "</div>"

        final_html_map = {}
        total_rows_count = 0

        clarification_header = """
        <div class="sc-clarification" style="display: flex; align-items: flex-start;">
            <div class="sc-c-item" style="width: 3.5em; flex-shrink: 0; display: flex; flex-direction: column;">
                <div style="color: black; font-weight: bold; font-size: 1.4em;">Tunti</div>
                <div class="en" style="font-size: 1.12em; font-weight: normal; color: black; font-style: italic;">Hour</div>
            </div>
            <div class="sc-c-item" style="padding-left: 10px; display: flex; flex-direction: column;">
                <div style="font-size: 1.4em; color: black; font-weight: bold;">min / linja</div>
                <div class="en" style="font-size: 1.12em; font-weight: normal; color: black; font-style: italic;">min / route</div>
            </div>
        </div>
        """

        for bucket in ["Mon-Fri", "Sat", "Sun"]:
            entries = [r for r in raw_rows if r["bucket"] == bucket]
            if not entries:
                final_html_map[bucket] = ""
                continue

            entries.sort(key=lambda x: (x["h"], x["m"]))
            hours_map = {}
            for e in entries:
                note = f"<sup>{e['footnote']})</sup>" if e["footnote"] else ""

                base_style = "display: inline-block; padding: 2px 6px; border-radius: 4px; margin: 0 2px; border: 1px solid transparent;"
                text_color = "black"
                
                if e["type"] == "SCHOOL":
                    style_str = base_style + "background-color: #F0F8FF; border-color: #BBDEFB; color: #0D47A1;"
                    text_color = "#0D47A1"
                elif e["type"] == "HOLIDAY":
                    style_str = base_style + "background-color: #FFF3E0; border-color: #FFE0B2; color: #CC4700;"
                    text_color = "#CC4700"
                else:
                    style_str = base_style + "color: black;"
                    text_color = "black"

                val = (
                    f"<div class='time-group' style='{style_str}'>"
                    f"<b style='color:{text_color}'>{e['m']:02d}</b>{note}"
                    f"<span class='s-line' style='font-weight:normal; color:{text_color}; opacity: 0.8;'>/{e['line']}</span>"
                    f"</div>"
                )
                hours_map.setdefault(e["h"], []).append(val)

            srt_hours = sorted(hours_map.keys())
            html_chunk = clarification_header
            i = 0
            row_counter = 0
            while i < len(srt_hours):
                ch = srt_hours[i]
                cm = "".join(hours_map[ch])
                eh, j = ch, i + 1
                while j < len(srt_hours):
                    nh = srt_hours[j]
                    nm = "".join(hours_map[nh])
                    if nh == eh + 1 and nm == cm:
                        eh = nh
                        j += 1
                    else:
                        break

                disp_ch = ch if ch < 24 else ch - 24
                disp_eh = eh if eh < 24 else eh - 24
                label = f"{disp_ch:02d}"
                if eh > ch:
                    label += f"&ndash;{disp_eh:02d}"

                bg_color = "#f2f2f2" if row_counter % 2 == 0 else "white"
                html_chunk += (
                    f'<div class="sc-row" style="background-color: {bg_color};">'
                    f'<div class="sc-h">{label}</div>'
                    f'<div class="sc-m" style="grid-template-columns: repeat(auto-fill, minmax(4.5em, 1fr)); gap: 5px {schedule_col_gap};">{cm}</div>'
                    f"</div>"
                )
                total_rows_count += 1
                row_counter += 1
                i = j

            final_html_map[bucket] = html_chunk

        return final_html_map, legend_html, total_rows_count

    # ----------------------------
    # TREE HELPERS
    # ----------------------------
    def _build_route_tree(self, start_stop_id, active_trips_df):
        st = self.data["stop_times"].copy()
        if st.empty or active_trips_df.empty:
            return None
        st["stop_sequence"] = st["stop_sequence"].astype(int)

        merged_all = active_trips_df.merge(st, on="trip_id").merge(self.data["routes"], on="route_id")
        
        # --- FILTER ALLOWED LINES (Tree) ---
        merged_all = merged_all[~merged_all.apply(lambda x: self._is_excluded_line(x["route_short_name"], x.get("trip_headsign", "")), axis=1)]

        if merged_all.empty:
            return None

        pattern_counts = (
            merged_all.groupby(["route_short_name", "direction_id"]).size().reset_index(name="departure_count")
        )
        pattern_counts = pattern_counts.sort_values("departure_count", ascending=False).head(5)

        visits = st[st["stop_id"] == str(start_stop_id)]
        merged = visits.merge(self.data["trips"], on="trip_id").merge(self.data["routes"], on="route_id")
        if merged.empty:
            return None

        patterns = merged.groupby(["route_short_name", "direction_id"]).first().reset_index()
        patterns = patterns.merge(pattern_counts, on=["route_short_name", "direction_id"], how="inner")
        if patterns.empty:
            return None

        processed = []

        for _, row in patterns.iterrows():
            trip_id = row["trip_id"]
            start_seq = int(row["stop_sequence"])
            line = str(row["route_short_name"])
            
            # Skip P-lines
            if line.strip().upper().startswith("P"):
                continue

            weight = int(row.get("departure_count", 1))

            ft = st[st["trip_id"] == trip_id].sort_values(by="stop_sequence")
            future = ft[ft["stop_sequence"] > start_seq].copy()
            
            # --- UPDATED: Exclude if zero or only one stop left (terminal) ---
            if len(future) < 2:
                continue
            # -------------------------------------------------------------

            # --- UPDATED LOGIC: Sequence based slicing ---
            # 1. Identify intermediate stops (exclude last)
            intermediate_stops = future.iloc[:-1]
            # 2. Take top 10 next stops
            next_10_stops = intermediate_stops.head(10)
            # 3. Add the terminal (last stop)
            last_stop_row = future.iloc[[-1]]
            
            selected_rows = pd.concat([next_10_stops, last_stop_row]).sort_values("stop_sequence")

            s_list = []
            for _, r in selected_rows.iterrows():
                info = self.get_stop_info(r["stop_id"])
                raw_name = info[0]
                clean_name = self._clean_stop_name(raw_name)
                if "Kantasatama" in clean_name:
                    clean_name = "Kantasatama"
                s_list.append({"id": clean_name, "name": clean_name})

            processed.append({"lines": [line], "path": s_list, "weight": weight})

        root = {"id": "ROOT", "children": {}, "lines": set(), "weight": 0}
        for p in processed:
            curr = root
            ls, w = p["lines"], p["weight"]
            for stop in p["path"]:
                sid = stop["id"]
                if sid not in curr["children"]:
                    curr["children"][sid] = {
                        "id": sid,
                        "name": stop["name"],
                        "children": {},
                        "lines": set(),
                        "is_gap": False,
                        "weight": 0,
                    }
                child = curr["children"][sid]
                child["lines"].update(ls)
                child["weight"] += w
                curr = child

        self._prune_and_post_process_tree(root)
        self._balance_tree_nodes(root)
        return root

    def _prune_and_post_process_tree(self, node):
        continuing_lines = set()
        for child in node["children"].values():
            continuing_lines.update(child["lines"])
            self._prune_and_post_process_tree(child)
        terminating_lines = node["lines"] - continuing_lines
        if terminating_lines:
            if node["children"]:
                term_id = node["id"] + "_TERM"
                virtual_child = {
                    "id": term_id,
                    "name": node.get("name", node["id"]),
                    "children": {},
                    "lines": terminating_lines,
                    "is_gap": False,
                    "is_terminal": True,
                    "weight": 0,
                }
                node["children"][term_id] = virtual_child
            else:
                node["is_terminal"] = True

    def _balance_tree_nodes(self, node):
        if not node["children"]:
            return
        for child in node["children"].values():
            self._balance_tree_nodes(child)

    def _get_max_depth(self, node):
        if not node["children"]:
            return 0
        return 1 + max((self._get_max_depth(c) for c in node["children"].values()), default=0)

    def _get_tree_sort_key(self, node):
        def n_sort(s):
            return [int(t) if t.isdigit() else t.lower() for t in re.split("([0-9]+)", str(s))]

        if not node.get("lines"):
            return [999999]
        sorted_lines = sorted(list(node["lines"]), key=n_sort)
        return n_sort(sorted_lines[0])

    def _layout_tree(self, node, y, leaf_counter, cfg):
        step = cfg["y_step"]
        if node.get("is_terminal"):
            node["y"] = cfg["term_y"]
            node["is_end"] = True
        else:
            node["y"] = y + step

        children = list(node["children"].values())
        children.sort(key=self._get_tree_sort_key)

        if not children:
            w = cfg["col_w"]
            node["x"] = cfg["margin_left"] + (leaf_counter[0] * w)
            leaf_counter[0] += 1
            node["is_terminal_leaf"] = True
            return node["x"]

        xs = [self._layout_tree(c, node["y"], leaf_counter, cfg) for c in children]
        node["x"] = sum(xs) / len(xs)
        return node["x"]

    def _assign_text_positions(self, node, is_leftmost=False, is_rightmost=False, sibling_count=0):
        anchor = "start"
        if is_leftmost:
            anchor = "end"
            if sibling_count >= 3:
                anchor = "start"
        if is_rightmost:
            anchor = "start"

        node["text_anchor"] = anchor
        children = list(node["children"].values())
        children.sort(key=self._get_tree_sort_key)
        cnt = len(children)
        for i, c in enumerate(children):
            self._assign_text_positions(c, i == 0, i == cnt - 1, cnt)

    def _resolve_overlaps(self, node, font_px, line_h_px, text_x_offset_px):
        visible_nodes = []

        def collect(n):
            if n["id"] != "ROOT" and not n.get("is_gap"):
                visible_nodes.append(n)
            for c in n["children"].values():
                collect(c)

        collect(node)
        
        # Guard against empty trees
        if not visible_nodes:
            return False

        char_w = font_px * 0.55

        def get_bbox(n):
            x, y = n["x"], n["y"]
            anchor = n.get("text_anchor", "start")
            raw_name = str(n.get("name", n["id"]))
            clean_name = re.sub(r"(?i)\bpäätepysäkki\b", "", raw_name).strip()

            words = clean_name.split()
            lines = []
            curr, cl = [], 0
            for w in words:
                if cl + len(w) > 18:
                    lines.append(" ".join(curr))
                    curr = [w]
                    cl = len(w)
                else:
                    curr.append(w)
                    cl += len(w) + 1
            if curr:
                lines.append(" ".join(curr))

            max_len = max([len(l) for l in lines]) if lines else 0
            text_w = max_len * char_w
            text_h = len(lines) * line_h_px
            top_y = y - ((len(lines) - 1) * line_h_px / 2) - 10
            bottom_y = top_y + text_h + 10

            if anchor == "start":
                left_x = x + text_x_offset_px
                right_x = left_x + text_w
            else:
                right_x = x - text_x_offset_px
                left_x = right_x - text_w
            return (left_x, top_y, right_x, bottom_y)

        def collides(b1, b2):
            return not (b1[2] < b2[0] or b1[0] > b2[2] or b1[3] < b2[1] or b1[1] > b2[3])

        # 1. Standard overlap resolution pass
        for i in range(len(visible_nodes)):
            for j in range(i + 1, len(visible_nodes)):
                n1, n2 = visible_nodes[i], visible_nodes[j]
                if abs(n1["y"] - n2["y"]) > (line_h_px * 3):
                    continue
                b1, b2 = get_bbox(n1), get_bbox(n2)
                if collides(b1, b2):
                    orig_anchor = n1.get("text_anchor", "start")
                    n1["text_anchor"] = "end" if orig_anchor == "start" else "start"
                    if collides(get_bbox(n1), b2):
                        n1["text_anchor"] = orig_anchor
                        orig_anchor2 = n2.get("text_anchor", "start")
                        n2["text_anchor"] = "end" if orig_anchor2 == "start" else "start"
                        if collides(b1, get_bbox(n2)):
                            n2["text_anchor"] = orig_anchor2

        # 2. NEW LOGIC: Align leftmost column (70% rule)
        min_x = min(n["x"] for n in visible_nodes)
        leftmost_nodes = [n for n in visible_nodes if abs(n["x"] - min_x) < 5.0]
        
        if leftmost_nodes:
            start_count = sum(1 for n in leftmost_nodes if n.get("text_anchor", "start") == "start")
            ratio = start_count / len(leftmost_nodes)
            
            if ratio >= 0.70:
                for n in leftmost_nodes:
                    n["text_anchor"] = "start"

        # 3. Final collision check (returns True if overlap remains)
        for i in range(len(visible_nodes)):
            for j in range(i + 1, len(visible_nodes)):
                b1, b2 = get_bbox(visible_nodes[i]), get_bbox(visible_nodes[j])
                if collides(b1, b2):
                    return True
                    
        return False

    def _get_tree_bounds(self, node, bounds):
        x, y = node.get("x", 0), node.get("y", 0)
        bounds["min_x"] = min(bounds["min_x"], x)
        bounds["max_x"] = max(bounds["max_x"], x)
        bounds["min_y"] = min(bounds["min_y"], y)
        bounds["max_y"] = max(bounds["max_y"], y)
        for c in node["children"].values():
            self._get_tree_bounds(c, bounds)

    def _clamp_tree_viewbox(self, vb_x, vb_y, vb_w, vb_h, min_w, min_h):
        if vb_w >= min_w and vb_h >= min_h:
            return vb_x, vb_y, vb_w, vb_h

        cx = vb_x + vb_w / 2
        cy = vb_y + vb_h / 2
        vb_w2 = max(vb_w, min_w)
        vb_h2 = max(vb_h, min_h)
        vb_x2 = cx - vb_w2 / 2
        vb_y2 = cy - vb_h2 / 2
        return vb_x2, vb_y2, vb_w2, vb_h2

    def _svg_tree(self, root, cfg, font_scale=1.0):
        elems = []
        first = list(root["children"].values())
        first.sort(key=self._get_tree_sort_key)
        if not first:
            return ""

        sx = sum(n["x"] for n in first) / len(first)
        sy = cfg["margin_top"]

        route_start_y = sy + (120 * font_scale)
        pin_center_y = sy + (30 * font_scale)

        r_main = 20 * font_scale
        r_outer = 35 * font_scale
        r_inner = 12 * font_scale
        stroke_main = 8 * font_scale
        stroke_path = 5 * font_scale
        stroke_circ = 4 * font_scale

        f_main = 80 * font_scale
        f_sub = 45 * font_scale

        f_node = 90 * font_scale
        
        line_h = 85 * font_scale
        text_x_offset = 60 * font_scale

        bounds = {"min_x": float("inf"), "max_x": float("-inf"), "min_y": float("inf"), "max_y": float("-inf")}
        for c in first:
            self._get_tree_bounds(c, bounds)
        bounds["min_x"] = min(bounds["min_x"], sx)
        bounds["max_x"] = max(bounds["max_x"], sx)
        bounds["min_y"] = min(bounds["min_y"], pin_center_y - (120 * font_scale))

        max_text_char_count = 18
        estimated_text_width = max_text_char_count * f_node * 0.55
        
        bounds["min_x"] -= (estimated_text_width * 0.2) 
        bounds["max_x"] += (estimated_text_width * 1.1)

        pad = 40 * font_scale
        bottom_gap = 1 * font_scale
        vb_x, vb_y = bounds["min_x"] - pad, bounds["min_y"] - pad
        vb_w = (bounds["max_x"] - bounds["min_x"]) + 2 * pad
        vb_h = (bounds["max_y"] - bounds["min_y"]) + 2 * pad + bottom_gap

        vb_x, vb_y, vb_w, vb_h = self._clamp_tree_viewbox(
            vb_x, vb_y, vb_w, vb_h,
            min_w=self.config["tree_min_viewbox_w"],
            min_h=self.config["tree_min_viewbox_h"],
        )
        self.tree_viewbox = f"{vb_x} {vb_y} {vb_w} {vb_h}"

        def draw_paths(node, px, py):
            x, y = node["x"], node["y"]
            branch_y = py + (120 * font_scale)

            dist = y - py
            dash_attr = ""
            if node.get("is_end"):
                dash_attr = 'stroke-dasharray="15,15"'
            elif dist > (cfg["y_step"] * 1.5):
                dash_attr = 'stroke-dasharray="25,15"'

            if abs(x - px) < 2:
                path = f"M {px},{py} L {x},{y}"
            else:
                path = f"M {px},{py} L {px},{branch_y} L {x},{branch_y} L {x},{y}"

            if node["id"] != "ROOT":
                elems.append(
                    f'<path d="{path}" fill="none" stroke="black" stroke-width="{stroke_path}" {dash_attr}/>'
                )

            children = list(node["children"].values())
            children.sort(key=self._get_tree_sort_key)
            for c in children:
                draw_paths(c, x, y)

        draw_paths(root, sx, route_start_y)

        p_cx, p_cy = sx, pin_center_y
        line_start_y = p_cy + r_main
        line_end_y = route_start_y
        elems.append(f'<path d="M {p_cx},{line_start_y} L {p_cx},{line_end_y}" stroke="#b00030" stroke-width="{stroke_main}"/>')
        elems.append(f'<circle cx="{p_cx}" cy="{p_cy}" r="{r_main}" fill="#b00030"/>')
        head_cy = p_cy - (35 * font_scale)
        elems.append(f'<circle cx="{p_cx}" cy="{head_cy}" r="{r_outer}" fill="#b00030"/>')
        elems.append(f'<circle cx="{p_cx}" cy="{head_cy}" r="{r_inner}" fill="white"/>')

        elems.append(
            f'<text x="{p_cx + (50*font_scale)}" y="{head_cy - (10*font_scale)}" font-family="Arial" font-size="{f_main}" font-weight="bold">Olet tässä</text>'
        )
        elems.append(
            f'<text x="{p_cx + (50*font_scale)}" y="{head_cy + (35*font_scale)}" font-family="Arial" font-size="{f_sub}" fill="#444">You are here</text>'
        )

        def wrap_name(name):
            clean_name = re.sub(r"(?i)\bpäätepysäkki\b", "", str(name)).strip()
            words = clean_name.split()
            lines = []
            curr, cl = [], 0
            for w in words:
                if cl + len(w) > 18:
                    if curr:
                        lines.append(" ".join(curr))
                    curr = [w]
                    cl = len(w)
                else:
                    curr.append(w)
                    cl += len(w) + 1
            if curr:
                lines.append(" ".join(curr))
            return lines

        def draw_nodes(node):
            x, y = node["x"], node["y"]
            anchor = node.get("text_anchor", "start")
            x_off = text_x_offset if anchor == "start" else -text_x_offset

            if not node.get("is_gap") and node["id"] != "ROOT":
                is_terminal = node.get("is_end")
                rr = (18 if is_terminal else 12) * font_scale
                elems.append(f'<circle cx="{x}" cy="{y}" r="{rr}" fill="white" stroke="black" stroke-width="{stroke_circ}"/>')

                name_lines = wrap_name(node.get("name", node["id"]))

                if is_terminal:
                    t_x_off = 40 * font_scale
                    t_y = y + (20 * font_scale)
                    for ln in name_lines:
                        elems.append(
                            f'<text x="{x + t_x_off}" y="{t_y}" text-anchor="start" font-family="Arial" font-size="{f_node}" font-weight="normal">{ln}</text>'
                        )
                        t_y += (line_h * 1.0)

                    def ns(s): return [int(t) if t.isdigit() else t.lower() for t in re.split("([0-9]+)", str(s))]
                    lns = sorted(list(node.get("lines", [])), key=ns)
                    if lns:
                        r1 = " | ".join(lns)
                        elems.append(
                            f'<text x="{x + t_x_off}" y="{t_y + (25*font_scale)}" text-anchor="start" font-family="Arial" font-size="{f_node}" font-weight="bold">{r1}</text>'
                        )
                else:
                    num_lines = len(name_lines)
                    baseline_nudge = 10 * font_scale
                    start_text_y = y - ((num_lines - 1) * line_h / 2) + baseline_nudge
                    text_y = start_text_y
                    for ln in name_lines:
                        elems.append(
                            f'<text x="{x + x_off}" y="{text_y}" text-anchor="{anchor}" font-family="Arial" font-size="{f_node}" font-weight="normal">{ln}</text>'
                        )
                        text_y += line_h

            children = list(node["children"].values())
            children.sort(key=self._get_tree_sort_key)
            for c in children:
                draw_nodes(c)

        draw_nodes(root)
        return "".join(elems)

    # ----------------------------
    # POSTER GENERATION
    # ----------------------------
    def generate_poster(self, stop_id, date_label, output_file, school_week_start, holiday_week_start, city_name):
        stop_name, stop_code, stop_zone = self.get_stop_info(stop_id)
        
        self.config["color"] = "#3069b3"

        if stop_zone == "B":
            schedule_col_gap = "25px" 
        else:
            schedule_col_gap = "10px"
        
        logo_svg_inline = self._read_svg_candidates([self._find_file("logo.svg")])
        alareuna_svg_inline = self._read_svg_candidates([self._find_file("alareuna.svg")])

        try:
            sched_html_chunks, legend_html, _ = self.generate_schedule_html_data(stop_id, school_week_start, holiday_week_start)

            grid_cols_css = "60fr 40fr"
            total_w_mm = self.trim_w_mm
            right_col_w_mm = total_w_mm * 0.45
            map_w_mm = int(right_col_w_mm - 60)
            map_h_mm = 350

            # Uses the provided school week date formatted as YYYY-MM-DD for the map
            map_svg_content = self._generate_map_svg(stop_id, map_w_mm, map_h_mm, school_week_start.strftime("%Y-%m-%d"))
            school_trips = self._get_active_trips_for_week(stop_id, school_week_start, school_week_start + timedelta(days=6))
            root_tree = self._build_route_tree(stop_id, school_trips)

            tree_svg_content = ""
            self.tree_viewbox = "0 0 1000 1000"
            if root_tree:
                max_depth = self._get_max_depth(root_tree)
                y_step = 280
                top_margin = 180
                term_y = top_margin + (max_depth * y_step) + 480

                current_col_w = 800
                font_scale = 1.0

                for _ in range(7):
                    tree_cfg = {
                        "margin_top": top_margin,
                        "margin_left": 0,
                        "col_w": current_col_w,
                        "y_step": y_step,
                        "gap_step": y_step,
                        "term_y": term_y,
                    }
                    self._layout_tree(root_tree, top_margin, [0], tree_cfg)
                    self._assign_text_positions(root_tree)

                    overlaps = self._resolve_overlaps(
                        root_tree,
                        font_px=90 * font_scale,
                        line_h_px=75 * font_scale,
                        text_x_offset_px=60 * font_scale,
                    )

                    if not overlaps:
                        break
                    current_col_w *= 1.18
                    if current_col_w > 1400:
                        font_scale *= 0.93

                tree_svg_content = self._svg_tree(root_tree, tree_cfg, font_scale=font_scale)
            else:
                tree_svg_content = "<text x='50%' y='50%' font-size='50'>No routes</text>"

            display_code = stop_code if (stop_code and stop_code != "???") else str(stop_id)

            line_data = self.generate_line_bar_data(school_trips)
            
            bus_icon_svg = f'''<svg class="bus-icon" viewBox="0 0 24 24"><path fill="{self.config['color']}" d="M4 16c0 .88.39 1.67 1 2.22V20c0 .55.45 1 1 1h1c.55 0 1-.45 1-1v-1h8v1c0 .55.45 1 1 1h1c.55 0 1-.45 1-1v-1.78c.61-.55 1-1.34 1-2.22V6c0-3.5-3.58-4-8-4s-8 .5-8 4v10zm3.5 1c-.83 0-1.5-.67-1.5-1.5S6.67 14 7.5 14s1.5.67 1.5 1.5S8.33 17 7.5 17zm9 0c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5zm1.5-6H6V6h12v5z"/></svg>'''

            line_bar_items = []
            for item in line_data:
                line_bar_items.append(
                    f'<div class="lb-item">{bus_icon_svg}<span class="lb-num" style="color:black;">{item["num"]}</span><span class="lb-dest">{item["dest"]}</span></div>'
                )
            line_bar_html = "".join(line_bar_items)

            def build_sched_html(key, fi, en):
                content = sched_html_chunks.get(key, "")
                if not content:
                    return ""
                return f'<div class="sc-block"><div class="sc-title" style="color: black;">{fi} <span class="en" style="color: black;">{en}</span></div><div class="sc-grid">{content}</div></div>'

            sched_html = build_sched_html("Mon-Fri", "Maanantai–perjantai", "Monday–Friday")
            sched_html += build_sched_html("Sat", "Lauantai", "Saturday")
            sched_html += build_sched_html("Sun", "Sunnuntai", "Sunday")
            sched_html += legend_html

            # --- DYNAMIC QR CODE URL ---
            city_subdomain = city_name.lower()
            city_prefix = city_name.capitalize()
            schedule_url = f"https://{city_subdomain}.digitransit.fi/pysakit/{city_prefix}:{stop_id}"
            # ---------------------------
            
            encoded_url = urllib.parse.quote(schedule_url)
            qr_img_url = f"https://api.qrserver.com/v1/create-qr-code/?size=1000x1000&color=000000&bgcolor=FFFFFF&data={encoded_url}"

            w_mm, h_mm = self.page_w_mm, self.page_h_mm
            bleed = self.bleed_mm
            crop_lines = f"""
                <line x1="0" y1="{bleed}" x2="10" y2="{bleed}" stroke="black" stroke-width="0.5" />
                <line x1="{bleed}" y1="0" x2="{bleed}" y2="10" stroke="black" stroke-width="0.5" />

                <line x1="{w_mm-10}" y1="{bleed}" x2="{w_mm}" y2="{bleed}" stroke="black" stroke-width="0.5" />
                <line x1="{w_mm-bleed}" y1="0" x2="{w_mm-bleed}" y2="10" stroke="black" stroke-width="0.5" />

                <line x1="0" y1="{h_mm-bleed}" x2="10" y2="{h_mm-bleed}" stroke="black" stroke-width="0.5" />
                <line x1="{bleed}" y1="{h_mm-10}" x2="{bleed}" y2="{h_mm}" stroke="black" stroke-width="0.5" />

                <line x1="{w_mm-10}" y1="{h_mm-bleed}" x2="{w_mm}" y2="{h_mm-bleed}" stroke="black" stroke-width="0.5" />
                <line x1="{w_mm-bleed}" y1="{h_mm-10}" x2="{w_mm-bleed}" y2="{h_mm}" stroke="black" stroke-width="0.5" />
            """
            
            stop_number_html = ""
            if stop_zone != "B":
                stop_number_html = f"""
                <div class="h-info-group">
                    <div class="h-label" style="color: white;">Pysäkkinumero <span class="en" style="color: white;">| Stop number</span></div>
                    <div class="h-value">{display_code}</div>
                </div>
                """

            html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
    @page {{
        size: {self.page_w_mm}mm {self.page_h_mm}mm;
        margin: 0;
    }}

    * {{
        box-sizing: border-box;
    }}

    html, body {{
        width: {self.page_w_mm}mm;
        height: {self.page_h_mm}mm;
        margin: 0;
        padding: 0;
        overflow: hidden;
        font-family: Arial, sans-serif;
        background-color: {self.config['color']};
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
    }}

    @media print {{
        html, body {{
            width: {self.page_w_mm}mm !important;
            height: {self.page_h_mm}mm !important;
            overflow: hidden !important;
        }}
    }}

    .crop-layer {{
        position: fixed;
        top: 0;
        left: 0;
        width: {self.page_w_mm}mm;
        height: {self.page_h_mm}mm;
        pointer-events: none;
        z-index: 9999;
    }}
    .crop-layer svg {{
        display: block;
        width: {self.page_w_mm}mm;
        height: {self.page_h_mm}mm;
    }}

    .poster-container {{
        position: fixed;
        top: {self.bleed_mm}mm;
        left: {self.bleed_mm}mm;
        width: {self.trim_w_mm}mm;
        height: {self.trim_h_mm}mm;

        display: grid;
        grid-template-columns: 60fr 40fr;
        grid-template-rows: auto auto minmax(0, 1fr) 200mm;

        padding: {self.config['layout_gap_mm']}mm;
        gap: {self.config['layout_gap_mm']}mm;

        overflow: hidden;
        background: {self.config['color']};
    }}

    .en {{ font-style: italic; color: #444; }}

    .header {{
        grid-column: 1 / span 2;
        background-color: {self.config['color']};
        padding: 15mm 20mm 5mm 20mm;
        color: white;
        position: relative;
        display: flex;
        justify-content: space-between;
        align-items: baseline;
    }}
    .header-left {{ display: flex; flex-direction: column; }}
    .h-stop-name {{ font-size: 6em; font-weight: bold; color: white; line-height: 1; }}
    .h-date {{ font-size: 3em; margin-top: 5px; font-weight: normal; color: white; font-style: normal; }}

    .header-right {{
        display: flex;
        align-items: baseline;
        gap: 60px;
        text-align: center;
    }}
    .h-info-group {{ display: flex; flex-direction: column; align-items: center; justify-content: flex-start; }}
    .h-label {{ font-size: 1.5em; font-weight: normal; margin-bottom: 5px; opacity: 0.9; white-space: nowrap; }}
    .h-value {{ font-size: 5em; font-weight: bold; line-height: 1; }}

    .line-bar-container {{ grid-column: 1 / span 2; width: 100%; padding: 0; margin: 0; }}
    .line-bar {{
        background: white;
        padding: 5mm 10mm;
        display: flex;
        flex-wrap: wrap;
        gap: 15px;
        align-items: center;
        border-radius: 20px;
        width: 100%;
        justify-content: flex-start;
    }}
    .lb-item {{ display: flex; align-items: center; margin-right: 25px; }}
    .bus-icon {{ width: 28px; height: 28px; margin-right: 10px; }}
    .lb-num {{ font-size: 2em; font-weight: bold; margin-right: 10px; }}
    .lb-dest {{ font-size: 1.2em; font-weight: 300; color: #000; text-transform: uppercase; }}

    .left-col {{
        grid-column: 1;
        grid-row: 3;
        background: white;
        border-radius: 30px;
        padding: 20mm 20mm 5mm 20mm;
        display: block;
        overflow: hidden;
        align-self: start;
        height: auto;
    }}

    .sc-title {{
        font-size: 3em;
        font-weight: bold;
        border-bottom: 4px solid black;
        padding-bottom: 10px;
        margin-bottom: 20px;
        margin-top: 20px;
        color: black;
    }}
    .sc-title .en {{ font-weight: normal; color: black; font-size: 0.7em; margin-left: 10px; }}

    .sc-clarification {{
        display: flex;
        align-items: baseline;
        margin-bottom: 10px;
        color: #666;
        font-size: 0.8em;
        border-bottom: 1px solid #ccc;
        padding-bottom: 5px;
    }}
    .sc-c-item {{ margin-right: 0px; }}
    .sc-c-item .en {{ font-size: 0.85em; color: #666; margin-left: 2px; }}

    .sc-row {{
        display: flex;
        border-bottom: 1px solid #eee;
        padding: 10px 20mm;
        font-size: 1.8em;
        margin-left: -20mm;
        margin-right: -20mm;
    }}
    .sc-h {{ width: 3.5em; font-weight: bold; white-space: nowrap; flex-shrink: 0; }}
    .sc-m {{
        flex: 1;
        display: grid;
    }}
    .time-group {{ white-space: nowrap; }}
    .s-line {{ vertical-align: baseline; margin-left: 2px; color: #444; font-size: 1.0em; }}

    .right-col {{
        grid-column: 2;
        grid-row: 3;
        display: flex;
        flex-direction: column;
        gap: {self.config['layout_gap_mm']}mm;
        overflow: hidden;
        align-self: start;
        height: auto;
        min-height: 0;
    }}

    .map-box {{
        height: {map_h_mm}mm;
        background-color: {self.config['map_bg_color']};
        border-radius: 30px;
        overflow: hidden;
        position: relative;
        box-shadow: 0 10px 30px rgba(0,0,0,0.1);
        flex-shrink: 0;
        width: 100%;
    }}
    .map-box svg {{ display: block; }}

    .tree-container {{
        background: white;
        border-radius: 30px;
        padding: 0mm;
        padding-top: 85px;
        padding-bottom: 0px;
        box-sizing: border-box;
        position: relative;
        overflow: hidden;
        margin: 0;
        width: 100%;
        height: {self.config['tree_box_h_mm']}mm;
        flex: none;
        min-height: 0;
    }}
    .tree-title {{
        position: absolute;
        top: 20px;
        left: 30px;
        font-size: 2.5em;
        font-weight: bold;
        z-index: 10;
        background: rgba(255,255,255,0.85);
        padding: 5px 10px;
        border-radius: 10px;
    }}
    .tree-title .en {{ font-weight: normal; color: #444; font-size: 0.8em; }}
    .tree-subtitle {{ font-size: 0.4em; font-weight: normal; margin-top: 5px; line-height: 1.2; color: #333; }}

    .tree-container svg {{
        width: 100%;
        height: 100%;
        display: block;
    }}

    .alareuna-row {{
        display: block;
        width: 100%;
        margin: 0;
        padding: 0;
        position: relative;
    }}
    .alareuna-row svg {{
        display: block;
        width: 100%;
        height: auto;
    }}

    .qr-group {{ 
        display: flex; 
        position: absolute;
        bottom: 30px;
        right: 20px;
        z-index: 50;
    }}
    .qr-box {{
        background-color: white;
        padding: 20px;
        border-radius: 30px;
        width: 240px;
        height: 240px;
    }}
    .qr-img {{ width: 100%; height: 100%; display: block; }}

    .footer {{
        grid-column: 2;
        grid-row: 4;
        display: flex;
        justify-content: flex-end; 
        align-items: flex-end;
        gap: 80px;
        margin-right: 20mm;
        margin-bottom: 20mm;
    }}
    .logo-box {{
        background-color: transparent; 
        padding: 20px;
        border-radius: 30px;
        display: flex;
        align-items: center;
        justify-content: center;
        height: 240px;
    }}
    .f-logo svg {{ width: 500px; height: auto; display: block; }}

</style>
</head>
<body>
    <div class="crop-layer">
        <svg viewBox="0 0 {self.page_w_mm} {self.page_h_mm}" xmlns="http://www.w3.org/2000/svg">
            {crop_lines}
        </svg>
    </div>

    <div class="poster-container">
        <div class="header">
            <div class="header-left">
                <div class="h-stop-name">{stop_name}</div>
                <div style="font-size: 1.5em; margin-bottom: 2px; margin-top: 15px; font-weight: normal; color: white;">
                    Aikataulut ovat voimassa | <span class="en" style="color: white;">Timetables valid</span>
                </div>
                <div class="h-date">{date_label}</div>
            </div>
            <div class="header-right">
                <div class="h-info-group">
                    <div class="h-label" style="color: white;">Vyöhyke <span class="en" style="color: white;">| Zone</span></div>
                    <div class="h-value">{stop_zone}</div>
                </div>
                {stop_number_html}
            </div>
        </div>

        <div class="line-bar-container">
            <div class="line-bar">{line_bar_html}</div>
        </div>

        <div class="left-col">
            <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 20px;">
                <div style="font-size: 4em; font-weight: bold; color: black;">
                    Pysäkkiaikataulu
                    <span class="en" style="font-weight: normal; font-size: 0.7em; color: black;">Stop timetable</span>
                </div>
                <div style="font-size: 1.2em; color: #333;">
                    Ajat ovat arvioaikoja | <span class="en">Times are estimates</span>
                </div>
            </div>
            {sched_html}
        </div>

        <div class="right-col">
            <div class="map-box">
                <svg width="100%" height="100%" viewBox="0 0 {map_w_mm} {map_h_mm}" preserveAspectRatio="xMidYMid slice">
                    {map_svg_content}
                </svg>
            </div>

            <div class="tree-container">
                <div class="tree-title">
                    Linjojen reitit <span class="en">Routes</span>
                    <div class="tree-subtitle">Listassa näkyvissä 10 seuraavaa pysäkkiä sekä päätepysäkki</div>
                </div>
                <svg viewBox="{self.tree_viewbox}" preserveAspectRatio="xMidYMin meet">
                    {tree_svg_content}
                </svg>
            </div>
            
            <div class="alareuna-row">
                {alareuna_svg_inline}
                <div class="qr-group">
                    <div class="qr-box"><img class="qr-img" src="{qr_img_url}"></div>
                </div>
            </div>
        </div>
        
        <div class="footer">
            <div class="logo-box">
                <div class="f-logo">
                    {logo_svg_inline}
                </div>
            </div>
        </div>
    </div>
</body>
</html>
"""

            with open(output_file, "w", encoding="utf-8") as f:
                f.write(html)

            print(f"✅ Generated HTML Poster: {os.path.abspath(output_file)}")
            pdf_filename = output_file.replace(".html", ".pdf")
            self.print_pdf_in_colab(output_file, pdf_filename)
            return pdf_filename

        except Exception as e:
            print(f"Error generating poster: {e}")
            import traceback
            traceback.print_exc()
            return None

    def print_pdf_in_colab(self, html_path, pdf_path):
        print("Converting HTML to PDF using Google Chrome...")
        try:
            cmd = [
                "google-chrome",
                "--headless",
                "--disable-gpu",
                "--no-sandbox",
                f"--print-to-pdf={pdf_path}",
                "--no-pdf-header-footer",
                "--virtual-time-budget=10000",
                html_path,
            ]
            subprocess.run(
                cmd, 
                check=True, 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL
            )
            print(f"✅ Generated PDF Poster: {os.path.abspath(pdf_path)}")
        except Exception as e:
            print(f"❌ PDF Conversion Failed: {e}")


if __name__ == "__main__":
    def find_file_main(filename):
        """Smart path resolver for Colab and local execution."""
        if not filename: return filename
        paths = [
            filename,
            f"/content/{filename}",
            os.path.join("assets", filename),
            os.path.join("/content/assets", filename),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        ]
        for p in paths:
            if os.path.exists(p):
                return p
        return filename

    print("--- File Setup ---")
    gtfs_input = input("Enter GTFS zip filename (default: 218.zip): ").strip() or "218.zip"
    routes_input = input("Enter Routes GPKG filename (default: rjuli.gpkg): ").strip() or "rjuli.gpkg"
    water_input = input("Enter Water GeoJSON filename (default: blue_areas_kotka_hamina_pyhtaa.geojson): ").strip() or "blue_areas_kotka_hamina_pyhtaa.geojson"

    gtfs_file = find_file_main(gtfs_input)
    routes_file = find_file_main(routes_input)
    water_file = find_file_main(water_input)

    if gtfs_file and os.path.exists(gtfs_file):
        print(f"Found GTFS file at: {gtfs_file}")
        gen = GTFSIntegratedPoster(gtfs_file, routes_file, water_file)
        
        print("\n--- Timetable Configuration ---")
        stop_ids_input = input("Enter stop numbers separated by comma (e.g., 155766): ").strip()
        
        if stop_ids_input:
            date_label = input("Enter printed date label (default: 10.8.2025–31.5.2026): ").strip() or "10.8.2025–31.5.2026"
            
            # --- NEW DATE AND CITY PROMPTS ---
            school_date_input = input("Enter a normal school week start date (YYYY-MM-DD) [default: 2025-12-08]: ").strip() or "2025-12-08"
            holiday_date_input = input("Enter a holiday week start date (YYYY-MM-DD) [default: 2025-10-20]: ").strip() or "2025-10-20"
            city_input = input("Enter the city name for the QR code (default: Kotka): ").strip() or "Kotka"
            
            try:
                school_week_start = datetime.strptime(school_date_input, "%Y-%m-%d")
                holiday_week_start = datetime.strptime(holiday_date_input, "%Y-%m-%d")
            except ValueError:
                print("❌ Invalid date format. Please use YYYY-MM-DD.")
                sys.exit(1)
            # ------------------------
            
            stop_ids = [s.strip() for s in stop_ids_input.split(",")]
            generated_pdfs = []
            
            for stop_id in stop_ids:
                if not stop_id: continue
                print(f"\n--- Processing stop {stop_id} ---")
                
                # Pass the dates and the city input into the generate_poster method
                pdf_file = gen.generate_poster(stop_id, date_label, f"{stop_id}.html", school_week_start, holiday_week_start, city_input)
                
                if pdf_file and os.path.exists(pdf_file):
                    generated_pdfs.append(pdf_file)
            
            if generated_pdfs:
                zip_filename = "posters.zip"
                with zipfile.ZipFile(zip_filename, "w") as zf:
                    for pdf in generated_pdfs:
                        zf.write(pdf, os.path.basename(pdf))
                print(f"\n📦 All posters zipped into: {zip_filename}")
                
                try:
                    from google.colab import files
                    import IPython
                    
                    ipython = IPython.get_ipython()
                    if ipython is not None and getattr(ipython, 'kernel', None) is not None:
                        print(f"Triggering download for {zip_filename}...")
                        files.download(zip_filename)
                    else:
                        print("Interactive auto-download skipped (running in script mode).")
                except ImportError:
                    print(f"Not running in Colab. Find '{zip_filename}' in your working directory.")
        else:
            print("No stop IDs provided.")
    else:
        print(f"GTFS zip '{gtfs_input}' not found. Please ensure it is uploaded or placed in the correct directory.")
