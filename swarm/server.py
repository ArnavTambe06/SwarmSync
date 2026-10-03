"""Small standard-library HTTP server for the simulator and dashboard."""

from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from swarm.engine import HEIGHT, WIDTH, run_comparison, sim

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "web"


class Handler(BaseHTTPRequestHandler):
    server_version = "SwarmSync/0.1"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def _json(self, value: object, status: int = 200) -> None:
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/state":
            self._json(sim.snapshot())
        elif path == "/api/compare":
            self._json(run_comparison())
        elif path == "/api/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                while True:
                    payload = json.dumps(sim.snapshot(), separators=(",", ":"))
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(0.35)
            except (BrokenPipeError, ConnectionResetError):
                return
        else:
            self._static(path)

    def _static(self, path: str) -> None:
        requested = "index.html" if path == "/" else path.lstrip("/")
        target = (STATIC / requested).resolve()
        if STATIC.resolve() not in target.parents and target != STATIC.resolve():
            self.send_error(403)
            return
        if not target.is_file():
            self.send_error(404)
            return
        content_type = {".html": "text/html", ".css": "text/css", ".js": "text/javascript"}.get(target.suffix, "application/octet-stream")
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json({"error": "Invalid JSON"}, 400)
            return
        with sim.lock:
            if path == "/api/control":
                action = data.get("action")
                if action == "run": sim.running = True
                elif action == "pause": sim.running = False
                elif action == "step": sim.running = False; sim.tick()
                elif action == "reset": sim.reset()
                elif action == "mode" and data.get("mode") in ("swarm", "baseline"):
                    sim.mode = data["mode"]
                    sim._event(f"Mode changed to {sim.mode}", "system")
                else:
                    self._json({"error": "Unknown control action"}, 400)
                    return
            elif path == "/api/blockage":
                try:
                    point = (int(data["x"]), int(data["y"]))
                    if not (0 <= point[0] < WIDTH and 0 <= point[1] < HEIGHT):
                        raise ValueError
                except (KeyError, TypeError, ValueError):
                    self._json({"error": "x/y must be valid grid coordinates"}, 400)
                    return
                sim.set_blockage(point, bool(data.get("blocked", True)))
            else:
                self._json({"error": "Not found"}, 404)
                return
        self._json(sim.snapshot())


def simulation_loop() -> None:
    while True:
        time.sleep(0.45)
        if sim.running:
            sim.tick()
            publish_mqtt_state()


mqtt_client = None


def publish_mqtt_state() -> None:
    if mqtt_client is None:
        return
    snapshot = sim.snapshot()
    for robot in snapshot["robots"]:
        message = {"robotId": robot["id"], "position": robot["pos"], "route": robot["route"],
                   "state": robot["state"], "battery": robot["battery"], "tick": snapshot["tick"]}
        mqtt_client.publish(f"swarmsync/robots/{robot['id']}/state", json.dumps(message), qos=0)


def start_mqtt() -> None:
    global mqtt_client
    broker = os.environ.get("MQTT_HOST")
    if not broker:
        print("MQTT disabled; set MQTT_HOST to enable the local broker relay")
        return
    try:
        import paho.mqtt.client as mqtt
        mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="swarmsync-simulator")
        mqtt_client.connect(broker, int(os.environ.get("MQTT_PORT", "1883")), 30)
        mqtt_client.loop_start()
        print(f"MQTT telemetry relay connected to {broker}")
    except (ImportError, OSError) as exc:
        print(f"MQTT relay unavailable: {exc}")


def main() -> None:
    start_mqtt()
    threading.Thread(target=simulation_loop, daemon=True).start()
    host = os.environ.get("SWARMSYNC_HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", os.environ.get("SWARMSYNC_PORT", "8000")))
    print(f"SwarmSync dashboard: http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
