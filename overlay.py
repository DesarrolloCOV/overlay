import subprocess
import time
import logging
import threading
import sys
import os
from datetime import datetime

# Configuración
FFMPEG_PATH = "/usr/bin/ffmpeg"
GIF_PATH = "/var/www/html/livevideo/img/Drone_aspas_girando.gif"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

RTMP_INPUT = "rtmp://localhost:1935/cov/"
RTSP_OUTPUT = "rtsp://localhost:8554/"
STREAMS = ["vant1", "vant2", "vant3", "vant4", "vant5"]
CHECK_INTERVAL = 10
MAX_FAILURES = 1
MAX_STREAM_FAILURES = 1  # Máximo de fallos permitidos por stream

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Variables globales
active_processes = {}
error_flags = {}
error_flags_lock = threading.Lock()
consecutive_failures = 0
stream_failures = {}  # ✅ CORREGIDO: ahora está definido

def restart_script():
    logging.warning("Reiniciando el script...")
    python = sys.executable
    os.execv(python, [python] + sys.argv)

def format_stream_name(name):
    if name.lower().startswith("vant") and name[4:].isdigit():
        return f"VANT-{name[4:]}"
    return name.upper()

def check_stream(stream_name):
    global stream_failures

    command = [
        FFMPEG_PATH,
        '-rw_timeout', '5000000',
        '-i', f"{RTMP_INPUT}{stream_name}",
        '-v', 'quiet',
        '-t', '3',
        '-f', 'null',
        'null'
    ]

    try:
        subprocess.run(command, check=True, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        stream_failures[stream_name] = 0
        return True

    except subprocess.CalledProcessError as e:
        stream_failures[stream_name] = stream_failures.get(stream_name, 0) + 1
        logging.warning(f"check_stream no esta transmitiendo {stream_name} (fallo #{stream_failures[stream_name]}): {e.stderr.decode().strip()}")

        if stream_failures[stream_name] >= MAX_STREAM_FAILURES:
            return False
        return True

def log_ffmpeg_output(stream_name, process):
    global error_flags
    try:
        for line in iter(process.stderr.readline, ''):
            if line:
                sys.stdout.write(f"[{stream_name}] {line}")
                sys.stdout.flush()
                if any(err in line for err in [
                    "Broken pipe", "Error muxing", "Conversion failed",
                    "Conversion fallida", "DTS", "illegal reordering_of_pic_nums_idc"
                ]):
                    with error_flags_lock:
                        error_flags[stream_name] = True
    except Exception as e:
        logging.error(f"Error leyendo salida de FFmpeg para {stream_name}: {e}")

def start_stream_process(stream_name):
    overlay_name = format_stream_name(stream_name)

    filter_complex = (
        "[1:v]format=rgba,scale=200:-1[gif];"
        "[0:v][gif]overlay=10:10[tmp];"
        f"[tmp]drawtext=text='{overlay_name}':"
        f"fontfile='{FONT_PATH}':fontcolor=white:fontsize=26:"
        "borderw=2:bordercolor=black@0.7:shadowx=2:shadowy=2:"
        "x=10+((200-text_w)/2):y=10+110:"
        "enable='lt(mod(t\\,2)\\,1)'[outv]"
    )

    command = [
        FFMPEG_PATH,
        '-fflags', '+genpts+discardcorrupt',
        '-rw_timeout', '5000000',
        '-analyzeduration', '1000000',
        '-probesize', '1000000',
        '-i', f"{RTMP_INPUT}{stream_name}",
        '-err_detect', 'ignore_err',
        '-ignore_loop', '0',
        '-i', GIF_PATH,
        '-filter_complex', filter_complex,
        '-map', '[outv]',
        '-an',
        '-c:v', 'libx264',
        '-preset', 'ultrafast',
        '-tune', 'zerolatency',
        '-g', '30',
        '-b:v', '3000k',
        '-f', 'rtsp',
        '-rtsp_transport', 'tcp',
        '-muxdelay', '0.1',
        '-muxpreload', '0',
        f"{RTSP_OUTPUT}{stream_name}"
    ]

    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    threading.Thread(target=log_ffmpeg_output, args=(stream_name, process), daemon=True).start()

    active_processes[stream_name] = process
    with error_flags_lock:
        error_flags[stream_name] = False
    logging.info(f"Iniciando procesamiento para {stream_name}")

def stop_stream_process(stream_name):
    if stream_name in active_processes:
        process = active_processes[stream_name]
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        del active_processes[stream_name]
        with error_flags_lock:
            error_flags[stream_name] = False
        logging.info(f"Detenido procesamiento para {stream_name}")

def monitor_processes():
    global consecutive_failures
    for stream_name, process in list(active_processes.items()):
        should_restart = False

        if process.poll() is not None:
            should_restart = True
            logging.warning(f"{stream_name} terminó inesperadamente.")

        with error_flags_lock:
            if error_flags.get(stream_name, False):
                should_restart = True
                logging.error(f"{stream_name} mostró errores críticos. Reiniciando.")
                error_flags[stream_name] = False

        if should_restart:
            stop_stream_process(stream_name)
            time.sleep(2)
            start_stream_process(stream_name)
            consecutive_failures += 1
        else:
            consecutive_failures = 0

    if consecutive_failures >= MAX_FAILURES:
        logging.error("Demasiados errores consecutivos. Reiniciando script.")
        restart_script()

def main():
    logging.info("Iniciando monitor de streams")
    try:
        while True:
            active_now = []
            for stream in STREAMS:
                if check_stream(stream):
                    active_now.append(stream)
                    if stream not in active_processes:
                        start_stream_process(stream)
                else:
                    if stream in active_processes:
                        logging.warning(f"Stream {stream} ya no está activo. Deteniendo proceso.")
                        stop_stream_process(stream)

            monitor_processes()
            logging.info(f"Streams activos ahora: {active_now}")
            time.sleep(CHECK_INTERVAL)

    except KeyboardInterrupt:
        logging.info("Deteniendo monitor de streams")
        for stream in list(active_processes.keys()):
            stop_stream_process(stream)

if __name__ == "__main__":
    main()
