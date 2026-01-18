import asyncio
import logging

from sim.agents.center import AidCenterAgent
from sim.agents.group import AidGroupAgent
from sim.agents.vehicle import VehicleAgent
from sim.agents.world import WorldAgent
from sim.config import load_config
from sim.utils import resource_phrase


def _setup_logging(level):
    logging.basicConfig(level=getattr(logging, str(level).upper(), logging.INFO), format="%(message)s")
    for name in ("slixmpp", "spade", "spade.Agent", "spade.behaviour"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _require(mapping, key, kind):
    if key not in mapping:
        raise ValueError(f"Unknown {kind} id: {key}")
    return mapping[key]


async def main():
    config = load_config("config.yaml")
    _setup_logging(config.simulation.get("log_level", "INFO"))

    agents_cfg = config.agents
    world_cfg = agents_cfg.get("world", {})
    if not world_cfg:
        raise ValueError("Missing world agent config")

    centers_cfg = {c["id"]: c for c in agents_cfg.get("centers", [])}
    vehicles_cfg = {v["id"]: v for v in agents_cfg.get("vehicles", [])}
    groups_cfg = {g["id"]: g for g in agents_cfg.get("groups", [])}

    world = WorldAgent(world_cfg["jid"], world_cfg["password"], config)
    logger = logging.getLogger("sim")
    world_jid = world_cfg["jid"]
    max_ticks = int(config.simulation.get("max_ticks", 60))
    tick_seconds = int(config.simulation.get("tick_seconds", 1))
    logger.info(
        f"Simulation started (max_ticks={max_ticks}, tick_seconds={tick_seconds}). "
        f"Centers={len(centers_cfg)}, vehicles={len(vehicles_cfg)}, groups={len(groups_cfg)}."
    )
    for center in centers_cfg.values():
        vehicles_desc = " ".join(
            f"{vehicles_cfg[v]['id']}(cap={vehicles_cfg[v]['capacity']})"
            for v in center.get("vehicles", [])
            if v in vehicles_cfg
        ) or "-"
        logger.info(
            f"Aid center {center['id']} (at {center['location']}) starts with: "
            f"{resource_phrase(center.get('inventory', {}), include_zero=True)}. Vehicles: {vehicles_desc}."
        )
    for group in groups_cfg.values():
        logger.info(
            f"Group {group['id']} (at {group['location']}) is assigned to center {group['assigned_center']}. "
            f"Starting stock: {resource_phrase(group.get('stock', {}), include_zero=True)}. "
            f"Resupply threshold: {resource_phrase(group.get('min_threshold', {}), include_zero=True)}."
        )

    centers = [
        AidCenterAgent(
            c["jid"],
            c["password"],
            config,
            center_id=c["id"],
            location=c["location"],
            inventory=c.get("inventory", {}),
            world_jid=world_jid,
            vehicle_jids=[vehicles_cfg[v]["jid"] for v in c.get("vehicles", []) if v in vehicles_cfg],
            vehicle_capacities={
                vehicles_cfg[v]["jid"]: vehicles_cfg[v]["capacity"] for v in c.get("vehicles", []) if v in vehicles_cfg
            },
        )
        for c in centers_cfg.values()
    ]
    vehicles = [
        VehicleAgent(
            v["jid"],
            v["password"],
            config,
            vehicle_id=v["id"],
            home_location=v["home"],
            home_center_jid=_require(centers_cfg, v["home_center"], "center")["jid"],
            capacity=v["capacity"],
            world_jid=world_jid,
            base_edges=config.map_data.base_edges,
            adjacency=config.map_data.adjacency,
        )
        for v in vehicles_cfg.values()
    ]
    groups = [
        AidGroupAgent(
            g["jid"],
            g["password"],
            config,
            group_id=g["id"],
            location=g["location"],
            assigned_center_jid=_require(centers_cfg, g["assigned_center"], "center")["jid"],
            stock=g.get("stock", {}),
            min_threshold=g.get("min_threshold", {}),
            max_capacity=g.get("max_capacity", {}),
            consumption_per_tick=g.get("consumption_per_tick", {}),
            world_jid=world_jid,
        )
        for g in groups_cfg.values()
    ]

    all_agents = [world] + centers + vehicles + groups
    await world.start()
    await asyncio.gather(*(agent.start() for agent in centers + vehicles + groups))

    await asyncio.sleep(max_ticks * tick_seconds + 2)

    for agent in all_agents:
        is_alive = getattr(agent, "is_alive", None)
        if callable(is_alive) and not agent.is_alive():
            continue
        await agent.stop()

    await asyncio.sleep(1)
    logger.info("Simulation finished.")


if __name__ == "__main__":
    asyncio.run(main())
