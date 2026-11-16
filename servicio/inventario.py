"""Servicio de inventario: base de datos SQLite + MQTT.

- Guarda las entradas y salidas de cada producto y calcula el stock (entradas - salidas).
- Envía al ESP32 el historial de ventas de cada producto; el ESP32 ejecuta la red y devuelve el pronóstico.
- Publica en Home Assistant (descubrimiento MQTT) el stock, el pronóstico y las unidades a comprar,
  junto con un formulario para registrar ventas y entradas desde el celular.

Uso (desde la raíz del repositorio):
    python servicio/inventario.py                        ejecutar el servicio
    python servicio/inventario.py importar archivo.csv   cargar movimientos (fecha,producto,tipo,cantidad)
    python servicio/inventario.py producto pan "Pan"     crear o renombrar un producto
"""
import csv
import json
import logging
import os
import re
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

VENTANA, ANIO, H = 28, 364, 7  # iguales a los notebooks: días recientes, desfase de 52 semanas, días a pronosticar
DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
CANTIDAD_MAXIMA = 100_000
CARPETA = Path(__file__).resolve().parent
log = logging.getLogger("inventario")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS productos (
    id     TEXT PRIMARY KEY,   -- se usa en los temas MQTT: inventario/<id>/...
    nombre TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS movimientos (
    id         INTEGER PRIMARY KEY,
    fecha      TEXT NOT NULL,  -- AAAA-MM-DD
    producto   TEXT NOT NULL REFERENCES productos(id),
    tipo       TEXT NOT NULL CHECK (tipo IN ('entrada', 'salida')),
    cantidad   INTEGER NOT NULL CHECK (cantidad > 0),
    registrado TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS movimientos_producto_fecha ON movimientos (producto, fecha);
CREATE TABLE IF NOT EXISTS pronosticos (
    producto TEXT NOT NULL REFERENCES productos(id),
    corte    TEXT NOT NULL,    -- último día con ventas conocidas; el pronóstico cubre los 7 días siguientes
    total    INTEGER NOT NULL,
    detalle  TEXT NOT NULL,    -- JSON tal como lo publicó el ESP32
    recibido TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (producto, corte)
);
"""


# ---------------------------------------------------------------- base de datos

def abrir(ruta):
    db = sqlite3.connect(ruta)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(ESQUEMA)
    return db


def guardar_producto(db, producto, nombre):
    if not re.fullmatch(r"[a-z0-9_]{1,30}", producto):
        raise ValueError(f"id de producto inválido {producto!r}: solo minúsculas sin tildes, números y _ (va en los temas MQTT)")
    with db:
        db.execute("INSERT INTO productos (id, nombre) VALUES (?, ?) "
                   "ON CONFLICT(id) DO UPDATE SET nombre = excluded.nombre", (producto, nombre))


def productos(db):
    return db.execute("SELECT id, nombre FROM productos ORDER BY nombre").fetchall()


def validar(db, producto, tipo, cantidad):
    if tipo not in ("entrada", "salida"):
        raise ValueError(f"tipo inválido {tipo!r}: debe ser 'entrada' o 'salida'")
    if isinstance(cantidad, bool) or not isinstance(cantidad, int) or not 1 <= cantidad <= CANTIDAD_MAXIMA:
        raise ValueError(f"cantidad inválida {cantidad!r}: debe ser un entero entre 1 y {CANTIDAD_MAXIMA}")
    if db.execute("SELECT 1 FROM productos WHERE id = ?", (producto,)).fetchone() is None:
        raise ValueError(f"el producto {producto!r} no existe")


def registrar(db, producto, tipo, cantidad, fecha=None):
    validar(db, producto, tipo, cantidad)
    with db:
        db.execute("INSERT INTO movimientos (fecha, producto, tipo, cantidad) VALUES (?, ?, ?, ?)",
                   ((fecha or date.today()).isoformat(), producto, tipo, cantidad))


def stock(db, producto):
    (total,) = db.execute("SELECT COALESCE(SUM(CASE tipo WHEN 'entrada' THEN cantidad ELSE -cantidad END), 0) "
                          "FROM movimientos WHERE producto = ?", (producto,)).fetchone()
    return total


def historial(db, producto, corte):
    """Historial crudo que el ESP32 convierte en las 42 entradas de la red. Mismos cortes que armar_pistas()."""
    inicio = corte - timedelta(days=ANIO + VENTANA - 1)  # 391 días antes del corte
    ventas = [0] * (ANIO + VENTANA)                      # posición 0 = inicio, última = corte
    filas = db.execute("SELECT fecha, SUM(cantidad) FROM movimientos WHERE producto = ? AND tipo = 'salida' "
                       "AND fecha BETWEEN ? AND ? GROUP BY fecha", (producto, inicio.isoformat(), corte.isoformat()))
    for fecha, cantidad in filas:
        ventas[(date.fromisoformat(fecha) - inicio).days] = cantidad
    return {
        "corte": corte.isoformat(),
        "dia": (corte.weekday() + 1) % 7,                         # primer día pronosticado (0 = lunes)
        "reciente": ventas[-VENTANA:],                            # del corte-27 al corte
        "anio": ventas[VENTANA:VENTANA + H],                      # los 7 días a pronosticar, 364 días antes
        "base_anio": round(sum(ventas[:VENTANA]) / VENTANA, 4),  # promedio de los 28 días anteriores a esa semana
    }


def guardar_pronostico(db, producto, datos):
    with db:
        db.execute("INSERT OR REPLACE INTO pronosticos (producto, corte, total, detalle) VALUES (?, ?, ?, ?)",
                   (producto, datos["corte"], int(datos["total_7d"]), json.dumps(datos)))


def ultimo_pronostico(db, producto):
    fila = db.execute("SELECT detalle FROM pronosticos WHERE producto = ? ORDER BY corte DESC LIMIT 1",
                      (producto,)).fetchone()
    return json.loads(fila[0]) if fila else None


def resumen(db, producto, nombre):
    """Lo que Home Assistant y el agente necesitan de un producto. El cálculo de compra se hace aquí, no en el LLM."""
    datos = {"producto": nombre, "stock": stock(db, producto), "pronostico_7d": None, "comprar": None}
    pronostico = ultimo_pronostico(db, producto)
    if pronostico:
        datos["pronostico_7d"] = pronostico["total_7d"]
        datos["comprar"] = max(pronostico["total_7d"] - datos["stock"], 0)
        datos["pronostico_corte"] = pronostico["corte"]
        datos.update({dia: pronostico[dia] for dia in DIAS if dia in pronostico})
    return datos


def importar_csv(db, ruta):
    """Carga movimientos desde un CSV con columnas fecha,producto,tipo,cantidad. Crea los productos que falten."""
    with open(ruta, newline="", encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    for producto in sorted({fila["producto"] for fila in filas}):
        if db.execute("SELECT 1 FROM productos WHERE id = ?", (producto,)).fetchone() is None:
            guardar_producto(db, producto, producto.capitalize())
    movimientos = []
    for numero, fila in enumerate(filas, start=2):  # la línea 1 es el encabezado
        try:
            cantidad = int(fila["cantidad"])
            validar(db, fila["producto"], fila["tipo"], cantidad)
            movimientos.append((date.fromisoformat(fila["fecha"]).isoformat(), fila["producto"], fila["tipo"], cantidad))
        except ValueError as e:
            raise ValueError(f"{ruta}, línea {numero}: {e}") from None
    with db:
        db.executemany("INSERT INTO movimientos (fecha, producto, tipo, cantidad) VALUES (?, ?, ?, ?)", movimientos)
    return len(movimientos)


# ---------------------------------------------------------------- MQTT

class Servicio:
    """Atiende los mensajes MQTT. Todo corre en un solo hilo, así que la conexión SQLite no se comparte."""

    def __init__(self, db, cliente):
        self.db, self.cliente = db, cliente
        self.formulario = {"producto": None, "cantidad": 1}
        self.comprar = {}          # último valor por producto: la alerta se envía solo cuando pasa de 0 a más
        self.dia_enviado = None    # fecha del último envío de historiales al ESP32

    def publicar(self, tema, datos, retener=True):
        texto = datos if isinstance(datos, str) else json.dumps(datos, ensure_ascii=False)
        self.cliente.publish(tema, texto, retain=retener)

    def nombres(self):
        return dict(productos(self.db))

    # ----- Home Assistant

    def descubrimiento(self):
        """Crea en Home Assistant los sensores de cada producto y el formulario de movimientos."""
        nombres = self.nombres()
        for producto, nombre in nombres.items():
            tema_stock = f"inventario/{producto}/stock"
            tema_pronostico = f"inventario/{producto}/pronostico"
            sensores = {
                f"stock_{producto}": {"name": f"Stock {nombre}", "state_topic": tema_stock,
                                      "value_template": "{{ value_json.stock }}", "json_attributes_topic": tema_stock},
                f"comprar_{producto}": {"name": f"Comprar {nombre}", "state_topic": tema_stock,
                                        "value_template": "{{ value_json.comprar }}"},
                f"pronostico_{producto}_7d": {"name": f"Pronóstico {nombre} 7d", "state_topic": tema_pronostico,
                                              "value_template": "{{ value_json.total_7d }}",
                                              "json_attributes_topic": tema_pronostico},
            }
            for id_unico, config in sensores.items():
                config.update(unique_id=id_unico, unit_of_measurement="unidades")
                self.publicar(f"homeassistant/sensor/{id_unico}/config", config)

        formulario = {
            "select/inventario_producto": {"name": "Inventario producto", "options": list(nombres.values()),
                                           "command_topic": "inventario/form/producto/set",
                                           "state_topic": "inventario/form/producto"},
            "number/inventario_cantidad": {"name": "Inventario cantidad", "min": 1, "max": CANTIDAD_MAXIMA, "step": 1,
                                           "mode": "box", "unit_of_measurement": "unidades",
                                           "command_topic": "inventario/form/cantidad/set",
                                           "state_topic": "inventario/form/cantidad"},
            "button/inventario_registrar_venta": {"name": "Registrar venta", "payload_press": "salida",
                                                  "command_topic": "inventario/form/registrar"},
            "button/inventario_registrar_entrada": {"name": "Registrar entrada", "payload_press": "entrada",
                                                    "command_topic": "inventario/form/registrar"},
            "button/inventario_recalcular": {"name": "Recalcular pronóstico", "payload_press": "ahora",
                                             "command_topic": "inventario/recalcular"},
            "sensor/inventario_ultimo_movimiento": {"name": "Inventario último movimiento",
                                                    "state_topic": "inventario/ultimo_movimiento"},
        }
        for ruta, config in formulario.items():
            config["unique_id"] = ruta.split("/")[1]
            self.publicar(f"homeassistant/{ruta}/config", config)

        if self.formulario["producto"] not in nombres and nombres:
            self.formulario["producto"] = next(iter(nombres))
        if self.formulario["producto"]:
            self.publicar("inventario/form/producto", nombres[self.formulario["producto"]])
        self.publicar("inventario/form/cantidad", str(self.formulario["cantidad"]))

    def publicar_producto(self, producto, alertar=True):
        nombre = self.nombres()[producto]
        datos = resumen(self.db, producto, nombre)
        self.publicar(f"inventario/{producto}/stock", datos)
        anterior, self.comprar[producto] = self.comprar.get(producto), datos["comprar"]
        if alertar and datos["comprar"] and not anterior:
            self.publicar("inventario/alerta", f"Te vas a quedar sin {nombre.lower()}: hay {datos['stock']} y se "
                          f"pronostican {datos['pronostico_7d']} para los próximos 7 días. Compra unas {datos['comprar']}.",
                          retener=False)

    # ----- ESP32

    def enviar_historiales(self):
        """Envía al ESP32 el historial de cada producto hasta ayer (el último día completo)."""
        corte = date.today() - timedelta(days=1)
        for producto, nombre in productos(self.db):
            (primera,) = self.db.execute("SELECT MIN(fecha) FROM movimientos WHERE producto = ? AND tipo = 'salida'",
                                         (producto,)).fetchone()
            if primera is None or date.fromisoformat(primera) > corte - timedelta(days=ANIO + VENTANA - 1):
                log.warning("%s: menos de %d días de ventas; el pronóstico será menos preciso", nombre, ANIO + VENTANA)
            self.publicar(f"inventario/{producto}/historial", historial(self.db, producto, corte))
        self.dia_enviado = date.today()
        log.info("Historiales enviados al ESP32 (corte %s)", corte)

    # ----- callbacks de paho-mqtt

    def al_conectar(self, cliente, userdata, flags, codigo, propiedades=None):
        if codigo.is_failure:
            log.error("MQTT rechazó la conexión: %s (¿usuario o clave en servicio/.env?)", codigo)
            return
        log.info("Conectado a MQTT")
        for tema in ("inventario/+/pronostico", "inventario/movimiento", "inventario/form/+/set",
                     "inventario/form/registrar", "inventario/recalcular"):
            cliente.subscribe(tema)
        self.descubrimiento()
        for producto in self.nombres():
            self.publicar_producto(producto, alertar=False)

    def al_mensaje(self, cliente, userdata, mensaje):
        tema, texto = mensaje.topic, mensaje.payload.decode("utf-8", errors="replace")
        try:
            self.atender(tema, texto)
        except (ValueError, KeyError, TypeError, OverflowError) as e:  # JSONDecodeError es un ValueError
            log.warning("Mensaje ignorado en %s (%s): %s", tema, e, texto[:120])

    def atender(self, tema, texto):
        partes = tema.split("/")
        if len(partes) == 3 and partes[2] == "pronostico":
            producto, datos = partes[1], json.loads(texto)
            if "corte" not in datos or producto not in self.nombres():
                return  # valores de prueba de la etapa 1 o producto desconocido
            date.fromisoformat(datos["corte"])  # valida el formato antes de guardarlo
            guardar_pronostico(self.db, producto, datos)
            log.info("Pronóstico de %s: %s unidades en 7 días", producto, datos["total_7d"])
            self.publicar_producto(producto)

        elif tema == "inventario/movimiento":  # para otros clientes (scripts, el agente más adelante)
            datos = json.loads(texto)
            self.registrar_y_publicar(datos["producto"], datos["tipo"], datos["cantidad"])

        elif tema == "inventario/form/producto/set":
            producto = {nombre: p for p, nombre in self.nombres().items()}[texto]
            self.formulario["producto"] = producto
            self.publicar("inventario/form/producto", texto)

        elif tema == "inventario/form/cantidad/set":
            cantidad = int(float(texto))
            if not 1 <= cantidad <= CANTIDAD_MAXIMA:
                raise ValueError("cantidad fuera de rango")
            self.formulario["cantidad"] = cantidad
            self.publicar("inventario/form/cantidad", str(cantidad))

        elif tema == "inventario/form/registrar":
            self.registrar_y_publicar(self.formulario["producto"], texto, self.formulario["cantidad"])

        elif tema == "inventario/recalcular":
            self.enviar_historiales()

    def registrar_y_publicar(self, producto, tipo, cantidad):
        registrar(self.db, producto, tipo, cantidad)
        nombre = self.nombres()[producto]
        texto = f"{'Venta' if tipo == 'salida' else 'Entrada'} de {nombre}: {cantidad} unidades ({datetime.now():%H:%M})"
        log.info(texto)
        self.publicar("inventario/ultimo_movimiento", texto)
        self.publicar_producto(producto)


# ---------------------------------------------------------------- ejecución

def cargar_env(ruta):
    """Lee las líneas VARIABLE=valor de servicio/.env (ese archivo no se sube a GitHub)."""
    if ruta.exists():
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            if "=" in linea and not linea.lstrip().startswith("#"):
                clave, valor = linea.split("=", 1)
                valor = valor.strip()
                cierre = valor.find(valor[:1], 1) if valor[:1] in ("'", '"') else -1
                if cierre > 0:  # "valor" // comentario  ->  valor (mismo estilo que secrets.h)
                    valor = valor[1:cierre]
                os.environ.setdefault(clave.strip(), valor)


def ruta_bd():
    return os.environ.get("BD", str(CARPETA / "inventario.db"))


def ejecutar():
    import paho.mqtt.client as mqtt

    db = abrir(ruta_bd())
    if not productos(db):
        log.warning("La base de datos no tiene productos. Primero: python servicio/inventario.py importar servicio/demo.csv")
    cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="servicio-inventario")
    faltan = [v for v in ("MQTT_HOST", "MQTT_USER", "MQTT_PASS") if not os.environ.get(v)]
    if faltan:
        sys.exit(f"Faltan en servicio/.env: {', '.join(faltan)} (ver servicio/.env.ejemplo)")
    cliente.username_pw_set(os.environ["MQTT_USER"], os.environ["MQTT_PASS"])
    servicio = Servicio(db, cliente)
    cliente.on_connect = servicio.al_conectar
    cliente.on_message = servicio.al_mensaje

    host, puerto = os.environ["MQTT_HOST"], int(os.environ.get("MQTT_PUERTO", "1883"))
    while True:
        try:
            cliente.connect(host, puerto)
            break
        except OSError as e:
            log.error("No se pudo conectar a %s:%d (%s). Reintento en 10 s", host, puerto, e)
            time.sleep(10)

    while True:
        if cliente.loop(timeout=1.0) != mqtt.MQTT_ERR_SUCCESS:
            log.warning("Conexión MQTT perdida. Reintento en 5 s")
            time.sleep(5)
            try:
                cliente.reconnect()
            except OSError:
                pass
            continue
        if cliente.is_connected() and servicio.dia_enviado != date.today():
            servicio.enviar_historiales()  # al arrancar y cada día después de medianoche


def main(argumentos):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    cargar_env(CARPETA / ".env")
    if not argumentos:
        try:
            ejecutar()
        except KeyboardInterrupt:
            log.info("Servicio detenido")
    elif argumentos[0] == "importar" and len(argumentos) == 2:
        db = abrir(ruta_bd())
        print(f"{importar_csv(db, argumentos[1])} movimientos importados en {ruta_bd()}")
        for producto, nombre in productos(db):
            print(f"  {nombre}: stock {stock(db, producto)}")
    elif argumentos[0] == "producto" and len(argumentos) == 3:
        guardar_producto(abrir(ruta_bd()), argumentos[1], argumentos[2])
        print(f"Producto guardado: {argumentos[1]} = {argumentos[2]}")
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
