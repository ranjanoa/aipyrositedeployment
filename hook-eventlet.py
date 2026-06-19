# hook-eventlet.py
# Disabled eventlet monkey patching on Windows to prevent socket/InfluxDB connection aborts.
print("[INIT] Eventlet monkey patching disabled for Windows stability")
