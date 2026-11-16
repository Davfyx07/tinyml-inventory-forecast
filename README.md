# TinyML Inventory Forecast

> Work in progress · En desarrollo

[English](#english) · [Español](#español)

---

## English

7-day inventory consumption forecasting with TinyML on an ESP32-S3, fully offline, integrated with Home Assistant and a local LLM.

```
Phone (Home Assistant app) ── record sales and restocks ──► inventory service (Python + SQLite)
        ▲                                                         │ daily sales history per product
        │ stock, forecast, units to buy, alerts                   ▼
        └──────────────────────── 7-day forecast ◄──────── ESP32-S3 (int8 MLP, TFLite Micro)
Assist + Ollama (qwen2.5:1.5b): answers questions about stock, forecast and purchases
```

### Status (v0.2: on-device inference)

| Stage | Result |
|---|---|
| Model selection ([report](ml/notebooks/README.md), Spanish) | 6 models compared (statistical baselines, Chronos-Bolt, LightGBM and an MLP) on the Kaggle *Store Item Demand Forecasting* dataset, with a final 52-week backtest over 2017. A 5,063-parameter MLP reaches a weekly WAPE of 5.3%, versus 6.5% for Chronos-Bolt and the seasonal naive baseline. |
| int8 quantization (notebook 03) | Full-integer TensorFlow Lite model of 7,744 bytes with per-tensor weights; weekly WAPE 5.28%, identical to float32. |
| On-device inference ([`firmware/`](firmware)) | The ESP32-S3 runs the model with TensorFlow Lite Micro: 0.49 ms per forecast, 780-byte tensor arena, identical results to Python on 5 test vectors checked at every boot. |
| Inventory service ([`servicio/`](servicio)) | Python + SQLite: records sales and restocks, computes stock and units to buy, sends each product's history to the ESP32 over MQTT and creates the Home Assistant entities through MQTT discovery. |
| Home Assistant + local LLM ([`homeassistant/`](homeassistant)) | Dashboard, restock alert and a conversational agent on Ollama without tools; prompt versions evaluated with a script against the local model (11/30 → 27–29/36 correct answers). |

Architecture and design decisions (Spanish): [docs/arquitectura.md](docs/arquitectura.md) · [models explained](docs/modelos.md).

Pending: packaging the inventory service as a Home Assistant add-on for the Raspberry Pi; real store data (the Kaggle history plays the role of the store).

---

## Español

Pronóstico del consumo de inventario a 7 días con TinyML en un ESP32-S3, sin conexión a internet e integrado con Home Assistant y un LLM local.

```
Celular (app de Home Assistant) ── registrar ventas y entradas ──► servicio de inventario (Python + SQLite)
        ▲                                                                │ historial diario de ventas por producto
        │ stock, pronóstico, unidades a comprar, alertas                 ▼
        └──────────────────────── pronóstico a 7 días ◄──────── ESP32-S3 (MLP int8, TFLite Micro)
Assist + Ollama (qwen2.5:1.5b): responde preguntas sobre stock, pronóstico y compras
```

### Estado (v0.2: inferencia en el microcontrolador)

| Etapa | Resultado |
|---|---|
| Selección del modelo ([informe](ml/notebooks/README.md)) | 6 modelos comparados (referencias estadísticas, Chronos-Bolt, LightGBM y un MLP) sobre el conjunto *Store Item Demand Forecasting* de Kaggle, con un backtesting final de 52 semanas sobre 2017. Un MLP de 5,063 parámetros obtiene un WAPE semanal de 5.3 %, frente a 6.5 % de Chronos-Bolt y del modelo naive estacional. |
| Cuantización int8 (notebook 03) | Modelo TensorFlow Lite entero de 7,744 bytes, con pesos cuantizados por capa; WAPE semanal 5.28 %, igual que en float32. |
| Inferencia en el ESP32-S3 ([`firmware/`](firmware)) | El ESP32-S3 ejecuta el modelo con TensorFlow Lite Micro: 0.49 ms por pronóstico, arena de 780 bytes y resultados idénticos a Python en 5 vectores de prueba que se verifican en cada arranque. |
| Servicio de inventario ([`servicio/`](servicio)) | Python + SQLite: registra ventas y entradas, calcula el stock y las unidades a comprar, envía al ESP32 el historial de cada producto por MQTT y crea las entidades de Home Assistant por descubrimiento MQTT. |
| Home Assistant + LLM local ([`homeassistant/`](homeassistant)) | Tablero, alerta de reabastecimiento y agente conversacional en Ollama sin herramientas; versiones de las instrucciones evaluadas con un script contra el modelo local (de 11/30 a 27–29/36 respuestas correctas). |

Arquitectura y decisiones de diseño: [docs/arquitectura.md](docs/arquitectura.md) · [explicación de los modelos](docs/modelos.md).

Pendiente: empaquetar el servicio de inventario como aplicación de Home Assistant para la Raspberry Pi; datos de una tienda real (el historial de Kaggle cumple el papel de la tienda).

### Estructura

| Carpeta | Contenido |
|---|---|
| `ml/` | Notebooks de comparación de modelos (01, 02) y cuantización (03), modelos por versión |
| `firmware/` | Firmware del ESP32-S3 (PlatformIO): inferencia con TFLite Micro y MQTT |
| `servicio/` | Servicio de inventario: SQLite, MQTT y carga de datos |
| `homeassistant/` | Instrucciones del agente, automatización, tarjeta del tablero y evaluación del agente |
| `docs/` | Arquitectura y explicación de los modelos |
