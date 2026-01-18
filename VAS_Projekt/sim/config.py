from dataclasses import dataclass

import yaml

@dataclass
class MapData:
    locations: dict
    roads: list
    base_edges: dict
    adjacency: dict


@dataclass
class Config:
    simulation: dict
    xmpp: dict
    map_data: MapData
    events: dict
    agents: dict


def _build_map(map_cfg):
    locations = {loc["name"]: {"x": loc["x"], "y": loc["y"]} for loc in map_cfg.get("locations", [])}
    roads = map_cfg.get("roads", [])
    base_edges = {}
    adjacency = {name: [] for name in locations}

    for road in roads:
        a = road["from"]
        b = road["to"]
        base_time = int(road["base_time"])
        bidirectional = road.get("bidirectional", True)

        base_edges[(a, b)] = base_time
        adjacency.setdefault(a, []).append(b)
        if bidirectional:
            base_edges[(b, a)] = base_time
            adjacency.setdefault(b, []).append(a)

    return MapData(
        locations=locations, roads=roads, base_edges=base_edges, adjacency=adjacency
    )


def load_config(path):
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    simulation = data.get("simulation", {})
    xmpp = data.get("xmpp", {})
    map_data = _build_map(data.get("map", {}))
    events = data.get("events", {})
    agents = data.get("agents", {})

    return Config(
        simulation=simulation, xmpp=xmpp, map_data=map_data, events=events, agents=agents
    )
