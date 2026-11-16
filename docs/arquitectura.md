# Arquitectura del sistema

## 1. Objetivo

Proyecto 5 de *Home Assistant and ESP32-S3 TinyML integration projects*:

> Pronosticar cuántas unidades de cada producto se consumirán en los próximos 7 días, usando el historial de salidas del inventario.

## 2. Requisitos del proyecto

| Tipo | Requisito |
|---|---|
| Hardware | Raspberry Pi (Home Assistant), ESP32-S3 (cámara, modelo TinyML), sensores |
| Software | Integración con Home Assistant, modelo TinyML, agente de IA\*, base de datos\*, Ollama local |
| Restricción | Todo se ejecuta en la red local, sin internet. La Raspberry Pi puede reemplazarse por otro equipo si no alcanza. |

\* Por confirmar con el profesor si estos componentes son obligatorios u opcionales.

## 3. Diagrama

```
                         Celular (app de Home Assistant)
                registrar ventas y entradas · ver stock y pronóstico · preguntar
                                        │
┌──────────────────────────── Raspberry Pi ─────────────────────────────┐
│ Home Assistant                         Servicio de inventario          │
│  • Mosquitto (broker MQTT)    MQTT     (aplicación local, Python)      │
│  • Formulario de movimientos ◄───────► • SQLite: productos,            │
│  • Sensores por producto                 movimientos y pronósticos     │
│  • Alerta de reabastecimiento          • Stock = entradas - salidas    │
│  • Assist + Ollama                     • Unidades a comprar            │
└──────────────────────────────────────────────┬────────────────────────┘
                                   historial ▼ │ ▲ pronóstico (MQTT)
                                ┌──────────── ESP32-S3 ────────────┐
                                │ 42 entradas → MLP int8 (TinyML)  │
                                │ → pronóstico a 7 días            │
                                └──────────────────────────────────┘

      PC de desarrollo (una sola vez): Python entrena el modelo → model_data.h → firmware del ESP32
```

## 4. Función de cada componente

| Componente | Función | Lenguaje |
|---|---|---|
| **PC de desarrollo** | Entrena y compara los modelos, cuantiza el elegido a int8 y lo exporta como `model_data.h`. No forma parte del sistema en operación. | Python |
| **ESP32-S3** | **Ejecuta el modelo TinyML.** Recibe por MQTT el historial de ventas de cada producto, construye las 42 entradas, ejecuta la red int8 y publica el pronóstico de 7 días. Al encender verifica que su resultado coincide con el de Python ([`firmware/`](../firmware)). | C++ |
| **Servicio de inventario** | Guarda los movimientos en la base de datos, calcula el stock y las unidades a comprar, envía cada día el historial al ESP32 y crea en Home Assistant los sensores y el formulario por descubrimiento MQTT ([`servicio/`](../servicio)). | Python |
| **Base de datos** | SQLite, dentro del servicio. Tablas de productos, movimientos (entradas y salidas) y pronósticos. Conserva el historial completo, que sirve para reentrenar el modelo con datos propios. Un CSV solo se usa para la carga inicial. | SQL |
| **Raspberry Pi** | Servidor local. Ejecuta Home Assistant, el broker MQTT, el servicio de inventario como aplicación local y, si la capacidad lo permite, Ollama. | — |
| **Home Assistant** | Interfaz desde el celular: formulario para registrar ventas y entradas, sensores por producto, alerta de reabastecimiento y preguntas por Assist ([`homeassistant/`](../homeassistant)). | YAML, Jinja |
| **Ollama** | Agente de IA local. Interpreta preguntas en lenguaje natural y responde a partir de los atributos de los sensores de stock. **No calcula el pronóstico ni las compras**: los lee. | — |

## 5. Ejemplo de flujo

En resumen: **el servicio guarda el inventario, el ESP32 calcula el pronóstico, Home Assistant lo muestra y alerta, y Ollama permite preguntarlo en lenguaje natural**, todo dentro de la red WiFi local.

1. **Lunes, 10 a. m.** El usuario vende 3 manzanas y lo registra desde el celular: producto, cantidad y botón *Registrar venta*.
2. Home Assistant envía el movimiento por MQTT; el servicio lo guarda en SQLite y publica el stock actualizado.
3. **Después de medianoche**, el servicio envía al ESP32 el historial de cada producto hasta el día anterior:

   ```json
   {"corte": "2026-11-16", "dia": 1, "reciente": [12, 9, ...], "anio": [8, 6, 6, 7, 8, 9, 7], "base_anio": 7.2}
   ```

4. El ESP32 construye las 42 entradas, ejecuta la red y publica el pronóstico: mar 6, mié 6, jue 7, vie 8, sáb 9, dom 7, lun 9 (52 en total).

   ```json
   {"total_7d": 52, "inicio": "martes", "martes": 6, "miercoles": 6, "jueves": 7, "viernes": 8, "sabado": 9, "domingo": 7, "lunes": 9, "corte": "2026-11-16", "origen": "esp32"}
   ```

5. El servicio guarda el pronóstico y calcula las unidades a comprar: hay 30 manzanas, así que hay que comprar 22. Home Assistant actualiza `sensor.pronostico_manzana_7d`, `sensor.stock_manzana` y `sensor.comprar_manzana`.
6. Como las unidades a comprar pasaron de 0 a 22, el servicio publica una alerta y Home Assistant la envía al celular: "Te vas a quedar sin manzana... Compra unas 22".
7. El usuario pregunta en la app de Home Assistant: "¿Cuántas manzanas podría vender el lunes?"
8. Ollama lee los atributos del sensor de stock y responde: "Para el lunes se esperan unas 9 manzanas; en toda la semana, 52".

## 6. Preguntas en lenguaje natural (Home Assistant + Ollama)

Home Assistant y Ollama permiten preguntarle al sistema como a una persona, por texto o por voz, desde la app del celular:

> **Usuario:** ¿Cuántas manzanas podría vender el lunes?
> **Asistente:** Para el lunes se esperan unas 9 manzanas. En total, esta semana se pronostican 52.

### Funcionamiento

```
Pregunta → Assist (Home Assistant) → instrucciones del agente: la plantilla inserta los datos de
                                     todos los sensor.stock_* (stock, pronóstico, compra, días)
                                   → Ollama (LLM local) redacta la respuesta con esos datos
```

1. **Assist** es el asistente integrado en Home Assistant. Recibe la pregunta desde la app o el navegador.
2. **Ollama** se configura en Home Assistant como *agente de conversación* (integración *Ollama*), **sin herramientas de IA**: el modelo no consulta ni controla entidades.
3. Las instrucciones del agente son una plantilla ([`homeassistant/agente_instrucciones.jinja`](../homeassistant/agente_instrucciones.jinja)) que, en cada pregunta, recorre los sensores de stock e inserta sus atributos como texto.
4. El LLM redacta la respuesta en lenguaje natural a partir de ese texto, y rechaza las preguntas ajenas al inventario.

### Reparto de funciones

| Pregunta | Quién la resuelve |
|---|---|
| ¿Cuánto se venderá el lunes? | El **modelo TinyML** calcula el número; **Ollama** lo lee y lo explica. |
| ¿Qué tengo que comprar esta semana? | El **servicio** calcula las unidades a comprar; Ollama las lee. Los modelos pequeños cometen errores aritméticos, por eso no se les delega la cuenta. |
| ¿Por qué el pronóstico subió? | Ollama puede explicar a partir de los datos disponibles (por ejemplo, que el fin de semana se vende más). |

El LLM no inventa el pronóstico: solo conoce los datos que la plantilla inserta.

### Requisitos

- `qwen2.5:1.5b` (1 GB), que en CPU responde a unos 40 tokens por segundo. Como no usa herramientas, no necesita un modelo con *tool calling*.
- En una Raspberry Pi 5 de 8 GB funciona, pero lento. Si no alcanza, Ollama se instala en un PC de la misma red y el sistema sigue siendo local.

## 7. Operación sin conexión

| Falla | Comportamiento |
|---|---|
| Sin internet | El sistema funciona completo: todos los componentes están en la red local. |
| Home Assistant apagado | No se pueden registrar movimientos desde el celular. El servicio y el ESP32 siguen funcionando y los datos se conservan en la base de datos. |
| ESP32 apagado | Se siguen registrando movimientos; Home Assistant muestra el último pronóstico. Al reconectarse, el ESP32 recibe los historiales retenidos y recalcula. |
| Servicio apagado | No se registran movimientos. Home Assistant muestra los últimos valores publicados. |
| Ollama apagado | El dashboard y las alertas siguen funcionando; solo se pierden las preguntas en lenguaje natural. |

## 8. Decisiones

Tomadas el 2026-11-15:

1. **Dónde se ejecuta el pronóstico.** En el ESP32, con TinyML. El servicio en Python de la Raspberry Pi guarda el inventario y prepara el historial, pero no ejecuta el modelo. La sección 6 de `ml/notebooks/README.md` describe la variante anterior (modelo en la Raspberry Pi) y debe actualizarse.
2. **Dónde se registran los movimientos.** En Home Assistant, con un formulario que crea el servicio por descubrimiento MQTT, en lugar de una página web en el ESP32. Home Assistant ya está en el celular y el ESP32 queda dedicado al modelo. A cambio, sin el servidor no se pueden registrar movimientos.
3. **Base de datos.** SQLite dentro del servicio de inventario. La base de datos de Home Assistant no sirve para este fin: guarda estados de sensores, no movimientos, y por defecto conserva 10 días.
4. **Historial mínimo.** El modelo necesita 392 días de historial por producto (ver `docs/modelos.md`, sección 9). La demostración precarga dos años de ventas de Kaggle con `servicio/preparar_demo.py`, con las fechas desplazadas en múltiplos de 7 días para conservar el día de la semana.

Pendientes:

1. **Uso de la cámara.** Por confirmar si es obligatoria. Si lo es, puede identificar el producto al registrar una salida.
2. **Despliegue del servicio en la Raspberry Pi.** Home Assistant OS no ejecuta programas de Python sueltos: el servicio se empaquetará como aplicación local o se ejecutará en el mismo PC que Ollama.

## 9. Entorno de exploración y proyecto final

Home Assistant es el mismo programa en el PC y en la Raspberry Pi. Durante la exploración se instala en el PC; en el proyecto final, en la Raspberry Pi. La configuración se traslada con un backup de Home Assistant.

| Componente | Función | Ahora (exploración) | Proyecto final |
|---|---|---|---|
| PC | Entrenar el modelo en Python (v0.1 hecha) | ✅ | Solo para reentrenar |
| ESP32-S3 | Ejecutar el modelo con el historial que recibe | Se programa desde el PC | Igual |
| Home Assistant | Registrar movimientos, mostrar el pronóstico, enviar alertas y responder preguntas | Máquina virtual en el PC | Raspberry Pi |
| Mosquitto (MQTT) | Mensajería entre el ESP32, el servicio y Home Assistant | Aplicación en la máquina virtual | Raspberry Pi |
| Servicio de inventario + SQLite | Movimientos, stock, historial para el ESP32 y unidades a comprar | PC (Python) | Aplicación local en la Raspberry Pi |
| Ollama | Entender las preguntas y responderlas | PC | Raspberry Pi o un PC de la red |

### Instalación en el PC

1. Instalar un programa de máquinas virtuales (VirtualBox o virt-manager).
2. Descargar la imagen oficial de **Home Assistant OS** (`.vdi` para VirtualBox, `.qcow2` para virt-manager) y arrancarla en una máquina virtual con red en modo puente (*bridge*), para que el ESP32 y el celular la encuentren en la red local.
3. Instalar los add-ons Mosquitto y ESPHome desde la tienda de add-ons.

Se usa Home Assistant OS porque es la única variante que incluye la tienda de add-ons. Las instalaciones con Docker o desde la configuración de NixOS no la traen.

### Paso a la Raspberry Pi

1. En la máquina virtual: *Ajustes → Sistema → Copias de seguridad → Crear copia*.
2. Instalar Home Assistant OS en la Raspberry Pi y, en la pantalla inicial, elegir **restaurar desde copia de seguridad**.
