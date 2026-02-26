/*
 * Gantry.h
 *
 *  Created on: Jun 18, 2025
 *      Author: conar
 */

#ifndef INC_GANTRY_H_
#define INC_GANTRY_H_

#include <cstdint>
#include "Stepper.h"

struct GantryPosition {
  int32_t x, y, z;
};

/// High-level controller for a 3-axis gantry (X, Y, Z).
class Gantry {
public:
  /// Get the singleton instance
  static Gantry* instance();

  Gantry();
  void begin();


  /// Move each axis by (dx, dy, dz) full-steps, using feedHz as top speed on the longest axis
  void moveBy(int32_t dx, int32_t dy, int32_t dz, uint32_t feedHz);

  void moveTo(int32_t x, int32_t y, uint32_t feedHz);

  static void pauseXYZMotors();
  static void resumeXYZMotors();
  static void cancelXYZMotors();

  GantryPosition getPosition() const;

  // Convenience APIs to set accel/profile per axis from app code
  void setAxisAccel(Stepper::Axis ax, float steps_per_s2);
  void setAccelAll(float steps_per_s2);
  void setAccelProfileAll(Stepper::AccelProfile p);


private:
  static Gantry* _instance;
  uint32_t 		 _minStepHz = 3000;

};

extern "C" {
  /// Initialize all three steppers (call once, e.g. in main() after MX_STEPPER#_Init)
  void MX_GANTRY_Init(void);

  /// C wrapper for moveBy
  void MX_GANTRY_MoveBy(int32_t dx, int32_t dy, int32_t dz, uint32_t feedHz);
  void MX_GANTRY_MoveTo(int32_t x, int32_t y, int32_t z, uint32_t feedHz);
}


#endif /* INC_GANTRY_H_ */
