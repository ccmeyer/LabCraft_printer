#include "CoordinatedXyExecutor.h"

static_assert(LC_COORDINATED_XY_EXECUTOR_ENABLE == 1,
              "The rollback build retains the coordinated executor");
static_assert(LC_COORDINATED_XY_NORMAL_ROUTE_ENABLE == 0,
              "The A/B rollback build must compile with normal routing disabled");

int coordinatedXyLegacyGateCompileProbe() {
  CoordinatedXyExecutor::Cursor cursor{};
  return CoordinatedXyExecutor::isActive(cursor) ? 1 : 0;
}
