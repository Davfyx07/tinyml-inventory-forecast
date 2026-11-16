#pragma once

// Historial de un producto: lo que necesita la red para pronosticar los próximos 7 días.
struct Historial {
  float reciente[28];  // ventas de los últimos 28 días, del más antiguo al más reciente
  float anio[7];       // ventas de los mismos 7 días a pronosticar, pero hace 364 días
  float base_anio;     // promedio de los 28 días anteriores a esa semana de hace un año
  int dia;             // día de la semana del primer día pronosticado (0 = lunes ... 6 = domingo)
};

// Carga la red int8 en memoria. Se llama una vez, en setup().
bool iniciarModelo();

// Calcula el pronóstico de los próximos 7 días, en unidades. Retorna false si algo falla.
bool pronosticar(const Historial& h, float salida[7]);
