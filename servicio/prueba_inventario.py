"""Pruebas del servicio de inventario, sin broker MQTT ni ESP32.

Uso (desde la raíz del repositorio):  python servicio/prueba_inventario.py
"""
import csv
import json
import os
from datetime import date, timedelta
from pathlib import Path

import inventario as inv

KAGGLE = Path(__file__).resolve().parent.parent / "ml" / "data" / "train.csv"


class ClienteFalso:
    """Reemplaza al cliente MQTT: guarda lo que el servicio publica."""

    def __init__(self):
        self.mensajes = []

    def publish(self, tema, texto, retain=False):
        self.mensajes.append((tema, texto))

    def subscribe(self, tema):
        pass

    def ultimo(self, tema):
        return next((texto for t, texto in reversed(self.mensajes) if t == tema), None)


class Mensaje:
    def __init__(self, tema, texto):
        self.topic, self.payload = tema, texto.encode()


class ConexionAceptada:
    is_failure = False


def bd_con_manzanas(stock_inicial):
    db = inv.abrir(":memory:")
    inv.guardar_producto(db, "manzana", "Manzana")
    inv.registrar(db, "manzana", "entrada", stock_inicial)
    return db


def prueba_stock_y_validaciones():
    db = bd_con_manzanas(50)
    inv.registrar(db, "manzana", "salida", 8)
    assert inv.stock(db, "manzana") == 42
    for malo in [("pera", "salida", 1), ("manzana", "robo", 1), ("manzana", "salida", 0),
                 ("manzana", "salida", 2.5), ("manzana", "salida", True)]:
        try:
            inv.registrar(db, *malo)
        except ValueError:
            continue
        raise AssertionError(f"debió rechazar {malo}")
    for id_malo in ["Pan Tajado", "piña", "", "a/b"]:
        try:
            inv.guardar_producto(db, id_malo, "x")
        except ValueError:
            continue
        raise AssertionError(f"debió rechazar el id {id_malo!r}")
    assert inv.stock(db, "manzana") == 42


def prueba_historial_igual_al_notebook():
    """El historial debe coincidir con el vector de prueba 0 del firmware (tienda10_prod1, corte 2017-01-01),
    que el notebook 03 armó con armar_pistas()."""
    if not KAGGLE.exists():
        print("  (omitida: falta ml/data/train.csv)")
        return
    db = inv.abrir(":memory:")
    inv.guardar_producto(db, "p", "P")
    with open(KAGGLE, newline="") as f:
        filas = [(r["date"], "p", "salida", int(r["sales"])) for r in csv.DictReader(f)
                 if r["store"] == "10" and r["item"] == "1" and int(r["sales"]) > 0]
    with db:
        db.executemany("INSERT INTO movimientos (fecha, producto, tipo, cantidad) VALUES (?, ?, ?, ?)", filas)
    h = inv.historial(db, "p", date(2017, 1, 1))
    assert h["reciente"] == [17, 21, 23, 19, 30, 23, 31, 10, 15, 18, 17, 21, 17, 24,
                             18, 20, 14, 26, 21, 17, 30, 21, 17, 14, 25, 25, 28, 25], h["reciente"]
    assert h["anio"] == [23, 20, 18, 19, 28, 17, 23], h["anio"]
    assert abs(h["base_anio"] - 17.6071434) < 1e-3, h["base_anio"]
    assert h["dia"] == 0  # el 2017-01-02 fue lunes


def prueba_flujo_mqtt():
    db = bd_con_manzanas(30)
    cliente = ClienteFalso()
    servicio = inv.Servicio(db, cliente)
    servicio.al_conectar(cliente, None, None, ConexionAceptada())

    # descubrimiento: sensores del producto y formulario
    config = json.loads(cliente.ultimo("homeassistant/select/inventario_producto/config"))
    assert config["options"] == ["Manzana"]
    assert cliente.ultimo("homeassistant/sensor/pronostico_manzana_7d/config") is not None
    assert json.loads(cliente.ultimo("inventario/manzana/stock"))["comprar"] is None  # aún sin pronóstico

    # el ESP32 responde 52 → comprar 22 y alerta
    pronostico = {"total_7d": 52, "inicio": "lunes", "lunes": 9, "martes": 6, "miercoles": 6, "jueves": 7,
                  "viernes": 8, "sabado": 9, "domingo": 7, "corte": "2026-11-15", "origen": "esp32"}
    servicio.al_mensaje(cliente, None, Mensaje("inventario/manzana/pronostico", json.dumps(pronostico)))
    datos = json.loads(cliente.ultimo("inventario/manzana/stock"))
    assert (datos["stock"], datos["pronostico_7d"], datos["comprar"], datos["lunes"]) == (30, 52, 22, 9), datos
    assert "Compra unas 22" in cliente.ultimo("inventario/alerta")

    # formulario de Home Assistant: vender 5 manzanas (HA envía la cantidad como "5.0")
    alertas = sum(t == "inventario/alerta" for t, _ in cliente.mensajes)
    servicio.al_mensaje(cliente, None, Mensaje("inventario/form/producto/set", "Manzana"))
    servicio.al_mensaje(cliente, None, Mensaje("inventario/form/cantidad/set", "5.0"))
    servicio.al_mensaje(cliente, None, Mensaje("inventario/form/registrar", "salida"))
    datos = json.loads(cliente.ultimo("inventario/manzana/stock"))
    assert (datos["stock"], datos["comprar"]) == (25, 27), datos
    assert cliente.ultimo("inventario/ultimo_movimiento").startswith("Venta de Manzana: 5 unidades")
    assert sum(t == "inventario/alerta" for t, _ in cliente.mensajes) == alertas  # ya estaba en alerta: no repite

    # mensajes que se deben ignorar sin romper el servicio
    servicio.al_mensaje(cliente, None, Mensaje("inventario/manzana/pronostico", '{"total_7d": 99}'))  # etapa 1, sin corte
    for tema, texto in [("inventario/movimiento", "no es json"),
                        ("inventario/movimiento", '{"producto": "manzana", "tipo": "salida", "cantidad": -3}'),
                        ("inventario/form/producto/set", "Pera"),
                        ("inventario/form/cantidad/set", "inf"),
                        ("inventario/manzana/pronostico", '{"total_7d": 1, "corte": "ayer"}')]:
        servicio.al_mensaje(cliente, None, Mensaje(tema, texto))
    assert inv.ultimo_pronostico(db, "manzana")["total_7d"] == 52
    assert inv.stock(db, "manzana") == 25

    # historial para el ESP32: llega hasta ayer, así que la venta de hoy todavía no cuenta
    inv.registrar(db, "manzana", "salida", 4, fecha=date.today() - timedelta(days=1))
    servicio.al_mensaje(cliente, None, Mensaje("inventario/recalcular", "ahora"))
    h = json.loads(cliente.ultimo("inventario/manzana/historial"))
    assert len(h["reciente"]) == 28 and len(h["anio"]) == 7
    assert h["reciente"][-1] == 4 and h["corte"] == (date.today() - timedelta(days=1)).isoformat()
    assert h["dia"] == date.today().weekday()


def prueba_importar_csv(tmp=Path(__file__).resolve().parent / "_prueba.csv"):
    tmp.write_text("fecha,producto,tipo,cantidad\n2026-01-05,pan,entrada,20\n2026-01-06,pan,salida,3\n", encoding="utf-8")
    try:
        db = inv.abrir(":memory:")
        assert inv.importar_csv(db, tmp) == 2
        assert inv.productos(db) == [("pan", "Pan")] and inv.stock(db, "pan") == 17
        tmp.write_text("fecha,producto,tipo,cantidad\n2026-01-07,pan,salida,x\n", encoding="utf-8")
        try:
            inv.importar_csv(db, tmp)
        except ValueError as e:
            assert "línea 2" in str(e)
        else:
            raise AssertionError("debió rechazar la cantidad 'x'")
        assert inv.stock(db, "pan") == 17  # el archivo con errores no deja nada a medias
    finally:
        tmp.unlink()


def prueba_cargar_env(tmp=Path(__file__).resolve().parent / "_prueba.env"):
    tmp.write_text('# comentario\nPRUEBA_HOST="192.168.1.5" // ip de la red\nPRUEBA_USER=esp32\n'
                   "PRUEBA_PASS='a#b//c'\n", encoding="utf-8")
    try:
        inv.cargar_env(tmp)
        assert (os.environ["PRUEBA_HOST"], os.environ["PRUEBA_USER"], os.environ["PRUEBA_PASS"]) == ("192.168.1.5", "esp32", "a#b//c")
    finally:
        tmp.unlink()


if __name__ == "__main__":
    pruebas = [f for nombre, f in sorted(globals().items()) if nombre.startswith("prueba_")]
    for prueba in pruebas:
        prueba()
        print(f"OK  {prueba.__name__}")
    print(f"{len(pruebas)} pruebas pasaron")
