# Home Assistant

Configuración que se agrega a mano en Home Assistant. Los sensores y el formulario de movimientos no están aquí: los crea el [servicio de inventario](../servicio/README.md) por descubrimiento MQTT.

## Entidades que crea el servicio

| Entidad | Contenido |
|---|---|
| `sensor.stock_<producto>` | Stock actual. Sus atributos incluyen el nombre, el pronóstico de 7 días, las unidades a comprar y el pronóstico por día. Las instrucciones del agente leen estos atributos. |
| `sensor.pronostico_<producto>_7d` | Pronóstico de los próximos 7 días calculado por el ESP32, con un atributo por día de la semana |
| `sensor.comprar_<producto>` | Unidades a comprar para cubrir el pronóstico (`pronóstico - stock`, mínimo 0) |
| `select.inventario_producto`, `number.inventario_cantidad` | Formulario: producto y cantidad |
| `button.registrar_venta`, `button.registrar_entrada` | Registran el movimiento con el producto y la cantidad del formulario |
| `button.recalcular_pronostico` | Reenvía los historiales al ESP32 para recalcular |
| `sensor.inventario_ultimo_movimiento` | Confirmación del último movimiento registrado |

## Archivos

| Archivo | Dónde se pega |
|---|---|
| `agente_instrucciones.jinja` | *Dispositivos y servicios → Ollama →* engranaje del agente `Inventario` → *Instrucciones* (versión 5) |
| `evaluar_agente.py` | No se pega: evalúa las instrucciones contra Ollama desde el PC (sección siguiente) |
| `automatizacion_alerta.yaml` | *Automatizaciones → Crear automatización →* menú ⋮ → *Editar en YAML* |
| `tarjeta_inventario.yaml` | *Configuración → Tableros → Agregar tablero* (la URL debe llevar un guion, p. ej. `inventario-tienda`) → lápiz → *Agregar tarjeta → Manual* |

## Instrucciones del agente

El agente usa `qwen2.5:1.5b` sin herramientas: la plantilla inserta en cada pregunta los datos de todos los sensores `sensor.stock_*`. El texto final que recibe el modelo se revisa pegando la plantilla en *Herramientas para desarrolladores → Plantilla*.

### Evolución

| Versión | Productos | Cambio principal |
|---|---|---|
| 1 a 3 | Manzana | Reglas, ejemplos de rechazo y compra calculada en la plantilla |
| 4 | Todos | Ciclo sobre `sensor.stock_*`; datos de la base de datos; regla y ejemplo para productos inexistentes |
| 5 | Todos | Un bloque por producto con una línea por dato; ventas de hoy y de mañana calculadas en la plantilla; resumen de productos por comprar; ejemplos de respuesta generados con los datos reales; ejemplos de rechazo antes de los datos |

### Evaluación

`evaluar_agente.py` renderiza la plantilla con los datos de `servicio/inventario.db`, envía cada pregunta 3 veces a Ollama y cuenta las respuestas que contienen el valor esperado. Resultados del 2026-11-15 con `qwen2.5:1.5b` y los datos de la demostración (la versión 5 se ejecutó dos veces; se indica el rango):

| Pregunta | Versión 4 | Versión 5 |
|---|---|---|
| Compra, stock, ventas de un día y de la semana | 6/15 | 14/15 |
| Ventas de mañana | No se evaluó | 3/3 |
| Lista de productos por comprar | 0/3 | 1/3 a 3/3 |
| Producto inexistente (peras, fresas) | 3/3 (solo peras) | 2/6 a 3/6 |
| Fuera de tema (código, chiste, hora) | 2/9 | 6/9 a 7/9 |
| **Total** | **11/30** | **27/36 a 29/36** |

Hallazgos:

- La versión 4 tenía un solo ejemplo, el de un producto inexistente ("¿Cuántas peras tengo?"), y el modelo lo aplicaba a casi todas las preguntas, en especial cuando el producto se escribía en plural ("manzanas" frente a "Manzana").
- Con 1.5B parámetros, el modelo imita la forma de los ejemplos más que las reglas. Los ejemplos de respuesta correcta, generados con los datos reales, eliminaron casi todos los errores en las preguntas de inventario.
- El modelo no resuelve referencias en dos pasos ("mañana" → día de la semana → valor): la plantilla entrega el valor directamente.
- Limitación vigente: ante un producto inexistente pero parecido a uno real (peras frente a manzanas), el modelo puede responder con los datos del producto real. Un modelo mayor (`qwen2.5:3b`, unos 2 GB) es la siguiente opción si este error resulta relevante.

Con muchos productos, el texto puede superar la ventana de contexto de 2048 tokens; en ese caso se aumenta en la configuración del agente.
