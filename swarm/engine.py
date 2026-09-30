"""Discrete warehouse simulator with baseline and peer-style coordination modes."""

from __future__ import annotations

import heapq
import itertools
import random
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field

Point = tuple[int, int]
WIDTH, HEIGHT = 18, 12
STAGING: Point = (8, 10)
WALLS: set[Point] = {
    *((x, 3) for x in range(2, 16) if x not in (5, 11)),
    *((x, 7) for x in range(1, 17) if x not in (3, 8, 14)),
    (5, 4), (5, 5), (5, 6), (11, 4), (11, 5), (11, 6),
    (13, 8), (13, 9), (13, 10),
}


@dataclass
class Task:
    id: str
    pickup: Point
    destination: Point
    status: str = "queued"
    owner: str | None = None
    staged: bool = False


@dataclass
class Robot:
    id: str
    pos: Point
    battery: int = 100
    task_id: str | None = None
    loaded: bool = False
    route: list[Point] = field(default_factory=list)
    state: str = "idle"
    wait_ticks: int = 0
    completed: int = 0


def astar(start: Point, goal: Point, blocked: set[Point]) -> list[Point] | None:
    if start == goal:
        return []
    serial = itertools.count()
    frontier: list[tuple[int, int, Point]] = [(0, next(serial), start)]
    came_from: dict[Point, Point | None] = {start: None}
    cost = {start: 0}
    while frontier:
        _, _, current = heapq.heappop(frontier)
        if current == goal:
            path: list[Point] = []
            while came_from[current] is not None:
                path.append(current)
                current = came_from[current]  # type: ignore[assignment]
            return list(reversed(path))
        for nxt in ((current[0] + 1, current[1]), (current[0] - 1, current[1]),
                    (current[0], current[1] + 1), (current[0], current[1] - 1)):
            if not (0 <= nxt[0] < WIDTH and 0 <= nxt[1] < HEIGHT) or nxt in blocked:
                continue
            new_cost = cost[current] + 1
            if new_cost < cost.get(nxt, 10**9):
                cost[nxt] = new_cost
                came_from[nxt] = current
                heuristic = abs(nxt[0] - goal[0]) + abs(nxt[1] - goal[1])
                heapq.heappush(frontier, (new_cost + heuristic, next(serial), nxt))
    return None


class Simulator:
    """All decisions are computed by robot-local rules; this object advances simulated time."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.events: deque[dict] = deque(maxlen=100)
        self.reset()

    def reset(self) -> None:
        with getattr(self, "lock", threading.RLock()):
            self.mode = "swarm"
            self.running = False
            self.tick_count = 0
            self.collisions = 0
            self.deadlocks = 0
            self.stalled_ticks = 0
            self.deadlock_active = False
            self.conflicts_resolved = 0
            self.blocked: set[Point] = set(WALLS)
            self.robots = [Robot("R1", (1, 1)), Robot("R2", (16, 1)), Robot("R3", (1, 10))]
            self.tasks = [
                Task("T1", (2, 1), (15, 10)), Task("T2", (15, 1), (2, 10)),
                Task("T3", (1, 9), (16, 9)), Task("T4", (16, 10), (1, 2)),
                Task("T5", (9, 1), (9, 10)), Task("T6", (2, 8), (15, 2)),
            ]
            self.started_at = time.monotonic()
            self.elapsed_ticks = 0
            self.events = deque(maxlen=100)
            self._event("System reset", "system")

    def _event(self, message: str, kind: str = "info", robot: str | None = None) -> None:
        self.events.appendleft({"message": message, "kind": kind, "robot": robot, "tick": self.tick_count})

    def _target(self, robot: Robot) -> Point | None:
        task = next((t for t in self.tasks if t.id == robot.task_id), None)
        if not task:
            return None
        if task.staged and robot.loaded:
            return STAGING
        return task.destination if robot.loaded else task.pickup

    def _claim_tasks(self) -> None:
        idle = [r for r in self.robots if r.task_id is None and r.battery > 0]
        for task in [t for t in self.tasks if t.status == "queued"]:
            candidates = [(abs(r.pos[0] - task.pickup[0]) + abs(r.pos[1] - task.pickup[1]), r.id, r) for r in idle]
            if not candidates:
                break
            _, _, robot = min(candidates)
            robot.task_id, robot.loaded, task.owner, task.status = task.id, False, robot.id, "claimed"
            robot.route = astar(robot.pos, task.pickup, self.blocked) or []
            robot.state = "to pickup" if robot.route else "at pickup"
            idle.remove(robot)
            self._event(f"{robot.id} claimed {task.id} by nearest-robot rule", "claim", robot.id)

    def _replan_blocked(self, robot: Robot) -> None:
        target = self._target(robot)
        if target is None:
            return
        route = astar(robot.pos, target, self.blocked)
        if route is not None:
            if route != robot.route:
                self._event(f"{robot.id} computed an alternate route", "reroute", robot.id)
            robot.route, robot.state = route, "at pickup" if not route and not robot.loaded else ("delivering" if robot.loaded else "to pickup")
            return
        task = next(t for t in self.tasks if t.id == robot.task_id)
        if not robot.loaded:
            self._event(f"{task.id} path blocked; releasing unpicked task for re-claim", "reassign", robot.id)
            task.status, task.owner = "queued", None
            robot.task_id, robot.route, robot.state = None, [], "idle"
        else:
            stage_route = astar(robot.pos, STAGING, self.blocked)
            if stage_route is None:
                robot.route, robot.state = [], "blocked"
                self._event(f"{robot.id} cannot reach staging; waiting for aisle clearance", "blocked", robot.id)
            else:
                task.staged = True
                robot.route, robot.state = stage_route, "rerouting to staging"
                self._event(f"{robot.id} carrying {task.id}; routing to staging fallback", "staging", robot.id)

    def tick(self) -> None:
        with self.lock:
            self.tick_count += 1
            self.elapsed_ticks += 1
            self._claim_tasks()
            for robot in self.robots:
                if robot.battery <= 0:
                    if robot.task_id:
                        task = next(t for t in self.tasks if t.id == robot.task_id)
                        task.status, task.owner = "queued", None
                        self._event(f"{robot.id} battery depleted; {task.id} returned to queue", "reassign", robot.id)
                    robot.task_id, robot.route, robot.state = None, [], "battery depleted"
                    continue
                target = self._target(robot)
                if target is not None and (not robot.route or robot.route[-1] != target):
                    self._replan_blocked(robot)

            if self.mode == "baseline":
                self._tick_baseline()
            else:
                self._tick_swarm()
            positions = [robot.pos for robot in self.robots]
            self.collisions += len(positions) - len(set(positions))
            pending_routes = any(robot.task_id and robot.route for robot in self.robots)
            moved = any(robot.state == "moving" for robot in self.robots)
            if pending_routes and not moved:
                self.stalled_ticks += 1
                if self.stalled_ticks >= 12 and not self.deadlock_active:
                    self.deadlocks += 1
                    self.deadlock_active = True
                    self._event("Fleet made no progress for 12 ticks; deadlock recorded", "deadlock")
            else:
                self.stalled_ticks = 0
                self.deadlock_active = False
            self._complete_arrivals()

    def _tick_baseline(self) -> None:
        active = sorted((r for r in self.robots if r.task_id and r.route), key=lambda r: r.id)
        if not active:
            self._claim_tasks()
            return
        # Centralized stop-and-wait: only one robot advances in a tick.
        robot = active[0]
        for waiting in active[1:]:
            waiting.wait_ticks += 1
            waiting.state = "waiting for fleet turn"
        robot.pos = robot.route.pop(0)
        robot.battery = max(0, robot.battery - 1)
        robot.state = "moving"

    def _tick_swarm(self) -> None:
        # Older waits age upward; robot ID is the stable simultaneous-request tiebreak.
        active = [r for r in self.robots if r.task_id and r.route]
        active.sort(key=lambda r: (-(r.wait_ticks // 8), -int(r.id[1:])))
        occupants = {r.pos: r for r in self.robots}
        proposals: dict[str, Point] = {}
        selected_destinations: set[Point] = set()
        for robot in active:
            nxt = robot.route[0]
            if nxt in selected_destinations:
                continue
            proposals[robot.id] = nxt
            selected_destinations.add(nxt)

        def can_advance(robot_id: str, trail: set[str]) -> bool:
            if robot_id in trail:
                return False
            nxt = proposals.get(robot_id)
            if nxt is None:
                return False
            occupant = occupants.get(nxt)
            if occupant is None:
                return True
            if occupant.id == robot_id:
                return False
            return can_advance(occupant.id, trail | {robot_id})

        accepted = {robot_id: point for robot_id, point in proposals.items() if can_advance(robot_id, set())}
        for robot in active:
            nxt = robot.route[0]
            if robot.id not in accepted:
                robot.wait_ticks += 1
                robot.state = "yielding"
                self.conflicts_resolved += 1
                self._event(f"{robot.id} yields at {nxt[0]},{nxt[1]}; reservation conflict resolved", "yield", robot.id)
                if robot.wait_ticks >= 2:
                    dynamic_obstacles = self.blocked | {r.pos for r in self.robots if r.id != robot.id}
                    target = self._target(robot)
                    alternate = astar(robot.pos, target, dynamic_obstacles) if target is not None else None
                    if alternate:
                        robot.route = alternate
                        self._event(f"{robot.id} locally rerouted around occupied cells", "reroute", robot.id)
                continue
            # All accepted moves were checked against the simultaneous departure set.
            point = accepted[robot.id]
            robot.pos = point
            robot.route.pop(0)
            robot.battery = max(0, robot.battery - 1)
            robot.wait_ticks = max(0, robot.wait_ticks - 1)
            robot.state = "moving"

    def _complete_arrivals(self) -> None:
        for robot in self.robots:
            if not robot.task_id or robot.route:
                continue
            task = next((t for t in self.tasks if t.id == robot.task_id), None)
            if task is None:
                continue
            if not robot.loaded and robot.pos == task.pickup:
                robot.loaded, robot.route, robot.state = True, astar(robot.pos, task.destination, self.blocked) or [], "delivering"
                self._event(f"{robot.id} picked up {task.id}", "pickup", robot.id)
            elif robot.loaded and robot.pos == self._target(robot):
                if task.staged:
                    old = task.id
                    task.id = f"{old}-H"
                    task.pickup = STAGING
                    task.status, task.owner, task.staged = "queued", None, False
                    robot.task_id, robot.loaded, robot.state = None, False, "idle"
                    self._event(f"{robot.id} staged {old}; new handoff task {task.id} queued", "staging", robot.id)
                else:
                    task.status, robot.state = "complete", "complete"
                    robot.completed += 1
                    robot.task_id, robot.loaded = None, False
                    self._event(f"{robot.id} delivered {task.id}", "complete", robot.id)
        self._claim_tasks()

    def set_blockage(self, point: Point, blocked: bool) -> None:
        with self.lock:
            if point in WALLS:
                return
            if blocked:
                self.blocked.add(point)
                self._event(f"Aisle blocked at {point[0]},{point[1]}; affected routes recalculating", "blocked")
                for robot in self.robots:
                    if robot.task_id and point in robot.route:
                        robot.route = []
            else:
                self.blocked.discard(point)
                self._event(f"Aisle cleared at {point[0]},{point[1]}", "clear")

    def snapshot(self) -> dict:
        with self.lock:
            completed = sum(t.status == "complete" for t in self.tasks)
            all_done = bool(self.tasks) and completed == len(self.tasks)
            elapsed = self.tick_count
            return {
                "width": WIDTH, "height": HEIGHT, "walls": [list(p) for p in sorted(WALLS)],
                "blocked": [list(p) for p in sorted(self.blocked - WALLS)],
                "staging": list(STAGING), "mode": self.mode, "running": self.running,
                "tick": self.tick_count, "robots": [self._robot_json(r) for r in self.robots],
                "tasks": [asdict(t) for t in self.tasks], "events": list(self.events),
                "metrics": {"collisions": self.collisions, "deadlocks": self.deadlocks,
                    "conflictsResolved": self.conflicts_resolved, "completed": completed,
                    "totalTasks": len(self.tasks), "completionTicks": elapsed if all_done else None,
                    "waitTicks": sum(r.wait_ticks for r in self.robots),
                    "elapsedSeconds": round(time.monotonic() - self.started_at, 1)},
            }

    @staticmethod
    def _robot_json(robot: Robot) -> dict:
        return {**asdict(robot), "pos": list(robot.pos), "route": [list(p) for p in robot.route]}


sim = Simulator()


def run_comparison() -> dict:
    """Run both modes against identical static tasks; results are simulation measurements."""
    outcomes = {}
    for mode in ("baseline", "swarm"):
        model = Simulator()
        model.mode = mode
        for _ in range(5000):
            model.tick()
            if all(t.status == "complete" for t in model.tasks):
                break
        outcomes[mode] = {"ticks": model.tick_count, "collisions": model.collisions, "deadlocks": model.deadlocks,
                          "completed": sum(t.status == "complete" for t in model.tasks)}
    base, swarm = outcomes["baseline"], outcomes["swarm"]
    reduction = round((1 - swarm["ticks"] / base["ticks"]) * 100, 1) if base["ticks"] else 0
    return {"baseline": base, "swarm": swarm, "timeReductionPercent": reduction,
            "targetMet": reduction >= 20 and swarm["collisions"] == 0}
