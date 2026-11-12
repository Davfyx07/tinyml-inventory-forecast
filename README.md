# TinyML Inventory Forecast

> Work in progress · En desarrollo

[English](#english) · [Español](#español)

---

## English

7-day inventory consumption forecasting with TinyML on an ESP32-S3, fully offline, integrated with Home Assistant.

### Status (v0.1: first training)

- Model selection for the 7-day forecast, using the Kaggle *Store Item Demand Forecasting* dataset. Methodology and results (in Spanish): [ml/notebooks/README.md](ml/notebooks/README.md).
- Best models: LightGBM and a 5,063-parameter MLP, with a weekly WAPE of 5.2–5.3% versus 6.5% for Chronos-Bolt and the seasonal naive baseline. The MLP (20 KB) is the ESP32-S3 candidate.
- v0.1 artifacts: figures in `ml/notebooks/figuras/v0.1/`, trained MLP in `ml/models/v0.1/red.keras`.
- Docs (Spanish): [system architecture](docs/arquitectura.md) · [models explained](docs/modelos.md).
- Pending: int8 quantization for the ESP32-S3 (notebook 03), forecasting service on the Raspberry Pi, Home Assistant integration and firmware.

---

## Español

Pronóstico del consumo de inventario a 7 días con TinyML en un ESP32-S3, sin conexión a internet e integrado con Home Assistant.

### Estado (v0.1: primer entrenamiento)

- Selección del modelo de pronóstico a 7 días con el conjunto de datos *Store Item Demand Forecasting* de Kaggle. Metodología y resultados: [ml/notebooks/README.md](ml/notebooks/README.md).
- Mejores modelos: LightGBM y un MLP de 5,063 parámetros, con un WAPE semanal de 5.2–5.3%, frente a 6.5% de Chronos-Bolt y del modelo naive estacional. El MLP (20 KB) es el candidato para el ESP32-S3.
- Artefactos de la v0.1: figuras en `ml/notebooks/figuras/v0.1/` y MLP entrenado en `ml/models/v0.1/red.keras`.
- Documentación: [arquitectura del sistema](docs/arquitectura.md) · [explicación de los modelos](docs/modelos.md).
- Pendiente: cuantización int8 para el ESP32-S3 (notebook 03), servicio de pronóstico en la Raspberry Pi, integración con Home Assistant y firmware.
