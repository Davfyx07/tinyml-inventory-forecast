"""Genera servicio/demo.csv: dos años de ventas de 5 productos de Kaggle, con fechas que terminan ayer.

Las fechas se desplazan un múltiplo de 7 días para conservar el día de la semana: el patrón semanal de Kaggle
(los domingos se vende más) debe caer en el mismo día que vio el modelo al entrenar.
Ejecutarlo el mismo día en que se importa, para que el historial llegue hasta ayer.

Uso (desde la raíz del repositorio):  python servicio/preparar_demo.py
"""
import csv
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
KAGGLE = RAIZ / "ml" / "data" / "train.csv"
SALIDA = Path(__file__).resolve().parent / "demo.csv"
TIENDA = "1"
PRODUCTOS = {"1": "manzana", "2": "pan", "3": "leche", "4": "huevos", "5": "arroz"}  # artículo de Kaggle → producto
DIAS_HISTORIAL = 2 * 364  # el modelo necesita al menos 392 días (28 recientes + la misma semana del año anterior)
# unidades que quedan después de la carga: unos productos alcanzan para la semana y otros no
STOCK_FINAL = {"manzana": 30, "pan": 350, "leche": 150, "huevos": 120, "arroz": 60}

ventas = {}
with open(KAGGLE, newline="") as f:
    for fila in csv.DictReader(f):
        if fila["store"] == TIENDA and fila["item"] in PRODUCTOS:
            ventas[PRODUCTOS[fila["item"]], date.fromisoformat(fila["date"])] = int(fila["sales"])

ayer = date.today() - timedelta(days=1)
ultimo = max(fecha for _, fecha in ventas)
fin = ultimo - timedelta(days=(ultimo.weekday() - ayer.weekday()) % 7)  # último día de Kaggle que cae el mismo día de la semana que ayer
desfase = ayer - fin                                                    # múltiplo de 7
inicio = fin - timedelta(days=DIAS_HISTORIAL - 1)
assert desfase.days % 7 == 0 and (inicio + desfase).weekday() == inicio.weekday()

with open(SALIDA, "w", newline="", encoding="utf-8") as f:
    escritor = csv.writer(f)
    escritor.writerow(["fecha", "producto", "tipo", "cantidad"])
    for producto in PRODUCTOS.values():
        filas = [(fecha + desfase, cantidad) for (p, fecha), cantidad in sorted(ventas.items())
                 if p == producto and inicio <= fecha <= fin and cantidad > 0]
        # una entrada inicial que cubre todas las ventas y deja el stock final del producto
        escritor.writerow([(inicio + desfase).isoformat(), producto, "entrada", sum(c for _, c in filas) + STOCK_FINAL[producto]])
        escritor.writerows([fecha.isoformat(), producto, "salida", cantidad] for fecha, cantidad in filas)

print(f"Guardado {SALIDA}: {len(PRODUCTOS)} productos, ventas de Kaggle del {inicio} al {fin} "
      f"movidas al {inicio + desfase} - {ayer}")
