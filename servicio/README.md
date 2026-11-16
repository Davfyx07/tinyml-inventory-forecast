# Servicio de inventario

Programa en Python que guarda el inventario en una base de datos SQLite y lo conecta, por MQTT, con el ESP32 y con Home Assistant.

```
Home Assistant ──(formulario: venta o entrada)──► servicio ──► SQLite
       ▲                                            │
       │ stock, pronóstico, comprar, alertas        │ historial de ventas de cada producto
       │                                            ▼
       └───────────────── pronóstico ────────── ESP32 (red int8)
```

| Responsabilidad | Detalle |
|---|---|
| Movimientos | Registra entradas y salidas. El stock no se edita: se calcula como entradas menos salidas. |
| Historial para el modelo | Cada día, después de medianoche, envía al ESP32 las ventas de cada producto hasta el día anterior: 28 días recientes, la misma semana del año anterior y su promedio base (los mismos cortes que `armar_pistas()` en el notebook 03). |
| Pronósticos | Guarda el pronóstico que devuelve el ESP32 y calcula las unidades a comprar (`pronóstico - stock`, mínimo 0). El LLM no hace esa cuenta. |
| Home Assistant | Crea por descubrimiento MQTT los sensores de cada producto y el formulario de movimientos; no requiere configuración YAML. |
| Alertas | Publica un mensaje en `inventario/alerta` cuando las unidades a comprar de un producto pasan de 0 a más. |

## Archivos

| Archivo | Contenido |
|---|---|
| `inventario.py` | Servicio, base de datos y comandos de carga |
| `preparar_demo.py` | Genera `demo.csv` con dos años de ventas de 5 productos de Kaggle, con fechas que terminan ayer |
| `prueba_inventario.py` | Pruebas sin broker ni ESP32, incluida la comparación del historial con el vector de prueba del firmware |
| `.env.ejemplo` | Plantilla de la configuración de MQTT |

`.env`, `inventario.db` y `demo.csv` no se versionan.

## Uso

Desde la raíz del repositorio, con el entorno `.venv` activado:

```bash
pip install -r servicio/requirements.txt
cp servicio/.env.ejemplo servicio/.env                 # completar IP, usuario y clave de MQTT
python servicio/prueba_inventario.py                   # 4 pruebas
python servicio/preparar_demo.py                       # solo para la demostración
python servicio/inventario.py importar servicio/demo.csv
python servicio/inventario.py                          # deja el servicio en ejecución (Ctrl+C para detenerlo)
```

Otros comandos:

```bash
python servicio/inventario.py producto platano "Plátano"   # crea o renombra un producto
```

El formato del CSV es `fecha,producto,tipo,cantidad`, con fechas `AAAA-MM-DD`, `tipo` igual a `entrada` o `salida` y cantidades enteras positivas. Si una fila es inválida, no se importa ninguna.

## Base de datos

| Tabla | Columnas |
|---|---|
| `productos` | `id` (se usa en los temas MQTT: minúsculas, números y `_`), `nombre` |
| `movimientos` | `fecha`, `producto`, `tipo` (`entrada` o `salida`), `cantidad`, `registrado` |
| `pronosticos` | `producto`, `corte` (último día con ventas conocidas), `total`, `detalle` (JSON del ESP32), `recibido` |

## Temas MQTT

| Tema | Dirección | Contenido |
|---|---|---|
| `inventario/<producto>/historial` | servicio → ESP32 (retenido) | `{"corte", "dia", "reciente"[28], "anio"[7], "base_anio"}` |
| `inventario/<producto>/pronostico` | ESP32 → servicio y Home Assistant (retenido) | `{"total_7d", "inicio", "lunes", ..., "domingo", "corte", "origen", "microsegundos"}` |
| `inventario/<producto>/stock` | servicio → Home Assistant (retenido) | `{"producto", "stock", "pronostico_7d", "comprar", "lunes", ..., "domingo"}` |
| `inventario/movimiento` | cualquier cliente → servicio | `{"producto": "manzana", "tipo": "salida", "cantidad": 3}` |
| `inventario/form/...` | Home Assistant ↔ servicio | Formulario: producto, cantidad y botones |
| `inventario/recalcular` | Home Assistant → servicio | Reenvía los historiales al ESP32 |
| `inventario/alerta` | servicio → Home Assistant | Texto de la alerta de reabastecimiento |

## Despliegue

Durante el desarrollo, el servicio se ejecuta en el PC. Home Assistant OS no permite ejecutar programas de Python fuera de sus aplicaciones (complementos), por lo que en la Raspberry Pi se empaquetará como aplicación local; así se incluye en la copia de seguridad de Home Assistant.
