# SwarmSync

**Decentralized fleet coordination for Autonomous Mobile Robots (AMRs) in smart warehouses — no central server, no single point of failure.**

Built for **Smart India Hackathon 2026** — Problem Statement **26123**, posed by **Bharat Electronics Limited (BEL)**.

---

## The Problem

Warehouse AMR fleets today depend on a central cloud server for path planning and collision avoidance. That dependency causes:

- High network latency and delayed commands
- Wi-Fi dead zones inside large warehouse floors
- A single point of failure — one server outage halts the entire fleet

## Our Approach

SwarmSync removes the central server from the coordination loop entirely. Robots communicate directly with each other over MQTT, resolve conflicts locally using reservation-based priority planning, and reroute or hand off tasks autonomously when a path is blocked.

- **Peer-to-Peer Communication** — robots broadcast position and intent directly, no central decision-maker
- **Reservation-Based Conflict Resolution** — priority-timestamp reservations resolve who goes first at shared intersections, with a deterministic tiebreaker (lower robot ID yields) to prevent deadlock
- **Task Allocation & Re-routing** — blocked robots reroute locally first; unstarted tasks are reassigned via broadcast-and-claim if a path is fully blocked
- **Live Fleet Dashboard** — real-time visualization of robot positions, task status, and battery via WebSocket

## Tech Stack

| Layer | Technology |
|---|---|
| Simulation & Algorithm | Python |
| Robot-to-Robot Messaging | MQTT |
| Backend API | Java Spring Boot |
| Live Dashboard Updates | WebSocket |
| Containerization | Docker |

## Success Criteria

- **Zero inter-robot collisions** under simulated conditions
- **≥20% reduction in task completion time** vs. traditional centralized stop-and-wait coordination

## Status

This is a proof-of-concept simulation validating the coordination mechanism — not production firmware. It demonstrates that decentralized, reservation-based coordination is sound and implementable on lightweight, edge-feasible logic; a production deployment would require further work against real robot dynamics, sensor noise, and hardware-specific constraints.

## Team

**The Debuggers** — BVIMIT, Navi Mumbai
