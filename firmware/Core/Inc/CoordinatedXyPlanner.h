#ifndef INC_COORDINATEDXYPLANNER_H_
#define INC_COORDINATEDXYPLANNER_H_

#include "NormalizedCosineProfile.h"

#include <cstdint>

namespace CoordinatedXyPlanner {

enum class Direction : int8_t {
  Negative = -1,
  Stationary = 0,
  Positive = 1,
};

enum class EdgeMask : uint8_t {
  None = 0u,
  X = 1u << 0u,
  Y = 1u << 1u,
};

enum class ProfilePhase : uint8_t {
  Acceleration = 0u,
  Cruise = 1u,
  Deceleration = 2u,
};

enum class PlanStatus : uint8_t {
  Ready = 0u,
  Immediate = 1u,
  InvalidLimits = 2u,
  OutOfRange = 3u,
  ArithmeticOverflow = 4u,
};

enum class TraceStatus : uint8_t {
  Ready = 0u,
  Complete = 1u,
  Busy = 2u,
  InvalidPlan = 3u,
  InvalidState = 4u,
};

struct AxisLimits {
  uint32_t maxRateHz = 0u;
  uint32_t accelerationEdgesPerSec2 = 0u;
};

struct TimerLimits {
  uint32_t inputClockHz = 0u;
  uint32_t maxArr = 0u;
  uint32_t minEdgeIntervalNs = 2000u;
};

struct PlanRequest {
  int64_t deltaX = 0;
  int64_t deltaY = 0;
  uint32_t requestedMasterRateHz = 0u;
  // Zero retains the legacy one-fifth-of-cruise start. A nonzero value is an
  // explicit initial master-edge rate, used by fresh resume plans.
  uint32_t initialMasterRateHz = 0u;
  AxisLimits xLimits{};
  AxisLimits yLimits{};
  TimerLimits timer{};
};

struct CoordinatedXyPlan {
  PlanStatus status = PlanStatus::InvalidLimits;
  Direction xDirection = Direction::Stationary;
  Direction yDirection = Direction::Stationary;
  uint32_t xEdges = 0u;
  uint32_t yEdges = 0u;
  uint32_t masterEdges = 0u;
  uint32_t ddaIncrementX = 0u;
  uint32_t ddaIncrementY = 0u;
  uint32_t ddaThreshold = 0u;

  uint32_t masterRateCapHz = 0u;
  uint32_t masterRateHz = 0u;
  uint32_t initialMasterRateHz = 0u;
  uint32_t xRateHz = 0u;
  uint32_t yRateHz = 0u;
  uint32_t masterAccelerationCapEdgesPerSec2 = 0u;
  uint32_t masterAccelerationEdgesPerSec2 = 0u;
  uint32_t xAccelerationEdgesPerSec2 = 0u;
  uint32_t yAccelerationEdgesPerSec2 = 0u;

  uint32_t accelerationEdges = 0u;
  uint32_t cruiseEdges = 0u;
  uint32_t decelerationEdges = 0u;
  bool triangular = false;

  TimerLimits timer{};
  uint32_t minArr = 0u;
  uint32_t targetArr = 0u;
  uint32_t startArr = 0u;
  NormalizedCosineProfile::RampSpec accelerationRamp{};
  NormalizedCosineProfile::RampSpec decelerationRamp{};
};

struct EdgeEvent {
  uint32_t masterEdgeIndex = 0u;
  EdgeMask mask = EdgeMask::None;
  uint32_t arr = 0u;
  ProfilePhase phase = ProfilePhase::Cruise;
};

struct Cursor {
  uint64_t xAccumulator = 0u;
  uint64_t yAccumulator = 0u;
  uint32_t xEmittedEdges = 0u;
  uint32_t yEmittedEdges = 0u;
  uint32_t completedMasterEdges = 0u;
  uint32_t expectedMasterEdges = 0u;
  uint32_t expectedXEdges = 0u;
  uint32_t expectedYEdges = 0u;
  EdgeEvent cachedEvent{};
  NormalizedCosineProfile::RampCursor accelerationCursor{};
  NormalizedCosineProfile::RampCursor decelerationCursor{};
  bool active = false;
  bool complete = false;
};

constexpr EdgeMask operator|(EdgeMask lhs, EdgeMask rhs) {
  return static_cast<EdgeMask>(static_cast<uint8_t>(lhs) |
                               static_cast<uint8_t>(rhs));
}

constexpr bool contains(EdgeMask mask, EdgeMask axis) {
  return (static_cast<uint8_t>(mask) & static_cast<uint8_t>(axis)) != 0u;
}

PlanStatus prepare(const PlanRequest& request, CoordinatedXyPlan& plan);
TraceStatus begin(const CoordinatedXyPlan& plan, Cursor& cursor);
TraceStatus currentEvent(const Cursor& cursor, EdgeEvent& event);
TraceStatus completeCurrentEdge(const CoordinatedXyPlan& plan, Cursor& cursor);
bool isComplete(const Cursor& cursor);

}  // namespace CoordinatedXyPlanner

#endif /* INC_COORDINATEDXYPLANNER_H_ */
