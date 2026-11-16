#include <Arduino.h>
#include <tflm_esp32.h>
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "model_data.h"
#include "pronostico.h"

const int TAM_ARENA = 16 * 1024;  // memoria de trabajo de la red (al iniciar se imprime cuánta usa)
alignas(16) uint8_t arena[TAM_ARENA];
tflite::MicroInterpreter* interprete = nullptr;

bool iniciarModelo() {
  const tflite::Model* modelo = tflite::GetModel(model_data);
  if (modelo->version() != TFLITE_SCHEMA_VERSION) {
    Serial.println("ERROR: versión del modelo incompatible con TFLite Micro");
    return false;
  }
  static tflite::MicroMutableOpResolver<1> operaciones;  // la red solo usa capas densas
  operaciones.AddFullyConnected();
  static tflite::MicroInterpreter interpreteRed(modelo, operaciones, arena, TAM_ARENA);
  if (interpreteRed.AllocateTensors() != kTfLiteOk) {
    Serial.println("ERROR: no se pudo preparar el modelo (ver el mensaje de TFLite de arriba; si habla de memoria, subir TAM_ARENA)");
    return false;
  }
  interprete = &interpreteRed;
  Serial.printf("Modelo cargado: %u bytes, arena usada %u de %d bytes\n",
                model_data_len, (unsigned)interprete->arena_used_bytes(), TAM_ARENA);
  return true;
}

float promedio(const float* valores, int n) {
  float suma = 0;
  for (int i = 0; i < n; i++) suma += valores[i];
  return suma / n;
}

bool pronosticar(const Historial& h, float salida[7]) {
  if (interprete == nullptr || h.dia < 0 || h.dia > 6) return false;

  // 1. Las 42 entradas, igual que armar_pistas() en Python
  float x[42] = {0};
  float escala = fmaxf(promedio(h.reciente, 28), 1.0f);
  float base = fmaxf(h.base_anio, 1.0f);
  for (int i = 0; i < 28; i++) x[i] = h.reciente[i] / escala;
  for (int i = 0; i < 7; i++) x[28 + i] = h.anio[i] / base;
  x[35 + h.dia] = 1.0f;

  // 2. De float a int8, con la escala y el punto cero de la entrada
  TfLiteTensor* entrada = interprete->input(0);
  for (int i = 0; i < 42; i++) {
    long q = lroundf(x[i] / entrada->params.scale) + entrada->params.zero_point;
    entrada->data.int8[i] = constrain(q, -128, 127);
  }

  // 3. Ejecutar la red
  if (interprete->Invoke() != kTfLiteOk) return false;

  // 4. De int8 a unidades: se quita la cuantización y se multiplica por la escala del producto
  TfLiteTensor* resultado = interprete->output(0);
  for (int i = 0; i < 7; i++) {
    salida[i] = (resultado->data.int8[i] - resultado->params.zero_point) * resultado->params.scale * escala;
  }
  return true;
}
