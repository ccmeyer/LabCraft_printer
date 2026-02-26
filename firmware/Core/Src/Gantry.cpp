/*
 * Gantry.cpp
 *
 *  Created on: Jun 18, 2025
 *      Author: conar
 */

#include "Gantry.h"
#include "Stepper.h"
#include "cmsis_os.h"      // for osDelay
#include <algorithm>       // for std::max
#include <cmath>           // for std::abs
#include <utility>   // <-- for std::pair

// the three C APIs you already have for your steppers:
extern "C" void MX_STEPPERX_Init(void);
extern "C" void MX_STEPPERY_Init(void);
extern "C" void MX_STEPPERZ_Init(void);

extern "C" void MX_STEPPERX_Move(uint8_t dir, uint32_t steps, uint32_t freqHz,uint32_t accelSteps);
extern "C" void MX_STEPPERY_Move(uint8_t dir, uint32_t steps, uint32_t freqHz,uint32_t accelSteps);
extern "C" void MX_STEPPERZ_Move(uint8_t dir, uint32_t steps, uint32_t freqHz,uint32_t accelSteps);

extern "C" uint8_t MX_STEPPERX_IsBusy(void);
extern "C" uint8_t MX_STEPPERY_IsBusy(void);
extern "C" uint8_t MX_STEPPERZ_IsBusy(void);

extern "C" int32_t MX_STEPPERX_GetPos(void);
extern "C" int32_t MX_STEPPERY_GetPos(void);
extern "C" int32_t MX_STEPPERZ_GetPos(void);


//----------------------------------------------------------------------
// Singleton
// singleton init
Gantry* Gantry::_instance = nullptr;

Gantry* Gantry::instance() {
  return _instance;
}

Gantry::Gantry() {};

void Gantry::begin() {
  _instance = this;
}

void Gantry::moveTo(int32_t x, int32_t y, uint32_t feedHz) {
	int32_t currX = MX_STEPPERX_GetPos();
	int32_t currY = MX_STEPPERY_GetPos();

	int32_t dx = x - currX;
	int32_t dy = y - currY;

	moveBy(dx,dy,0,feedHz);
}
//----------------------------------------------------------------------
void Gantry::moveBy(int32_t dx, int32_t dy, int32_t dz, uint32_t /*feedHz unused*/) {
  const uint32_t Nx = (uint32_t)std::abs(dx);
  const uint32_t Ny = (uint32_t)std::abs(dy);
  const uint32_t Nz = (uint32_t)std::abs(dz);

  const uint32_t Nmax = std::max(std::max(Nx, Ny), Nz);
  if (Nmax == 0u) return;

  Stepper* sx = Stepper::stepperX();
  Stepper* sy = Stepper::stepperY();
  Stepper* sz = Stepper::stepperZ();
  if (!sx || !sy || !sz) return;

  // Find which axis is the "longest" for this move
  Stepper* slong = (Nmax == Nx) ? sx : (Nmax == Ny ? sy : sz);
  const uint32_t feedRefHz = slong->maxSpeedHz();  // run the longest at its own max

  auto planHz = [&](Stepper* s, uint32_t Nsteps)->uint32_t {
    if (Nsteps == 0u) return 0u;
    uint64_t v_scaled = (uint64_t)feedRefHz * (uint64_t)Nsteps / (uint64_t)Nmax; // proportional
    uint32_t v = (uint32_t)std::min<uint64_t>(v_scaled, s->maxSpeedHz());        // clamp to axis cap
    if (v < _minStepHz) v = _minStepHz;                                          // floor for smoothness
    return v;
  };

  const uint32_t fx = planHz(sx, Nx);
  const uint32_t fy = planHz(sy, Ny);
  const uint32_t fz = planHz(sz, Nz);

  MX_STEPPERX_Move(dx >= 0, Nx, fx, /*accelSteps ignored*/ 0u);
  MX_STEPPERY_Move(dy >= 0, Ny, fy, /*accelSteps ignored*/ 0u);
  MX_STEPPERZ_Move(dz >= 0, Nz, fz, /*accelSteps ignored*/ 0u);
}

//// moveBy: fan-in three axes so they finish simultaneously
//void Gantry::moveBy(int32_t dx, int32_t dy, int32_t dz, uint32_t feedHz) {
//  // 1) how many steps on each
//  uint32_t absx = std::abs(dx),
//           absy = std::abs(dy),
//           absz = std::abs(dz);
//
//  // 2) longest axis
//  uint32_t longest = std::max({absx, absy, absz});
//  if (longest == 0u) return;  // nothing to do
//
//  // ---- distance-aware policy ------------------------------------------------
//  // The shorter the move, the lower the top speed and the fatter the ramps.
//  // Tunables (steps):
//  const uint32_t L1 = 50u;
//  const uint32_t L2 = 200u;
//  const uint32_t L3 = 1000u;
//  const uint32_t L4 = 2000u;
//
//  // Fixed accel budgets (FULL steps) for medium/large moves (tune as needed)
////  const uint32_t A_MED   = 800u;   // for L2 < longest <= L3
//  const uint32_t A_LONG  = 1500u;  // for L3 < longest <= L4
//  const uint32_t A_XLONG = 2500u;  // for L4 < longest
//
//  // Tunables per bracket
//  float     feedScale     = 1.0f;     // scales the user feedHz
//  uint32_t  minFloorHz    = _minStepHz;
//  bool      useFracAccel  = false;    // true → fractional accel; false → fixed accel
//  float     accelFrac     = 0.0f;     // only used if useFracAccel==true
//  uint32_t  accelFixed    = 0u;       // only used if useFracAccel==false
//
//  if (longest <= L1) {
//    // Very short: very gentle, heavy ramping
//    feedScale    = 0.25f;
//    minFloorHz   = 600u;
//    useFracAccel = true;
//    accelFrac    = 0.90f;
//  } else if (longest <= L2) {
//    // Short: still gentle
//    feedScale    = 0.30f;
//    minFloorHz   = 1200u;
//    useFracAccel = true;
//    accelFrac    = 0.90f;
//  } else if (longest <= L3) {
//    // Medium: fixed accel so we reach speed quickly
//    feedScale    = 0.30f;
//    minFloorHz   = 1200u;
//    useFracAccel = true;
//    accelFrac    = 0.90f;
//  } else if (longest <= L4) {
//    // Long: fixed accel, near full speed
//    feedScale    = 1.00f;
//    minFloorHz   = 2500u;
//    useFracAccel = false;
//    accelFixed   = A_LONG;
//  } else {
//    // Very long: fixed accel, full speed
//    feedScale    = 1.00f;
//    minFloorHz   = _minStepHz;  // let your global floor rule
//    useFracAccel = false;
//    accelFixed   = A_XLONG;
//  }
//
//  const uint32_t feedHzEff = static_cast<uint32_t>(float(feedHz) * feedScale);
//
//  // Time-coupled per-axis top rates so all axes finish together
//  auto rateFor = [&](uint32_t axisSteps)->uint32_t {
//    if (axisSteps == 0u) return 0u;
//    uint32_t f = static_cast<uint32_t>((uint64_t)feedHzEff * axisSteps / longest);
//    // floor is lower for tiny moves; higher for bigger moves
//    uint32_t floorHz = std::min(_minStepHz, minFloorHz);
//    return std::max(f, floorHz);
//  };
//
//  // Per-axis accel budget (FULL steps)
//  auto accelFor = [&](uint32_t axisSteps)->uint32_t {
//    if (axisSteps == 0u) return 0u;
//
//    // never spend more than half the move on accel (triangular fallback)
//    uint32_t cap = axisSteps / 2u;
//    if (cap == 0u) cap = 1u;
//
//    uint32_t a;
//    if (useFracAccel) {
//      a = static_cast<uint32_t>(std::ceil(float(axisSteps) * accelFrac));
//    } else {
//      a = accelFixed;
//    }
//
//    if (a > cap) a = cap;
//    if (a < 1u)  a = 1u;
//    return a;
//  };
//
//  uint32_t fx = rateFor(absx),
//           fy = rateFor(absy),
//           fz = rateFor(absz);
//
//  uint32_t ax = accelFor(absx),
//		   ay = accelFor(absy),
//		   az = accelFor(absz);
//
//  // 4) start all three
//  MX_STEPPERX_Move(dx >= 0, absx, fx, ax);
//  MX_STEPPERY_Move(dy >= 0, absy, fy, ay);
//  MX_STEPPERZ_Move(dz >= 0, absz, fz, az);
//
//}
void Gantry::setAxisAccel(Stepper::Axis ax, float a) {
  if (auto s = Stepper::getAxis(ax)) s->setAccelStepsPerSec2(a);
}
void Gantry::setAccelAll(float a) {
  setAxisAccel(Stepper::X_AXIS, a);
  setAxisAccel(Stepper::Y_AXIS, a);
  setAxisAccel(Stepper::Z_AXIS, a);
}
void Gantry::setAccelProfileAll(Stepper::AccelProfile p) {
  if (auto s = Stepper::stepperX()) s->setAccelProfile(p);
  if (auto s = Stepper::stepperY()) s->setAccelProfile(p);
  if (auto s = Stepper::stepperZ()) s->setAccelProfile(p);
}

void Gantry::pauseXYZMotors() {
  for (auto axis : { Stepper::X_AXIS, Stepper::Y_AXIS, Stepper::Z_AXIS }) {
	if (auto s = Stepper::getAxis(axis)) s->pauseMove();
  }
}
void Gantry::resumeXYZMotors() {
  for (auto axis : { Stepper::X_AXIS, Stepper::Y_AXIS, Stepper::Z_AXIS }) {
	if (auto s = Stepper::getAxis(axis)) s->resumeMove();
  }
}
void Gantry::cancelXYZMotors() {
  for (auto axis : { Stepper::X_AXIS, Stepper::Y_AXIS, Stepper::Z_AXIS }) {
	if (auto s = Stepper::getAxis(axis)) s->cancelMove();
  }
}

GantryPosition Gantry::getPosition() const {
  return {
    MX_STEPPERX_GetPos(),
    MX_STEPPERY_GetPos(),
    MX_STEPPERZ_GetPos()
  };
}

//----------------------------------------------------------------------
// C API
extern "C" {

void MX_GANTRY_Init(void) {
  // make sure each Stepper is configured first
  static Gantry g;
  g.begin();

  MX_STEPPERX_Init();
  MX_STEPPERY_Init();
  MX_STEPPERZ_Init();
}

void MX_GANTRY_MoveBy(int32_t dx, int32_t dy, int32_t dz, uint32_t feedHz) {
  Gantry::instance()->moveBy(dx, dy, dz, feedHz);
}

void MX_GANTRY_MoveTo(int32_t x, int32_t y, int32_t z, uint32_t feedHz) {
  Gantry::instance()->moveTo(x, y, feedHz);
}

} // extern "C"


