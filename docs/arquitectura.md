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
                    Celular (WiFi local)
                 ↙                       ↘
┌────────── ESP32-S3 ──────────┐        ┌─────────────── Raspberry Pi ───────────────┐
│ • Página web propia:         │        │ Home Assistant                             │
│   registrar salidas y ver    │  MQTT  │  • Mosquitto (broker MQTT)                 │
│   el pronóstico              │ ─────► │  • Sensores de pronóstico por producto     │
│ • Historial en memoria flash │        │  • Dashboard (app o navegador)             │
│ • MLP int8 (TinyML)          │        │  • Automatización de reabastecimiento      │
│   → pronóstico a 7 días      │        │  • Base de datos con el historial completo │
└──────────────────────────────┘        │  • Assist + Ollama (preguntas en lenguaje  │
                                        │    natural)                                │
                                        └────────────────────────────────────────────┘

      PC de desarrollo (una sola vez): Python entrena el modelo → model.h → firmware del ESP32
```

## 4. Función de cada componente

| Componente | Función | Lenguaje |
|---|---|---|
| **PC de desarrollo** | Entrena y compara los modelos, cuantiza el elegido a int8 y lo exporta como `model.h`. No forma parte del sistema en operación. | Python |
| **ESP32-S3** | Registra las salidas de inventario, guarda el historial en su memoria flash y **ejecuta el modelo TinyML** para pronosticar los próximos 7 días. Ofrece su propia página web y publica los resultados por MQTT. Funciona aunque Home Assistant esté apagado. | C++, HTML/JS |
| **Raspberry Pi** | Servidor local. Ejecuta Home Assistant, el broker MQTT, la base de datos y, si la capacidad lo permite, Ollama. | — |
| **Home Assistant** | Centro de control: recibe el pronóstico como sensores, lo muestra en el celular, genera alertas de reabastecimiento y permite hacer preguntas por Assist. | YAML |
| **Base de datos** | Guarda el historial completo de salidas y pronósticos (el ESP32 solo conserva lo necesario para el modelo). Sirve para reentrenar el modelo con datos propios. | — |
| **Ollama** | Agente de IA local. Interpreta preguntas en lenguaje natural y responde a partir de los sensores de Home Assistant. **No calcula el pronóstico**: lo lee. | — |

## 5. Ejemplo de flujo

En resumen: **el ESP32 calcula el pronóstico, Home Assistant lo muestra y lo vigila, y Ollama permite preguntarlo en lenguaje natural**, todo dentro de la red WiFi local.

1. **Lunes, 10 a. m.** El usuario saca 3 manzanas y lo registra desde el celular en la página del ESP32.
2. El ESP32 guarda "lunes: 3 manzanas" en su historial y lo publica por MQTT; Home Assistant lo almacena en la base de datos.
3. **A medianoche**, el ESP32 ejecuta el modelo con los días anteriores como entrada y obtiene: mar 6, mié 6, jue 7, vie 8, sáb 9, dom 7, lun 9 (52 en total).
4. El ESP32 publica el pronóstico por MQTT:

   ```json
   {"total_7d": 52, "martes": 6, "miercoles": 6, "jueves": 7, "viernes": 8, "sabado": 9, "domingo": 7, "lunes": 9}
   ```

5. Home Assistant actualiza el sensor `sensor.pronostico_manzana_7d = 52`, con el detalle por día como atributos.
6. Hay 30 manzanas en stock, menos que el pronóstico, así que Home Assistant envía una notificación: "Te vas a quedar sin manzanas, compra unas 22".
7. El usuario pregunta en la app de Home Assistant: "¿Cuántas manzanas podría vender el lunes?"
8. Ollama lee el sensor y responde: "Para el lunes se esperan unas 9 manzanas; en toda la semana, 52".

## 6. Preguntas en lenguaje natural (Home Assistant + Ollama)

Home Assistant y Ollama permiten preguntarle al sistema como a una persona, por texto o por voz, desde la app del celular:

> **Usuario:** ¿Cuántas manzanas podría vender el lunes?
> **Asistente:** Para el lunes se esperan unas 9 manzanas. En total, esta semana se pronostican 52.

### Funcionamiento

```
Pregunta → Assist (Home Assistant) → Ollama (LLM local) → lee sensor.pronostico_manzana_7d
                                                         → atributo "lunes" = 9
                                                         → redacta la respuesta
```

1. **Assist** es el asistente integrado en Home Assistant. Recibe la pregunta desde la app o el navegador.
2. **Ollama** se configura en Home Assistant como *agente de conversación* (integración *Ollama*, con la opción para que el modelo acceda a Home Assistant).
3. Los sensores de pronóstico se **exponen** al asistente (*Ajustes → Asistentes de voz → Exponer*). El LLM solo ve las entidades expuestas.
4. El LLM lee el valor y los atributos del sensor y redacta la respuesta en lenguaje natural.

### Reparto de funciones

| Pregunta | Quién la resuelve |
|---|---|
| ¿Cuánto se venderá el lunes? | El **modelo TinyML** calcula el número; **Ollama** lo lee y lo explica. |
| ¿Qué tengo que comprar esta semana? | Ollama compara el pronóstico con el stock y lo resume. |
| ¿Por qué el pronóstico subió? | Ollama puede explicar a partir de los datos disponibles (por ejemplo, que el fin de semana se vende más). |

El LLM no inventa el pronóstico: si un sensor no está expuesto, no tiene el dato. Para que responda por días, el pronóstico diario debe publicarse como atributo del sensor (paso 4 del flujo).

### Requisitos

- Un modelo pequeño con soporte de herramientas (*tool calling*), por ejemplo `qwen2.5:3b` o `llama3.2:3b`.
- En una Raspberry Pi 5 de 8 GB funciona, pero lento. Si no alcanza, Ollama se instala en un PC de la misma red y el sistema sigue siendo local.

## 7. Operación sin conexión

| Falla | Comportamiento |
|---|---|
| Sin internet | El sistema funciona completo: todos los componentes están en la red local. |
| Home Assistant apagado | El ESP32 sigue registrando y pronosticando; su página web sigue disponible. |
| ESP32 apagado | Home Assistant muestra el último pronóstico recibido. |
| Ollama apagado | El dashboard y las alertas siguen funcionando; solo se pierden las preguntas en lenguaje natural. |

## 8. Decisiones pendientes

1. **Dónde se ejecuta el pronóstico.** El documento del proyecto menciona un "servicio Python" (en la Raspberry Pi), mientras que esta arquitectura lo ejecuta en el ESP32 con TinyML. Propuesta: el ESP32 ejecuta el modelo y la Raspberry Pi corre el mismo modelo en Python como respaldo. La sección 6 de `ml/notebooks/README.md` describe hoy la variante de la Raspberry Pi, y debe actualizarse cuando se decida.
2. **Uso de la cámara.** Por confirmar si es obligatoria. Si lo es, puede identificar el producto al registrar una salida.
3. **Historial mínimo.** El modelo actual necesita un año de historial por producto (ver `docs/modelos.md`, sección 9). Para la demo hay que precargar un historial o entrenar una variante sin la variable anual.
4. **Componentes marcados con asterisco** (agente de IA, base de datos): confirmar si son obligatorios.

## 9. Entorno de exploración y proyecto final

Home Assistant es el mismo programa en el PC y en la Raspberry Pi. Durante la exploración se instala en el PC; en el proyecto final, en la Raspberry Pi. La configuración se traslada con un backup de Home Assistant.

| Componente | Función | Ahora (exploración) | Proyecto final |
|---|---|---|---|
| PC | Entrenar el modelo en Python (v0.1 hecha) | ✅ | Solo para reentrenar |
| ESP32-S3 | Registrar salidas, guardar el historial y ejecutar el modelo | Se programa desde el PC | Igual |
| Home Assistant | Mostrar el pronóstico, enviar alertas y responder preguntas | Máquina virtual en el PC | Raspberry Pi |
| Mosquitto (MQTT) | Mensajería entre el ESP32 y Home Assistant | Add-on en la máquina virtual | Raspberry Pi |
| Base de datos | Historial completo, para reentrenar | Dentro de Home Assistant | Raspberry Pi |
| Ollama | Entender las preguntas y responderlas | PC | Raspberry Pi o un PC de la red |

### Instalación en el PC

1. Instalar un programa de máquinas virtuales (VirtualBox o virt-manager).
2. Descargar la imagen oficial de **Home Assistant OS** (`.vdi` para VirtualBox, `.qcow2` para virt-manager) y arrancarla en una máquina virtual con red en modo puente (*bridge*), para que el ESP32 y el celular la encuentren en la red local.
3. Instalar los add-ons Mosquitto y ESPHome desde la tienda de add-ons.

Se usa Home Assistant OS porque es la única variante que incluye la tienda de add-ons. Las instalaciones con Docker o desde la configuración de NixOS no la traen.

### Paso a la Raspberry Pi

1. En la máquina virtual: *Ajustes → Sistema → Copias de seguridad → Crear copia*.
2. Instalar Home Assistant OS en la Raspberry Pi y, en la pantalla inicial, elegir **restaurar desde copia de seguridad**.
