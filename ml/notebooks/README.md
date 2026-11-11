# Pronóstico de consumo a 7 días: explicación completa

Este documento explica qué hace el notebook `01_pronostico_7_dias.ipynb`, de dónde salen los datos, qué es cada modelo, por qué lo elegí y cómo leer los resultados.

---

## 1. El problema en una frase

> Con el historial de cuántas unidades de cada producto salieron por día, predecir cuántas van a salir en los **próximos 7 días**.

En el proyecto completo:

```
ESP32-S3 (cámara + TinyML)  →  registra salidas de productos
        ↓
Base de datos / Home Assistant  →  guarda el historial
        ↓
Servicio Python en la Raspberry Pi  →  ESTE PRONÓSTICO (1 vez al día)
        ↓
Home Assistant (sensores)  →  el agente de Ollama responde "¿cuánto arroz necesito esta semana?"
```

Este notebook es la parte del **servicio Python**: elige qué modelo usar y demuestra que funciona.

---

## 2. Los datos: qué es eso de Kaggle

**Kaggle** es una plataforma de Google donde se publican datasets y competencias de ciencia de datos. Las empresas o la misma plataforma suben un problema con datos y la gente compite por resolverlo mejor.

El dataset que bajaste es de la competencia **"Store Item Demand Forecasting Challenge"**. Su identificador en Kaggle es `demand-forecasting-kernels-only`: "kernels only" significa que en la competencia solo se podía participar con notebooks dentro de Kaggle. Para nosotros eso no importa.

### Los 3 archivos que bajaste

| Archivo | Qué tiene | ¿Lo usamos? |
|---|---|---|
| `train.csv` | Ventas diarias reales: `date, store, item, sales` | **Sí, es el único que sirve** |
| `test.csv` | Fechas de 2018 **sin ventas** (Kaggle las escondió para calificar) | No: sin la respuesta no podemos medir nada |
| `sample_submission.csv` | Ejemplo del formato para enviar respuestas a la competencia | No |

### Qué hay en `train.csv`

- **10 tiendas × 50 productos = 500 series de tiempo** (cada combinación tienda+producto es una serie).
- **5 años diarios**: del 2013-01-01 al 2017-12-31.
- **913,000 filas**. Ventas por día entre 0 y 231 unidades (mediana: 47).
- Sin huecos y casi sin días en cero (0.0001%).

### ¿Por qué este dataset y no datos inventados por mí?

- **Es exactamente tu problema**: unidades por producto por día.
- **No lo hiciste tú.** Si generas datos con tus propias reglas ("los sábados se vende 20% más"), el modelo aprende tus reglas y el resultado "bueno" no demuestra nada. Con datos ajenos no puedes hacer trampa sin querer.
- **Es un benchmark conocido**: mucha gente lo ha usado, así que tus resultados se pueden comparar.

**Ojo:** es un dataset de práctica, muy limpio (sin agotados, sin huecos, sin productos nuevos). Los datos de tu almacén real serán más ruidosos. Por eso el método de evaluación (backtesting) es más importante que el modelo: cuando tengas datos reales, corres la misma comparación y ves cuál gana.

### Cómo conseguir el archivo

El notebook lee `ml/data/train.csv`, que ya está copiado. Si clonas el repo en otra máquina, el CSV **no está en git** (el `.gitignore` ignora `*.csv`), así que hay dos opciones:

1. **Manual:** descargarlo de la página de la competencia en Kaggle y copiar `train.csv` a `ml/data/`.
2. **Con código** (el snippet que encontraste):
   ```python
   import kagglehub
   path = kagglehub.competition_download('demand-forecasting-kernels-only')
   print(path)  # copia train.csv de esa carpeta a ml/data/
   ```
   Para esto necesitas cuenta de Kaggle, tu API token configurado y haber aceptado las reglas de la competencia en su página web.

---

## 3. Conceptos que necesitas antes de ver los modelos

### Serie de tiempo
Una secuencia de valores ordenados por fecha. Aquí: "ventas de producto 1 en tienda 1, día por día".

### Horizonte (`H = 7`)
Cuántos días hacia adelante predecimos. La tarea pide 7.

### Estacionalidad semanal (`season_length = 7`)
Un patrón que se repite cada 7 días. En el notebook (sección 2) se ve claramente: **los fines de semana se vende mucho más que los lunes**. Por eso todos los modelos reciben `season_length=7`: les decimos "busca patrones que se repiten cada semana".

### Backtesting (validación cruzada temporal)
Es la pieza más importante del notebook. La idea:

```
Historial: ════════════════════════════════════════╪═══════╪═══════╪═══════╪═══════╡
                                                  corte1  corte2  corte3  corte4  fin 2017
En el corte 1:  el modelo solo ve ════════════════╡ y predice los 7 días siguientes
                luego comparamos contra lo que pasó de verdad.
Repetimos en los 4 cortes (las últimas 4 semanas de 2017).
```

**¿Por qué no un train/test aleatorio como en otros problemas de ML?** Porque si mezclas fechas al azar, el modelo podría "ver" el martes para predecir el lunes anterior: estaría usando el futuro. En la vida real nunca tienes el futuro, así que la evaluación tampoco debe tenerlo.

**¿Por qué 4 cortes y no 1?** Una sola semana puede ser rara (un feriado, por ejemplo). Con 4 semanas el resultado es más confiable.

### Métricas

| Métrica | Fórmula simple | Cómo leerla |
|---|---|---|
| **MAE** (error absoluto medio) | promedio de \|predicción − real\| | "En promedio me equivoco por X unidades al día, por producto". En unidades: fácil de explicar. |
| **WAPE** (error porcentual ponderado) | suma de errores ÷ suma de ventas reales | "Me equivoco en X% de lo que se vende". Sirve para comparar productos que venden mucho con los que venden poco. |
| **Sesgo** | suma de (predicción − real) ÷ suma de ventas | Positivo: predice de más (sobra inventario). Negativo: predice de menos (te quedas sin stock). |
| **WAPE semanal** | igual que WAPE, pero sumando primero los 7 días | Para reabastecer importa el total de la semana, y los errores diarios se compensan en parte. |
| **Cobertura P90** | % de días en que lo real ≤ P90 | Si el P90 está bien hecho, debe ser cerca de 90%. |

### Cuantiles: P10, P50, P90
En vez de dar un solo número, el modelo da un rango:

- **P50 (mediana):** el valor más probable. La mitad de las veces se vende más y la mitad, menos.
- **P90:** el 90% de las veces se venderá **menos** que esto. Es el número "seguro" para reabastecer.
- **P10:** el 10% de las veces se venderá menos que esto.

**¿Por qué importa?** Si te pregunta el dueño del almacén "¿cuánto arroz pido?", responder con el P50 hace que te quedes corto la mitad de las semanas. Con el P90 te quedas corto 1 de cada 10.

---

## 4. Los modelos: qué es cada uno y por qué está ahí

Van **del más simple al más complejo**. La regla es: un modelo complejo solo vale la pena si le gana a los simples.

### 4.1 `Naive_semanal` (SeasonalNaive)
**Qué hace:** "la próxima semana va a ser igual que la semana pasada". El lunes que viene = el lunes pasado, y así con cada día.

**Por qué está:** es el **piso mínimo**. No necesita entrenamiento ni matemáticas. Si un modelo sofisticado no le gana a esto, no sirve. En inventario, este método es sorprendentemente difícil de superar.

### 4.2 `Promedio_4_semanas` (SeasonalWindowAverage)
**Qué hace:** el próximo lunes = promedio de los últimos 4 lunes. Igual con cada día de la semana.

**Por qué está:** corrige el problema del naive. Si la semana pasada fue rara (un feriado, una promoción), el naive la copia tal cual; el promedio de 4 semanas la suaviza. Sigue siendo fácil de explicar en una frase.

### 4.3 `AutoETS` (suavizado exponencial)
**Qué hace:** ETS = **E**rror, **T**rend (tendencia), **S**easonality (estacionalidad). Es un modelo estadístico clásico que separa la serie en tres partes:
- **Nivel:** cuánto se vende "normalmente" ahora.
- **Tendencia:** si las ventas suben o bajan con el tiempo.
- **Estacionalidad:** el patrón semanal.

"Exponencial" significa que los datos recientes pesan más que los viejos. "Auto" significa que **prueba varias combinaciones** (con o sin tendencia, estacionalidad que suma o que multiplica…) y para cada producto elige la que mejor ajusta.

**Por qué está:** es el estándar de la industria desde hace décadas. Se entrena en milisegundos, corre en cualquier lado (incluida la Pi) y sus resultados se pueden explicar.

### 4.4 `Chronos` (Chronos-Bolt small, de Amazon)
**Qué hace:** es un **"foundation model"** de series de tiempo, algo así como un "ChatGPT de series de tiempo". Amazon lo preentrenó con muchísimas series de tiempo de todo tipo (ventas, clima, tráfico, energía…). Aprendió patrones generales, así que le das el historial de tu producto y predice **sin que lo entrenes** (eso se llama *zero-shot*).

**Por qué está:** es la opción "moderna" que propusiste. La metimos en la comparación para que tú decidas con datos y no por moda. Ventajas que tiene:
- **No hay que entrenarlo.**
- **Da cuantiles (P10/P50/P90) de forma nativa.**
- **Funciona con poco historial**, lo cual sirve cuando el sistema recién se instala y casi no hay datos (lo que se conoce como "arranque en frío").
- La versión `small` tiene ~48 millones de parámetros y corre en CPU: en la Raspberry Pi es viable si corre una vez al día.

**¿Por qué no lo reentrenamos (fine-tuning)?** Ya viene entrenado. Reentrenarlo necesita muchos datos reales y una GPU. Si lo reentrenas con datos inventados, solo aprende tus reglas inventadas. Primero hay que ver si sin entrenar ya es suficiente.

### Lo que dejé fuera y por qué

| Modelo | Por qué no está |
|---|---|
| **Croston / TSB** | Son para productos que se venden de vez en cuando (muchos días en cero). En este dataset solo el 0.0001% de los días tiene cero ventas, así que no aportan. **En tu almacén real sí podrían servir** (por ejemplo, para repuestos que se venden una vez al mes). Están en la misma librería: `from statsforecast.models import CrostonOptimized`. |
| **LightGBM / XGBoost** | Necesitan construir variables a mano (ventas de hace 7 días, promedios, día de la semana, feriados…). Es más trabajo y vale la pena solo si los anteriores no alcanzan. |
| **Chronos-2** | Es la versión más nueva y grande de Chronos (acepta variables extra como feriados o promociones). Es más pesada para la Pi. Si quieres probarla, la librería ya la trae instalada. |
| **Redes neuronales en el ESP32 (TinyML)** | Ver la sección 8. |

---

## 5. Resultados

Backtesting de las 4 últimas semanas de 2017 (del 4 al 31 de diciembre), con los 500 productos. Son 14,000 predicciones diarias por modelo.

### Error diario

| Modelo | MAE (unidades/día) | WAPE | Sesgo |
|---|---|---|---|
| **Chronos** | **6.31** | **14.2%** | +5.2% |
| AutoETS | 7.05 | 15.9% | +8.3% |
| Naive_semanal | 8.74 | 19.7% | +5.1% |
| Promedio_4_semanas | 10.63 | 24.0% | +20.1% |

### Error en el total de la semana

| Modelo | WAPE semanal |
|---|---|
| **Chronos** | **8.4%** |
| Naive_semanal | 10.1% |
| AutoETS | 10.9% |
| Promedio_4_semanas | 20.5% |

### Rango de Chronos (P10–P90)

- Ventas reales ≤ P90: **94.9%** de los días (ideal: ~90%). Es un poco conservador, lo cual es bueno para no quedarse sin stock.
- Ventas reales dentro de P10–P90: **77.1%** (ideal: ~80%). Está bien calibrado.

### Cómo leer esto

1. **Chronos gana en todo, sin entrenarlo.** Se equivoca 10% menos que AutoETS y 28% menos que el naive. En el total semanal, el error es de 8.4%: para un producto que vende unas 300 unidades por semana, te equivocas por unas 25.
2. **Todos predicen de más (sesgo positivo).** No es un error del código: las ventas de este dataset tienen un **patrón anual** (pico en julio, ~67 unidades/día; mínimo en enero, ~35) y caen de ~62 a ~44 unidades/día entre noviembre y diciembre. Los modelos que solo miran semanas recientes "creen" que sigue noviembre.
   - Por eso `Promedio_4_semanas` queda último: promedia semanas de noviembre y predice 20% de más.
   - Chronos mira un historial mucho más largo y capta parte de ese patrón anual.
3. **El naive le gana a AutoETS en el total semanal**, aunque pierde en el error diario. AutoETS tiene más sesgo (+8.3%), y ese error no se compensa al sumar la semana. Por eso hay que mirar varias métricas y no solo una.
4. **Tiempo de cómputo:** en tu PC, el notebook completo tardó **33 minutos**, y casi todo fue AutoETS (ajusta un modelo por producto por semana). Chronos predijo los 500 productos en segundos.

---

## 6. Qué modelo elegir

**Recomendación: Chronos-Bolt small como modelo principal, y el naive semanal como respaldo.**

| Modelo | Decisión | Por qué |
|---|---|---|
| Chronos | **Usar** | El mejor en todas las métricas, el más rápido, da el P90 y no hay que entrenarlo. |
| Naive_semanal | **Respaldo** | Es una línea de código. Si Chronos no carga en la Pi o falla, el sistema sigue dando un número razonable. También sirve para vigilar: si un día Chronos empieza a perder contra el naive con tus datos reales, algo cambió. |
| AutoETS | Descartar | Segundo en error diario, pero lento y con más sesgo. No justifica el tiempo. |
| Promedio_4_semanas | Descartar | El peor: se queda atrás cuando cambia la temporada. |

**Frase para tu reporte:**
> "Comparé 4 métodos con backtesting sobre 500 series reales de Kaggle. Chronos-Bolt sin entrenar obtuvo el menor error (WAPE semanal de 8.4%, contra 10.1% del naive semanal y 10.9% de AutoETS), da un rango de confianza calibrado y corre en segundos en CPU. Por eso lo usamos en el servicio de la Raspberry Pi, con el naive semanal como respaldo."

**Limitación (ponla en el reporte):** solo evaluamos diciembre de 2017, y diciembre trae una caída de temporada. Para estar más seguro, evalúa otros meses (sube `N_WINDOWS`, aunque AutoETS tardará más) y, sobre todo, repite la comparación cuando tengas datos reales de tu almacén.

---

## 7. Cómo correr el notebook

Desde la raíz del repo, en PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r ml/requirements.txt
```

Luego abre `ml/notebooks/01_pronostico_7_dias.ipynb` en VS Code, elige el kernel de `.venv` y dale a **Run All**.
Si prefieres Jupyter en el navegador: `pip install jupyterlab` y luego `jupyter lab`.

Notas:
- **Tarda ~33 minutos completo**, casi todo por AutoETS. Si solo quieres ver Chronos, borra la línea de `AutoETS(...)` en la sección 3 y la palabra `"AutoETS"` de la lista `modelos` en la sección 5: así corre en pocos minutos.
- La primera vez descarga el modelo de Chronos (~200 MB) desde Hugging Face. Después queda guardado en caché.
- Usé `n_jobs=1` en `StatsForecast`: en Windows, con `n_jobs=-1`, los procesos en paralelo se quedan colgados. En la Raspberry Pi (Linux) puedes probar `n_jobs=-1` para que vaya más rápido.

---

## 8. ¿Y el TinyML del ESP32-S3?

El README principal dice que la predicción corre en el ESP32-S3 con TinyML, pero la tabla de la tarea asigna el pronóstico a un **"Python forecasting service"**. Mi interpretación:

- **El TinyML va en la cámara del ESP32-S3**, para detectar o contar productos que salen. Eso **genera** el historial.
- **El pronóstico va en Python en la Raspberry Pi**, que es este notebook.

Razones: Chronos no cabe en un ESP32 (que tiene unos pocos MB de memoria), y predecir 7 días una vez al día no necesita velocidad ni correr sin conexión en el chip.

**Confírmalo con tu profe o tu equipo.** Si te exigen que la predicción corra en el ESP32, la opción es una red neuronal pequeña (últimos 28 días → próximos 7) cuantizada a int8 con TensorFlow Lite Micro. Y la comparas en esta misma tabla contra `Naive_semanal`: si no le gana, no tiene sentido ponerla.

---

## 9. Cosas que en datos reales sí te van a pasar

1. **Salidas ≠ demanda.** Si un producto se agotó, las salidas de ese día son 0, pero la gente sí quería comprar. Si entrenas con esos ceros, el modelo aprende a predecir de menos. Solución: guarda también el stock de cada día y saca del historial los días con stock en cero.
2. **Productos nuevos.** Sin historial, ningún modelo estadístico funciona bien. Chronos o el promedio de las primeras semanas son lo mejor que hay al inicio.
3. **Feriados y promociones.** Este dataset no los marca. Si tu almacén los tiene, anótalos: son la principal razón para pasar a Chronos-2 o LightGBM, que aceptan esas variables.

---

## 10. Siguientes pasos

1. **Validar con el equipo** quién hace qué (sección 8).
2. **Definir la tabla de salidas** en la base de datos, por ejemplo: `salidas(fecha, producto_id, cantidad, stock_restante)`.
3. **Convertir la sección 7 del notebook en un script** (`ml/forecast.py`) que la Raspberry Pi corra todos los días (con cron o con una automatización de Home Assistant) y publique un sensor por producto, por ejemplo `sensor.pronostico_arroz_7d`, con la P50 y la P90 como atributos, vía la API REST de Home Assistant o MQTT.
   Ojo: en el notebook, `total_p90` es la **suma de los P90 de cada día**, no el P90 de la semana. Como los errores diarios se compensan en parte, esa suma es más alta: es un número conservador para reabastecer.
4. **El agente de Ollama** lee esos sensores y responde preguntas en lenguaje natural.

---
---

# Parte 2 · Notebook 02: modelos entrenados por nosotros

`02_comparacion_2017.ipynb` agrega dos modelos que **entrenamos nosotros** (LightGBM y una red neuronal pequeña) y los pone a competir contra Naive semanal y Chronos con un examen más grande.

## 11. Qué cambia respecto al notebook 01

| | Notebook 01 | Notebook 02 |
|---|---|---|
| Examen | 4 semanas (diciembre 2017) | **52 semanas (todo 2017)** |
| Partición | todo lo anterior a cada corte | **por años**: entrenar 2014–2015, validar 2016, probar 2017 |
| Modelos | 4 de librería | Naive, Chronos + **2 entrenados por nosotros** |
| Fuera | – | AutoETS (tardaría horas en 52 semanas) y Promedio 4 semanas (fue el peor en el 01) |

Las 4 últimas semanas del examen son **las mismas del notebook 01**. Por eso el notebook imprime un control: el MAE del naive en diciembre debe dar **8.74**, igual que en el 01. Ya lo verifiqué: da 8.74.

## 12. Orígenes: cómo se arma cada ejemplo

Un **origen** es "el último día que conocemos". Con los datos hasta ese día se predicen los 7 siguientes. Es lo mismo que hará el sistema real: cada día, "hoy" es el origen.

| Parte | Orígenes | Ejemplos (orígenes × 500 productos) |
|---|---|---|
| Entrenamiento | cada día de 2014–2015 (697) | 348,500 |
| Validación | cada día de 2016 (360) | 180,000 |
| Prueba | uno por semana de 2017 (52) | 26,000 |

El entrenamiento empieza a fines de enero de 2014, y no en 2013, porque cada ejemplo necesita 28 días recientes **más un año** de historia para la pista "hace un año".

Ningún objetivo de entrenamiento cae en 2016 y ninguno de validación cae en 2017. El notebook lo comprueba con un `assert`.

## 13. Las 42 pistas y por qué cada una

| Pistas | Cuántas | Por qué |
|---|---|---|
| **Últimos 28 días** ÷ escala | 28 | El nivel actual y el patrón semanal reciente. |
| **La misma semana hace un año** ÷ el promedio de las 4 semanas previas de ese año | 7 | Es la única forma de ver el **patrón anual** (lo que les faltó a los modelos simples en diciembre). Le dice al modelo "el año pasado, esta semana fue 0.75 veces lo normal". |
| **Día de la semana** del primer día a predecir | 7 | Para que sepa en qué posición cae el sábado. Va como siete 0/1 (*one-hot*). |

**Escala** = promedio de los últimos 28 días del producto. Todo se divide entre ella, y la predicción se multiplica de vuelta al final.

**Lo que NO le damos, a propósito:**
- **El nombre o número del producto.** Si lo tuviera, aprendería "el producto 15 vende 60", y eso no sirve en tu almacén.
- **La fecha del año** (mes, día del año). Aprendería el calendario de *este* dataset de Kaggle. "Hace un año" en cambio funciona con el calendario de cualquier negocio.

Con esas dos decisiones, el modelo aprende **formas** y no tamaños ni fechas, y por eso se puede aplicar a **cualquier inventario**.

**Atajo conocido:** si un producto vende menos de 1 unidad por día en promedio, no se normaliza (se divide entre 1). Está marcado en el código con `shortcut:`. Hay que revisarlo con tus datos reales si tienes productos de venta muy esporádica.

## 14. Diseño de LightGBM

- **7 modelos**, uno por cada día a predecir (día 1 … día 7). Es la forma más simple de que LightGBM, que predice un solo número, entregue 7. Se guardan en `ml/models/lightgbm_dia1.txt` … `lightgbm_dia7.txt`.
- **`objective="l1"`**: minimiza el error absoluto, y eso lleva a predecir la **mediana (P50)**, lo mismo que comparamos de Chronos.

| Perilla | Valor | Qué controla |
|---|---|---|
| `learning_rate` | 0.05 | Cuánto corrige cada árbol nuevo. Más bajo: aprende más lento pero más fino. |
| `num_leaves` | 31 | Qué tan complejo puede ser cada árbol. |
| `min_data_in_leaf` | 200 | Cada decisión final debe apoyarse en al menos 200 ejemplos. Evita que memorice casos raros. |
| `feature_fraction` | 0.8 | Cada árbol ve el 80% de las pistas al azar. Otra defensa contra memorizar. |

- **Early stopping (aquí se usa la validación):** agrega árboles mientras mejore en 2016. Si pasan 50 rondas sin mejorar, para. El notebook imprime cuántos árboles quedaron por día.
- **Reentrenamiento final:** con el número de árboles elegido, se entrena otra vez con 2014–2016, para que también aprenda de 2016.

## 15. Diseño de la red neuronal

```
42 pistas → [64 neuronas, ReLU] → [32 neuronas, ReLU] → 7 salidas (día 1 … día 7)
```

- **Parámetros:** (42×64 + 64) + (64×32 + 32) + (32×7 + 7) = **5,063**. Son unos 20 KB en float32 y unos 5 KB en int8: cabe de sobra en el ESP32-S3.
- **¿Por qué un MLP (capas densas) y no LSTM u otra red más "de series de tiempo"?** Con 42 pistas ya preparadas, un MLP alcanza. Además, TensorFlow Lite Micro soporta las capas densas sin problemas, mientras que el soporte de LSTM en microcontroladores es limitado. Y es la red más fácil de explicar.
- **`loss="mae"`**: igual que LightGBM, aprende la mediana.
- **Adam con `learning_rate=1e-3`, `batch_size=512`**: valores estándar para empezar.
- **Early stopping con `patience=5`:** si el error en 2016 no mejora en 5 épocas, para y se queda con la mejor. Luego se reentrena **desde cero** con 2014–2016 durante esas mismas épocas.
- **Curva de aprendizaje:** el notebook la dibuja. Si la línea de validación sube mientras la de entrenamiento baja, la red está memorizando (*overfitting*).
- **Keras sobre PyTorch:** Keras puede funcionar sobre PyTorch o sobre TensorFlow. Uso PyTorch porque ya está instalado (lo trajo Chronos) y así no instalamos TensorFlow (~400 MB) todavía. El archivo `ml/models/red.keras` sirve para los dos, y el **notebook 03** lo abrirá con TensorFlow para convertirlo a int8. Ya comprobé que TensorFlow 2.21 se instala en tu Python 3.13.

## 16. Lo que quedó fuera en esta versión

- **P90 de LightGBM y de la red:** por ahora solo predicen la mediana. Para que den P90 se entrenan con `objective="quantile"` (LightGBM) o con una pérdida *pinball* (la red). Es el siguiente paso si la comparación lo pide.
- **Afinar perillas:** usé valores estándar. Si LightGBM o la red quedan cerca de Chronos, vale la pena probar otras combinaciones contra la validación de 2016 (nunca contra 2017).

## 17. Cómo correrlo

1. Pon `PRUEBA_RAPIDA = True` en la primera celda de código y dale a **Run All**. Usa 20 productos y entrenamientos cortos, y en tu PC tardó **3.5 minutos**. Sirve para comprobar que todo funciona.
2. Vuelve a `PRUEBA_RAPIDA = False` y corre todo otra vez.
   - Chronos tarda **~42 segundos por semana** con los 500 productos, así que **~36 minutos** las 52 semanas.
   - LightGBM y la red no los he medido con los 500 productos; estimo de 10 a 20 minutos entre los dos.
   - En total, **alrededor de una hora**.

Los modelos entrenados quedan en `ml/models/`.

## 18. Resultados

_Pendiente: se llenan después de la corrida completa._ Los números de la prueba rápida no se anotan: con 20 productos y 2 épocas no significan nada.
